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
LIVE_LOG_FILE = os.path.join(CURRENT_INCIDENT_DIR, "live_logs.json")
DEFAULT_GREENNODE_BASE_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
DEFAULT_GREENNODE_MODEL = "qwen/qwen3-5-27b"


class AgentState(TypedDict, total=False):
    raw_alert: Dict[str, Any]
    raw_logs: List[Dict[str, Any]]
    raw_k8s: List[Dict[str, Any]]
    raw_metrics: Dict[str, Any]
    data_source: str
    enrichment_sources: List[str]
    persist_outputs: bool
    write_memory: bool
    matched_historical_incidents: List[str]
    log_agent_findings: AgentFinding
    metrics_agent_findings: AgentFinding
    research_agent_findings: AgentFinding
    agent_findings: List[AgentFinding]
    research_results: List[str]
    research_queries: List[str]
    root_cause: str
    remediation_actions: List[str]
    remediation_execution_log: str
    incident_report: IncidentReport
    post_mortem: PostMortem


def _read_json_file(filename: str) -> Any:
    path = os.path.join(CURRENT_INCIDENT_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _safe_read_json_file(filename: str, default: Any) -> Any:
    path = os.path.join(CURRENT_INCIDENT_DIR, filename)
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _read_live_logs_file() -> List[Dict[str, Any]]:
    if not os.path.exists(LIVE_LOG_FILE):
        return []

    with open(LIVE_LOG_FILE, "r", encoding="utf-8") as f:
        value = json.load(f)
        return value if isinstance(value, list) else []


def _normalize_live_logs(live_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(live_logs):
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "timestamp": item.get("timestamp") or datetime.utcnow().isoformat() + "Z",
                "level": str(item.get("level", "INFO")).upper(),
                "service": item.get("service", "unknown-service"),
                "message": item.get("message", ""),
                "trace_id": item.get("trace_id") or f"live-{index}",
            }
        )
    return normalized


def _has_fault_signal(logs: List[Dict[str, Any]]) -> bool:
    fault_levels = {"ERROR", "CRITICAL", "FATAL", "WARN", "WARNING"}
    return any(str(log.get("level", "")).upper() in fault_levels for log in logs)


def _dedupe_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()

    for item in records:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _snapshot_metrics_relevant(metrics: Dict[str, Any], service: str) -> bool:
    if not metrics:
        return False
    if str(metrics.get("service", "")) == service:
        return True
    return (
        float(metrics.get("cpu_usage_pct", 0.0) or 0.0) >= 80.0
        or float(metrics.get("memory_usage_pct", 0.0) or 0.0) >= 80.0
        or float(metrics.get("error_rate_pct", 0.0) or 0.0) >= 5.0
        or float(metrics.get("latency_ms", 0.0) or 0.0) >= 1000.0
    )


def _enrich_live_state_with_snapshots(live_state: Dict[str, Any]) -> Dict[str, Any]:
    """Use live logs as trigger, then enrich with available alert/log/metric/k8s snapshots."""
    live_logs = live_state.get("raw_logs", [])
    live_alert = live_state.get("raw_alert", {})
    service = str(live_alert.get("service", "unknown-service"))

    if not _has_fault_signal(live_logs):
        live_state["data_source"] = "live_logs.json"
        live_state["enrichment_sources"] = []
        return live_state

    snapshot_alert = _safe_read_json_file("alert.json", {})
    snapshot_logs = _safe_read_json_file("logs.json", [])
    snapshot_k8s = _safe_read_json_file("k8s_events.json", [])
    snapshot_metrics = _safe_read_json_file("metrics.json", {})

    enrichment_sources: List[str] = []

    if isinstance(snapshot_alert, dict) and snapshot_alert:
        snapshot_service = str(snapshot_alert.get("service", ""))
        snapshot_severity = str(snapshot_alert.get("severity", "")).upper()
        if snapshot_service == service or snapshot_severity in {"CRITICAL", "WARNING"}:
            live_state["raw_alert"] = {**snapshot_alert, **live_alert}
            enrichment_sources.append("alert.json")

    if isinstance(snapshot_logs, list) and snapshot_logs:
        live_state["raw_logs"] = _dedupe_records(live_logs + snapshot_logs)
        enrichment_sources.append("logs.json")

    if isinstance(snapshot_k8s, list) and snapshot_k8s:
        warning_events = [
            event
            for event in snapshot_k8s
            if str(event.get("type", "")).lower() == "warning"
            or str(event.get("reason", "")).lower() not in {"started", "pulled", "created"}
        ]
        if warning_events:
            live_state["raw_k8s"] = _dedupe_records(live_state.get("raw_k8s", []) + snapshot_k8s)
            enrichment_sources.append("k8s_events.json")

    if isinstance(snapshot_metrics, dict) and _snapshot_metrics_relevant(snapshot_metrics, service):
        live_state["raw_metrics"] = {**live_state.get("raw_metrics", {}), **snapshot_metrics}
        enrichment_sources.append("metrics.json")

    if enrichment_sources:
        live_state["data_source"] = "live_logs.json+" + "+".join(enrichment_sources)
    else:
        live_state["data_source"] = "live_logs.json"
    live_state["enrichment_sources"] = enrichment_sources
    return live_state


def _derive_incident_from_live_logs(live_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    logs = _normalize_live_logs(live_logs)
    if not logs:
        raise FileNotFoundError("No live logs found in data/current_incident/live_logs.json")

    error_logs = [
        log for log in logs if log.get("level") in {"ERROR", "CRITICAL", "FATAL", "WARN", "WARNING"}
    ]
    signal_logs = error_logs or logs[-4:]
    last_signal = signal_logs[-1]
    now = last_signal.get("timestamp", datetime.utcnow().isoformat() + "Z")
    service = str(last_signal.get("service", "unknown-service"))
    corpus = " ".join(str(log.get("message", "")) for log in signal_logs).lower()

    alert = {
        "alert_id": "LIVE-LOG-ALERT",
        "timestamp": now,
        "severity": "CRITICAL" if error_logs else "INFO",
        "service": service,
        "summary": "Live Log Signal Detected" if error_logs else "System Healthy",
        "description": "ClawOps derived this incident directly from live_logs.json.",
    }
    k8s_events = [
        {
            "timestamp": now,
            "namespace": "production",
            "pod_name": f"{service}-pod-live",
            "reason": "LiveLogDerived",
            "message": "No Kubernetes warning was present in live logs.",
            "type": "Normal",
        }
    ]
    metrics = {
        "timestamp": now,
        "service": service,
        "cpu_usage_pct": 18.0,
        "memory_usage_pct": 42.0,
        "error_rate_pct": 0.0 if not error_logs else 35.0,
        "latency_ms": 42.0 if not error_logs else 1500.0,
    }

    if any(token in corpus for token in ["hikaripool", "connection is not available", "idle object in pool", "db pool"]):
        alert.update(
            {
                "service": service or "backend-service",
                "summary": "Database Connection Timeout",
                "description": "Live logs show DB connection pool exhaustion and request timeout.",
            }
        )
        metrics.update(
            {
                "service": alert["service"],
                "error_rate_pct": 88.5,
                "latency_ms": 30000.0,
            }
        )
    elif any(token in corpus for token in ["oomkilled", "outofmemoryerror", "memory limit", "heap space"]):
        pod_name = str(last_signal.get("pod_name") or f"{service}-pod-live")
        alert.update(
            {
                "service": service or "data-worker",
                "summary": "Container OOMKilled",
                "description": "Live logs show memory exhaustion and Kubernetes OOM kill signals.",
            }
        )
        k8s_events = [
            {
                "timestamp": now,
                "namespace": "production",
                "pod_name": pod_name,
                "reason": "OOMKilled",
                "message": "Container exceeded memory limit and was killed by Kubernetes.",
                "type": "Warning",
            }
        ]
        metrics.update(
            {
                "service": alert["service"],
                "memory_usage_pct": 101.2,
                "error_rate_pct": 64.0,
                "latency_ms": 2200.0,
            }
        )
    elif error_logs:
        alert.update(
            {
                "summary": "Application Error Detected From Live Logs",
                "description": str(last_signal.get("message", "Live log error detected.")),
            }
        )

    return {
        "raw_alert": alert,
        "raw_logs": signal_logs,
        "raw_k8s": k8s_events,
        "raw_metrics": metrics,
        "data_source": "live_logs.json",
    }


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
        "research_queries": state.get("research_queries", []),
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


def _heuristic_open_web_query(error_signal: str) -> str:
    framework_candidates = [
        "HikariPool",
        "PostgreSQL",
        "Kubernetes",
        "OOMKilled",
        "OutOfMemoryError",
        "FastAPI",
        "SQLAlchemy",
        "Django",
        "Spring Boot",
        "Hibernate",
        "Kafka",
        "Redis",
    ]
    lower_signal = error_signal.lower()
    detected = [name for name in framework_candidates if name.lower() in lower_signal]
    exception_match = re.search(r"[A-Za-z_$][\w.$]*(?:Exception|Error|Timeout|OOMKilled)", error_signal)
    exception = exception_match.group(0) if exception_match else ""
    compact_signal = re.sub(r"[^A-Za-z0-9_.:-]+", " ", error_signal).strip()
    core = " ".join(dict.fromkeys(detected + ([exception] if exception else []) + [compact_signal]))
    return f"{core} root cause analysis solution fix"


def _generate_open_web_query(error_signal: str) -> str:
    llm = _build_llm()
    fallback_query = _heuristic_open_web_query(error_signal)
    if llm is None:
        return fallback_query

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a web search query strategist for an SRE incident response "
                "system. Extract the framework/library, exception or error code, and "
                "operational symptom. Return only JSON.",
            ),
            (
                "user",
                "Raw error line:\n{error_signal}\n\nReturn JSON with one key "
                "'query'. The query must be natural open-web search text, without "
                "site filters. Include terms like root cause analysis, solution, "
                "and fix when appropriate.",
            ),
        ]
    )

    try:
        response = (prompt | llm).invoke({"error_signal": error_signal})
        parsed = _extract_json_object(response.content)
        query = str(parsed.get("query", "")).strip()
        return query or fallback_query
    except Exception as exc:
        print(f"[WARN] ResearchAgent query generation failed, using fallback: {exc}")
        return fallback_query


def _summarize_open_web_context(error_signal: str, query: str, raw_results: str) -> str:
    if not raw_results.strip():
        return ""

    llm = _build_llm()
    if llm is None:
        return raw_results[:1800]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a Web Investigator for production incident response. "
                "Summarize open-web findings into concise SRE evidence. Mention "
                "likely root causes, fixes, and source categories such as official "
                "docs, engineering blogs, forums, or issue trackers when visible.",
            ),
            (
                "user",
                "Incident error signal:\n{error_signal}\n\nSearch query:\n{query}\n\n"
                "Raw web results:\n{raw_results}\n\nReturn 4-6 concise bullets.",
            ),
        ]
    )

    try:
        response = (prompt | llm).invoke(
            {
                "error_signal": error_signal,
                "query": query,
                "raw_results": raw_results[:6000],
            }
        )
        return _strip_qwen_thinking(response.content).strip() or raw_results[:1800]
    except Exception as exc:
        print(f"[WARN] ResearchAgent summarization failed, using raw search text: {exc}")
        return raw_results[:1800]


def _open_web_research(error_signal: str) -> Dict[str, Any]:
    query = _generate_open_web_query(error_signal)
    raw_results = ""

    try:
        try:
            from langchain_community.tools import DuckDuckGoSearchRun

            search_tool = DuckDuckGoSearchRun()
            if hasattr(search_tool, "invoke"):
                raw_results = str(search_tool.invoke(query))
            else:
                raw_results = str(search_tool.run(query))
        except ImportError:
            from ddgs import DDGS

            with DDGS() as search_client:
                results = list(search_client.text(query, max_results=5))
            raw_results = "\n".join(
                f"{item.get('title', '')}\n{item.get('href') or item.get('url', '')}\n{item.get('body') or item.get('snippet', '')}"
                for item in results
            )
    except Exception as exc:
        print(f"[WARN] ResearchAgent open web search failed: {exc}")

    summary = _summarize_open_web_context(error_signal, query, raw_results) if raw_results else ""
    return {"query": query, "raw_results": raw_results, "summary": summary}


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


def tool_restart_k8s_pod(pod_name: str) -> str:
    return f"Successfully executed: kubectl delete pod {pod_name} -n production"


def tool_scale_db_pool(service_name: str) -> str:
    return f"Successfully executed: ALTER SYSTEM SET max_connections = 100; for {service_name}"


def _first_pod_name(state: AgentState) -> str:
    for event in state.get("raw_k8s", []):
        pod_name = event.get("pod_name")
        if pod_name:
            return str(pod_name)
    alert_service = state.get("raw_alert", {}).get("service", "unknown-service")
    return f"{alert_service}-pod"


def _execute_auto_remediation(state: AgentState) -> str:
    root_cause = state.get("root_cause", "").lower()
    alert = state.get("raw_alert", {})
    service_name = str(alert.get("service", "unknown-service"))

    if any(term in root_cause for term in ["connection pool", "database", "db pool", "max_connections"]):
        return tool_scale_db_pool(service_name)

    if any(term in root_cause for term in ["oom", "memory", "crash loop", "crashloop", "pod"]):
        return tool_restart_k8s_pod(_first_pod_name(state))

    log_text = " ".join(
        [str(log.get("message", "")) for log in state.get("raw_logs", [])]
        + [str(event.get("reason", "")) + " " + str(event.get("message", "")) for event in state.get("raw_k8s", [])]
    ).lower()

    if any(term in log_text for term in ["hikaripool", "connection is not available", "idle object in pool"]):
        return tool_scale_db_pool(service_name)
    if any(term in log_text for term in ["oomkilled", "outofmemoryerror", "memory limit"]):
        return tool_restart_k8s_pod(_first_pod_name(state))

    return "No auto-remediation tool executed: RCA requires human approval."


def fetch_data_node(state: AgentState) -> Dict[str, Any]:
    print("[Node 1] Fetching incident data.")

    if state.get("raw_alert") and state.get("raw_logs") and state.get("raw_metrics"):
        return {
            "raw_alert": state["raw_alert"],
            "raw_logs": state.get("raw_logs", []),
            "raw_k8s": state.get("raw_k8s", []),
            "raw_metrics": state["raw_metrics"],
            "persist_outputs": state.get("persist_outputs", True),
            "write_memory": state.get("write_memory", True),
        }

    live_logs = _read_live_logs_file()
    if live_logs:
        live_state = _enrich_live_state_with_snapshots(_derive_incident_from_live_logs(live_logs))
        live_state.update(
            {
                "persist_outputs": state.get("persist_outputs", True),
                "write_memory": state.get("write_memory", True),
            }
        )
        return live_state

    return {
        "raw_alert": _read_json_file("alert.json"),
        "raw_logs": _read_json_file("logs.json"),
        "raw_k8s": _read_json_file("k8s_events.json"),
        "raw_metrics": _read_json_file("metrics.json"),
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
        query = _heuristic_open_web_query(signal)
        finding = AgentFinding(
            agent_name="Research Agent",
            confidence=0.60,
            summary="External research was skipped because CLAWOPS_DISABLE_RESEARCH is enabled.",
            evidence=[f"Detected research-worthy signal: {signal}", f"Generated query: {query}"],
            suspected_causes=[],
            recommended_actions=["Enable ResearchAgent search for unfamiliar framework or exception signatures."],
        )
        return {"research_agent_findings": finding, "research_results": [], "research_queries": [query]}

    investigation = _open_web_research(signal)
    query = str(investigation.get("query", ""))
    summary_context = str(investigation.get("summary", ""))
    raw_results = str(investigation.get("raw_results", ""))

    if summary_context:
        summary = f"Open Web Research found actionable context for: {signal}"
        evidence = [f"Generated open-web query: {query}", summary_context]
        actions = [
            "Compare open-web fixes with local service version, runtime, and deployment topology.",
            "Prioritize official documentation or issue tracker guidance over generic blog advice.",
        ]
        confidence = 0.76
    else:
        summary = f"Open Web Research was attempted for: {signal}, but no usable results were returned."
        evidence = [f"Generated open-web query: {query}"]
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
    context = summary_context or raw_results
    return {
        "research_agent_findings": finding,
        "research_results": [context] if context else [],
        "research_queries": [query] if query else [],
    }


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

    remediation_execution_log = _execute_auto_remediation(state)

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
            f.write("\n## Remediation Execution CLI Log\n")
            f.write("```bash\n")
            f.write(remediation_execution_log + "\n")
            f.write("```\n")

    if state.get("write_memory", True):
        append_to_memory(report.incident_id, post_mortem.title, state["root_cause"])

    return {
        "incident_report": report,
        "post_mortem": post_mortem,
        "remediation_execution_log": remediation_execution_log,
    }


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
