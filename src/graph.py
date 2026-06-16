import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from src.memory import append_to_memory, build_incident_query, semantic_search
from src.schema import AgentFinding, AnalyzeRequest, IncidentReport, PostMortem


load_dotenv()

CURRENT_INCIDENT_DIR = "data/current_incident"
DEFAULT_GREENNODE_BASE_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
DEFAULT_GREENNODE_MODEL = "qwen/qwen3-5-27b"


class AgentState(TypedDict, total=False):
    raw_alert: Dict[str, Any]
    raw_logs: List[Dict[str, Any]]
    raw_k8s: List[Dict[str, Any]]
    raw_metrics: Dict[str, Any]
    persist_outputs: bool
    write_memory: bool
    matched_historical_incidents: List[str]
    log_agent_findings: AgentFinding
    metrics_agent_findings: AgentFinding
    research_agent_findings: AgentFinding
    agent_findings: List[AgentFinding]
    research_results: List[str]
    root_cause: str
    remediation_actions: List[str]
    incident_report: IncidentReport
    post_mortem: PostMortem


def _read_json_file(filename: str) -> Any:
    path = os.path.join(CURRENT_INCIDENT_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_preview(data: Any, max_chars: int = 12000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>"


def _build_llm() -> Optional[ChatOpenAI]:
    if os.getenv("CLAWOPS_DISABLE_LLM", "").lower() in {"1", "true", "yes"}:
        return None

    api_key = os.getenv("GREENNODE_API_KEY")
    if not api_key:
        return None

    return ChatOpenAI(
        api_key=api_key,
        base_url=os.getenv("GREENNODE_BASE_URL", DEFAULT_GREENNODE_BASE_URL),
        model=os.getenv("GREENNODE_MODEL", DEFAULT_GREENNODE_MODEL),
        temperature=1.0,
        top_p=0.95,
        max_tokens=4096,
    )


def _strip_qwen_thinking(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


def _extract_json_object(content: str) -> Dict[str, Any]:
    cleaned = _strip_qwen_thinking(content)
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("LLM response did not contain a JSON object.")

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(cleaned)):
        char = cleaned[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : index + 1])

    raise ValueError("LLM response contained incomplete JSON.")


def _invoke_agent_finding_llm(
    agent_name: str,
    system_prompt: str,
    user_payload: Dict[str, Any],
) -> Optional[AgentFinding]:
    llm = _build_llm()
    if llm is None:
        return None

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "user",
                "Analyze the incident data below and return only valid JSON with "
                "these keys: agent_name, confidence, summary, evidence, "
                "suspected_causes, recommended_actions.\n\n{payload}",
            ),
        ]
    )

    try:
        response = (prompt | llm).invoke({"payload": _json_preview(user_payload)})
        parsed = _extract_json_object(response.content)
        parsed["agent_name"] = agent_name
        return AgentFinding.model_validate(parsed)
    except (ValueError, ValidationError, json.JSONDecodeError, Exception) as exc:
        print(f"[WARN] {agent_name} LLM failed, using heuristic fallback: {exc}")
        return None


def _invoke_supervisor_llm(state: AgentState) -> Optional[Dict[str, Any]]:
    llm = _build_llm()
    if llm is None:
        return None

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are the Supervisor Agent for ClawOps AI. Synthesize findings "
                "from specialist agents, validate them against historical memory, "
                "and produce a production-grade RCA. Return only valid JSON.",
            ),
            (
                "user",
                "Input data:\n{payload}\n\nReturn JSON with keys: "
                "root_cause_analysis, remediation_actions.",
            ),
        ]
    )

    payload = {
        "alert": state["raw_alert"],
        "historical_memory_top_2": state.get("matched_historical_incidents", []),
        "log_agent": state["log_agent_findings"].model_dump(),
        "metrics_agent": state["metrics_agent_findings"].model_dump(),
        "external_research": state.get("research_results", []),
    }

    try:
        response = (prompt | llm).invoke({"payload": _json_preview(payload)})
        parsed = _extract_json_object(response.content)
        if not isinstance(parsed.get("remediation_actions"), list):
            parsed["remediation_actions"] = [str(parsed.get("remediation_actions", ""))]
        return parsed
    except (ValueError, json.JSONDecodeError, Exception) as exc:
        print(f"[WARN] Supervisor LLM failed, using heuristic fallback: {exc}")
        return None


def _collect_log_evidence(logs: List[Dict[str, Any]], k8s_events: List[Dict[str, Any]]) -> List[str]:
    evidence: List[str] = []

    for log in logs:
        level = str(log.get("level", "")).upper()
        if level in {"ERROR", "FATAL", "WARN", "WARNING"}:
            evidence.append(
                f"{log.get('timestamp', 'unknown')} {level} {log.get('service', '')}: "
                f"{log.get('message', '')}"
            )

    for event in k8s_events:
        event_type = str(event.get("type", "")).lower()
        reason = str(event.get("reason", ""))
        if event_type == "warning" or reason.lower() not in {"started", "pulled", "created"}:
            evidence.append(
                f"{event.get('timestamp', 'unknown')} k8s {event.get('pod_name', '')} "
                f"{reason}: {event.get('message', '')}"
            )

    return evidence[:6]


def _extract_research_signal(
    logs: List[Dict[str, Any]],
    k8s_events: List[Dict[str, Any]],
    log_finding: AgentFinding,
) -> Optional[str]:
    messages = [str(log.get("message", "")) for log in logs]
    messages.extend(str(event.get("message", "")) for event in k8s_events)
    messages.extend(log_finding.evidence)
    corpus = "\n".join(messages)
    lower_corpus = corpus.lower()

    exception_match = re.search(
        r"([A-Za-z_$][\w.$]*(?:Exception|Error)(?::\s*[^\n\r]+)?)",
        corpus,
    )
    if exception_match:
        return exception_match.group(1)[:220]

    framework_terms = [
        "hikaripool",
        "sqlalchemy",
        "django",
        "fastapi",
        "uvicorn",
        "spring",
        "hibernate",
        "kafka",
        "redis",
        "celery",
        "grpc",
        "postgresql.driver",
        "node.js",
        "next.js",
    ]

    if any(term in lower_corpus for term in framework_terms):
        for log in logs:
            message = str(log.get("message", "")).strip()
            if message and any(term in message.lower() for term in framework_terms):
                return message[:220]

    if "application log anomaly requires deeper inspection" in " ".join(log_finding.suspected_causes).lower():
        for log in logs:
            level = str(log.get("level", "")).upper()
            message = str(log.get("message", "")).strip()
            if level in {"ERROR", "FATAL", "WARN", "WARNING"} and message:
                return message[:220]

    return None


def _research_disabled() -> bool:
    return os.getenv("CLAWOPS_DISABLE_RESEARCH", "").lower() in {"1", "true", "yes"}


def _duckduckgo_research(error_signal: str, max_results: int = 2) -> List[str]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        queries = [
            f"site:stackoverflow.com OR site:github.com {error_signal}",
            f'"{error_signal}" stackoverflow github issue',
            f"{error_signal} production incident fix",
        ]

        results = []
        with DDGS() as search_client:
            for query in queries:
                results = list(search_client.text(query, max_results=max_results))
                if results:
                    break
    except Exception as exc:
        print(f"[WARN] ResearchAgent search failed: {exc}")
        return []

    summaries: List[str] = []
    for index, result in enumerate(results[:max_results], start=1):
        title = result.get("title") or "Untitled result"
        url = result.get("href") or result.get("url") or ""
        snippet = result.get("body") or result.get("snippet") or ""
        summaries.append(f"{index}. {title}\nURL: {url}\nSummary: {snippet}")

    return summaries


def _heuristic_log_finding(
    alert: Dict[str, Any],
    logs: List[Dict[str, Any]],
    k8s_events: List[Dict[str, Any]],
) -> AgentFinding:
    evidence = _collect_log_evidence(logs, k8s_events)
    text = " ".join(
        [alert.get("summary", ""), alert.get("description", "")]
        + [str(log.get("message", "")) for log in logs]
        + [str(event.get("reason", "")) + " " + str(event.get("message", "")) for event in k8s_events]
    ).lower()

    suspected_causes: List[str] = []
    actions: List[str] = []

    if any(token in text for token in ["hikaripool", "connection pool", "idle object", "db connection"]):
        suspected_causes.append("Database connection pool exhaustion")
        actions.extend(
            [
                "Inspect active DB sessions and connection leak indicators.",
                "Scale or restart the affected backend pods after validating DB health.",
                "Tune HikariCP max pool size, timeout, and leak detection thresholds.",
            ]
        )
    if any(token in text for token in ["oomkilled", "outofmemoryerror", "memory limit"]):
        suspected_causes.append("Container memory limit exceeded")
        actions.extend(
            [
                "Capture heap or memory profile before restarting the workload.",
                "Increase memory limit or reduce worker concurrency.",
            ]
        )
    if "crashloopbackoff" in text:
        suspected_causes.append("Pod crash loop")
        actions.append("Inspect the last terminated container logs and deployment configuration.")

    if not suspected_causes:
        suspected_causes.append("Application log anomaly requires deeper inspection")
        actions.append("Correlate trace IDs, pod restarts, and recent deployments.")

    return AgentFinding(
        agent_name="Log Agent",
        confidence=0.82 if evidence else 0.55,
        summary=f"Log and Kubernetes signals point to: {', '.join(suspected_causes)}.",
        evidence=evidence or ["No high-severity log or Kubernetes warning event was found."],
        suspected_causes=suspected_causes,
        recommended_actions=list(dict.fromkeys(actions)),
    )


def _heuristic_metrics_finding(metrics: Dict[str, Any]) -> AgentFinding:
    cpu = float(metrics.get("cpu_usage_pct", 0.0) or 0.0)
    memory = float(metrics.get("memory_usage_pct", 0.0) or 0.0)
    error_rate = float(metrics.get("error_rate_pct", 0.0) or 0.0)
    latency = float(metrics.get("latency_ms", 0.0) or 0.0)

    evidence = [
        f"cpu_usage_pct={cpu}",
        f"memory_usage_pct={memory}",
        f"error_rate_pct={error_rate}",
        f"latency_ms={latency}",
    ]
    suspected_causes: List[str] = []
    actions: List[str] = []

    if cpu >= 90.0:
        suspected_causes.append("CPU saturation")
        actions.append("Scale replicas or inspect CPU-heavy code paths.")
    if memory >= 90.0:
        suspected_causes.append("Memory pressure or leak")
        actions.append("Review memory limits, heap size, and allocation spikes.")
    if error_rate >= 5.0 and latency >= 1000.0 and cpu < 80.0 and memory < 80.0:
        suspected_causes.append("Downstream dependency bottleneck")
        actions.append("Check database and external dependency saturation.")
    elif error_rate >= 5.0:
        suspected_causes.append("Elevated application error rate")
        actions.append("Inspect recent releases and error traces.")
    if latency >= 1000.0:
        suspected_causes.append("Severe request latency degradation")
        actions.append("Profile slow endpoints and dependency calls.")

    if not suspected_causes:
        suspected_causes.append("Metrics are not showing resource saturation")
        actions.append("Prioritize logs, traces, and dependency health checks.")

    return AgentFinding(
        agent_name="Metrics Agent",
        confidence=0.85 if error_rate >= 5.0 or cpu >= 90.0 or memory >= 90.0 else 0.60,
        summary=f"Metrics indicate: {', '.join(suspected_causes)}.",
        evidence=evidence,
        suspected_causes=list(dict.fromkeys(suspected_causes)),
        recommended_actions=list(dict.fromkeys(actions)),
    )


def _heuristic_supervisor_summary(state: AgentState) -> Dict[str, Any]:
    alert = state["raw_alert"]
    log_finding = state["log_agent_findings"]
    metrics_finding = state["metrics_agent_findings"]
    research_finding = state.get("research_agent_findings")
    all_causes = " ".join(log_finding.suspected_causes + metrics_finding.suspected_causes).lower()

    if "database connection pool exhaustion" in all_causes:
        root_cause = (
            "The most likely root cause is database connection pool exhaustion in "
            f"{alert.get('service', 'the affected service')}. Log evidence shows DB "
            "connection wait timeouts, while metrics show a high error rate and severe "
            "latency without CPU or memory saturation. This combination indicates the "
            "application could not obtain database connections fast enough rather than "
            "failing because of local compute pressure."
        )
    elif "memory" in all_causes or "oom" in all_causes:
        root_cause = (
            "The incident is most likely caused by memory exhaustion. Kubernetes and "
            "runtime signals point to container termination or memory pressure, and the "
            "service should be treated as unstable until memory usage is profiled."
        )
    elif "cpu saturation" in all_causes:
        root_cause = (
            "The incident is most likely caused by CPU saturation. Metrics crossed the "
            "critical threshold and latency increased, which is consistent with request "
            "queues building up inside the service."
        )
    else:
        root_cause = (
            "The incident requires additional trace-level investigation. Specialist "
            "agents found anomalies, but the current evidence does not isolate a single "
            "infrastructure or application failure mode with high confidence."
        )

    actions = []
    actions.extend(log_finding.recommended_actions)
    actions.extend(metrics_finding.recommended_actions)
    if research_finding:
        actions.extend(research_finding.recommended_actions)
    actions.append("Keep the incident open until the remediation is validated by metrics.")

    return {
        "root_cause_analysis": root_cause,
        "remediation_actions": list(dict.fromkeys(actions)),
    }


def fetch_data_node(state: AgentState) -> Dict[str, Any]:
    print("[Node 1] Fetching incident data.")

    return {
        "raw_alert": state.get("raw_alert") or _read_json_file("alert.json"),
        "raw_logs": state.get("raw_logs") or _read_json_file("logs.json"),
        "raw_k8s": state.get("raw_k8s") or _read_json_file("k8s_events.json"),
        "raw_metrics": state.get("raw_metrics") or _read_json_file("metrics.json"),
        "persist_outputs": state.get("persist_outputs", True),
        "write_memory": state.get("write_memory", True),
    }


def match_memory_node(state: AgentState) -> Dict[str, Any]:
    print("[Node 2] Retrieving Top-2 similar historical incidents.")
    alert = state["raw_alert"]
    alert_summary = " ".join(
        [
            str(alert.get("summary", "")),
            str(alert.get("description", "")),
            build_incident_query(
                alert=alert,
                logs=state["raw_logs"],
                metrics=state["raw_metrics"],
                k8s_events=state["raw_k8s"],
            ),
        ]
    )
    return {"matched_historical_incidents": semantic_search(alert_summary, top_k=2)}


def log_agent_node(state: AgentState) -> Dict[str, Any]:
    print("[Agent] Log Agent analyzing logs and Kubernetes events.")
    payload = {
        "alert": state["raw_alert"],
        "logs": state["raw_logs"],
        "kubernetes_events": state["raw_k8s"],
        "historical_memory_top_2": state.get("matched_historical_incidents", []),
    }
    system_prompt = (
        "You are Log Agent, a production SRE specialist focused on application logs "
        "and Kubernetes events. Identify concrete evidence, probable causes, and "
        "operator actions. Be concise and evidence-driven."
    )
    finding = _invoke_agent_finding_llm("Log Agent", system_prompt, payload)
    return {"log_agent_findings": finding or _heuristic_log_finding(state["raw_alert"], state["raw_logs"], state["raw_k8s"])}


def research_agent_node(state: AgentState) -> Dict[str, Any]:
    print("[Agent] Research Agent checking whether external research is needed.")
    signal = _extract_research_signal(
        logs=state["raw_logs"],
        k8s_events=state["raw_k8s"],
        log_finding=state["log_agent_findings"],
    )

    if not signal:
        finding = AgentFinding(
            agent_name="Research Agent",
            confidence=0.70,
            summary="No unfamiliar exception or framework-specific error required external research.",
            evidence=["Research skipped because Log Agent did not detect a research-worthy error signature."],
            suspected_causes=[],
            recommended_actions=[],
        )
        return {"research_agent_findings": finding, "research_results": []}

    if _research_disabled():
        finding = AgentFinding(
            agent_name="Research Agent",
            confidence=0.60,
            summary="External research was skipped because CLAWOPS_DISABLE_RESEARCH is enabled.",
            evidence=[f"Detected research-worthy signal: {signal}"],
            suspected_causes=[],
            recommended_actions=["Enable ResearchAgent search for unfamiliar framework or exception signatures."],
        )
        return {"research_agent_findings": finding, "research_results": []}

    results = _duckduckgo_research(signal, max_results=2)
    if results:
        summary = f"External research found {len(results)} relevant references for: {signal}"
        evidence = results
        actions = [
            "Compare the external references with local logs before applying fixes.",
            "Prefer official issue threads or accepted answers that match the exact version and stack.",
        ]
        confidence = 0.72
    else:
        summary = f"External research was attempted for: {signal}, but no usable results were returned."
        evidence = [f"Search query: site:stackoverflow.com OR site:github.com {signal}"]
        actions = ["Continue with local RCA evidence because external research was unavailable."]
        confidence = 0.45

    finding = AgentFinding(
        agent_name="Research Agent",
        confidence=confidence,
        summary=summary,
        evidence=evidence,
        suspected_causes=[],
        recommended_actions=actions,
    )
    return {"research_agent_findings": finding, "research_results": results}


def metrics_agent_node(state: AgentState) -> Dict[str, Any]:
    print("[Agent] Metrics Agent analyzing service metrics.")
    payload = {
        "alert": state["raw_alert"],
        "metrics": state["raw_metrics"],
        "historical_memory_top_2": state.get("matched_historical_incidents", []),
    }
    system_prompt = (
        "You are Metrics Agent, a production SRE specialist focused on CPU, memory, "
        "error-rate, and latency signals. Identify whether the incident is local "
        "resource pressure or a dependency bottleneck."
    )
    finding = _invoke_agent_finding_llm("Metrics Agent", system_prompt, payload)
    return {"metrics_agent_findings": finding or _heuristic_metrics_finding(state["raw_metrics"])}


def supervisor_agent_node(state: AgentState) -> Dict[str, Any]:
    print("[Agent] Supervisor Agent synthesizing root cause.")
    llm_result = _invoke_supervisor_llm(state)
    result = llm_result or _heuristic_supervisor_summary(state)

    root_cause = str(result.get("root_cause_analysis", "")).strip()
    actions = result.get("remediation_actions", [])
    if not isinstance(actions, list):
        actions = [str(actions)]

    if not root_cause:
        root_cause = _heuristic_supervisor_summary(state)["root_cause_analysis"]

    return {
        "root_cause": root_cause,
        "remediation_actions": [str(action) for action in actions if str(action).strip()],
        "agent_findings": [
            state["log_agent_findings"],
            state["metrics_agent_findings"],
            state["research_agent_findings"],
        ],
    }


def generate_deliverables_node(state: AgentState) -> Dict[str, Any]:
    print("[Node 4] Generating incident report and post-mortem.")
    alert = state["raw_alert"]
    incident_id = "INC-" + datetime.utcnow().strftime("%Y%m%d-%H%M%S")

    report = IncidentReport(
        incident_id=incident_id,
        title=f"Incident: {alert.get('service', 'unknown-service')}",
        severity=alert.get("severity", "CRITICAL"),
        detected_at=alert.get("timestamp", datetime.utcnow().isoformat() + "Z"),
        impacted_services=[alert.get("service", "unknown-service")],
        short_summary=alert.get("description") or alert.get("summary") or "Incident detected.",
    )

    post_mortem = PostMortem(
        incident_id=report.incident_id,
        title=f"Post-Mortem: {alert.get('summary', report.title)}",
        root_cause_analysis=state["root_cause"],
        timeline=[
            f"{alert.get('timestamp', 'unknown')}: Monitoring alert received.",
            "ClawOps FetchData loaded alert, logs, Kubernetes events, and metrics.",
            "Memory node retrieved the Top-2 similar historical incidents.",
            "Log Agent and Metrics Agent completed specialist analysis.",
            "Research Agent checked external references for unfamiliar error signatures.",
            "Supervisor Agent synthesized the final root cause.",
        ],
        remediation_actions=state.get("remediation_actions")
        or ["Validate the suspected root cause and apply the relevant service runbook."],
        similar_past_incidents=state.get("matched_historical_incidents", []),
    )

    if state.get("persist_outputs", True):
        os.makedirs(CURRENT_INCIDENT_DIR, exist_ok=True)
        with open(os.path.join(CURRENT_INCIDENT_DIR, "incident_report.json"), "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=4))

        with open(os.path.join(CURRENT_INCIDENT_DIR, "POST_MORTEM.md"), "w", encoding="utf-8") as f:
            f.write(f"# {post_mortem.title}\n\n")
            f.write(f"**Incident ID:** {post_mortem.incident_id}\n\n")
            f.write("## Root Cause Analysis\n")
            f.write(post_mortem.root_cause_analysis + "\n\n")
            f.write("## Specialist Agent Findings\n")
            for finding in state.get("agent_findings", []):
                f.write(f"### {finding.agent_name} - confidence {finding.confidence:.2f}\n")
                f.write(f"{finding.summary}\n\n")
                for item in finding.evidence:
                    f.write(f"- Evidence: {item}\n")
                f.write("\n")
            f.write("## Remediation Actions\n")
            for action in post_mortem.remediation_actions:
                f.write(f"- [ ] {action}\n")

    if state.get("write_memory", True):
        append_to_memory(report.incident_id, post_mortem.title, state["root_cause"])

    return {"incident_report": report, "post_mortem": post_mortem}


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("FetchData", fetch_data_node)
    workflow.add_node("MatchMemory", match_memory_node)
    workflow.add_node("LogAgent", log_agent_node)
    workflow.add_node("ResearchAgent", research_agent_node)
    workflow.add_node("MetricsAgent", metrics_agent_node)
    workflow.add_node("SupervisorAgent", supervisor_agent_node)
    workflow.add_node("GenReports", generate_deliverables_node)

    workflow.set_entry_point("FetchData")
    workflow.add_edge("FetchData", "MatchMemory")
    workflow.add_edge("MatchMemory", "LogAgent")
    workflow.add_edge("MatchMemory", "MetricsAgent")
    workflow.add_edge("LogAgent", "ResearchAgent")
    workflow.add_edge(["ResearchAgent", "MetricsAgent"], "SupervisorAgent")
    workflow.add_edge("SupervisorAgent", "GenReports")
    workflow.add_edge("GenReports", END)

    return workflow.compile()


clawops_agent = build_graph()


def run_clawops_analysis(request: Optional[AnalyzeRequest | Dict[str, Any]] = None) -> AgentState:
    if request is None:
        initial_state: AgentState = {}
    elif isinstance(request, AnalyzeRequest):
        initial_state = {
            "raw_alert": request.alert.model_dump() if request.alert else None,
            "raw_logs": [item.model_dump() for item in request.logs] if request.logs else None,
            "raw_k8s": [item.model_dump() for item in request.k8s_events] if request.k8s_events else None,
            "raw_metrics": request.metrics.model_dump() if request.metrics else None,
            "persist_outputs": request.persist_outputs,
            "write_memory": request.write_memory,
        }
    else:
        initial_state = dict(request)

    return clawops_agent.invoke(initial_state)
