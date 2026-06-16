import json
import os
import time
from typing import Any, Dict, List, Tuple

import requests
import streamlit as st


DEFAULT_BACKEND_URL = "http://localhost:8000"
LIVE_LOG_FILE = "data/current_incident/live_logs.json"
EXPECTED_FILES = {
    "alert.json": "alert",
    "logs.json": "logs",
    "metrics.json": "metrics",
    "k8s_events.json": "k8s_events",
}


st.set_page_config(
    page_title="ClawOps AI - SRE Copilot",
    page_icon="CL",
    layout="wide",
    initial_sidebar_state="collapsed",
)


st.markdown(
    """
    <style>
    :root {
        --panel: rgba(15, 23, 42, 0.78);
        --panel-soft: rgba(30, 41, 59, 0.72);
        --line: rgba(148, 163, 184, 0.28);
        --text-soft: #cbd5e1;
        --accent: #22c55e;
        --amber: #f59e0b;
        --cyan: #06b6d4;
        --danger: #ef4444;
    }

    .stApp {
        background:
            linear-gradient(180deg, #07111f 0%, #101827 38%, #151515 100%);
        color: #f8fafc;
    }

    .main .block-container {
        max-width: 1180px;
        padding-top: 2.2rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3 {
        letter-spacing: 0;
    }

    .hero {
        border: 1px solid var(--line);
        background: linear-gradient(135deg, rgba(34, 197, 94, 0.14), rgba(6, 182, 212, 0.08)), var(--panel);
        border-radius: 8px;
        padding: 24px 28px;
        margin-bottom: 18px;
    }

    .hero-title {
        font-size: 2.2rem;
        font-weight: 800;
        margin: 0;
        color: #f8fafc;
    }

    .hero-copy {
        color: var(--text-soft);
        font-size: 1.02rem;
        margin: 8px 0 0 0;
        max-width: 850px;
    }

    .signal-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin: 10px 0 22px 0;
    }

    .signal {
        border: 1px solid var(--line);
        background: rgba(2, 6, 23, 0.38);
        border-radius: 8px;
        padding: 12px 14px;
    }

    .signal span {
        display: block;
        color: var(--text-soft);
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    .signal strong {
        color: #f8fafc;
        font-size: 1.05rem;
    }

    .section-panel {
        border: 1px solid var(--line);
        background: var(--panel);
        border-radius: 8px;
        padding: 18px;
        margin-bottom: 16px;
    }

    .rca-box {
        border-left: 4px solid var(--accent);
        background: rgba(34, 197, 94, 0.08);
        padding: 14px 16px;
        border-radius: 6px;
        color: #f8fafc;
    }

    .pill {
        display: inline-block;
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 4px 10px;
        margin: 3px 4px 3px 0;
        background: rgba(15, 23, 42, 0.7);
        color: #e2e8f0;
        font-size: 0.84rem;
    }

    .severity-critical {
        color: #fecaca;
        background: rgba(239, 68, 68, 0.12);
        border-color: rgba(239, 68, 68, 0.42);
    }

    .timeline-item {
        border-left: 2px solid var(--cyan);
        padding: 4px 0 10px 14px;
        margin-left: 6px;
        color: #e2e8f0;
    }

    .action-item {
        border: 1px solid rgba(34, 197, 94, 0.28);
        background: rgba(34, 197, 94, 0.08);
        border-radius: 8px;
        padding: 10px 12px;
        margin: 8px 0;
        color: #ecfdf5;
    }

    div[data-testid="stFileUploader"] section {
        border: 1px dashed rgba(34, 197, 94, 0.55);
        background: rgba(2, 6, 23, 0.30);
        border-radius: 8px;
    }

    @keyframes buttonGlow {
        0% { box-shadow: 0 0 0 rgba(34, 197, 94, 0); }
        50% { box-shadow: 0 0 22px rgba(34, 197, 94, 0.34); }
        100% { box-shadow: 0 0 0 rgba(34, 197, 94, 0); }
    }

    @keyframes buttonSweep {
        0% { transform: translateX(-130%); opacity: 0; }
        28% { opacity: 0.75; }
        100% { transform: translateX(130%); opacity: 0; }
    }

    @keyframes feedbackPop {
        0% { transform: translateY(-6px) scale(0.98); opacity: 0; }
        18% { transform: translateY(0) scale(1); opacity: 1; }
        100% { transform: translateY(0) scale(1); opacity: 1; }
    }

    @keyframes feedbackScan {
        0% { left: -25%; opacity: 0; }
        30% { opacity: 0.9; }
        100% { left: 120%; opacity: 0; }
    }

    .stButton > button {
        width: 100%;
        border-radius: 8px;
        border: 1px solid rgba(34, 197, 94, 0.65);
        background: linear-gradient(90deg, #16a34a, #0891b2);
        color: white;
        font-weight: 800;
        position: relative;
        overflow: hidden;
        min-height: 42px;
        box-shadow: 0 10px 24px rgba(8, 145, 178, 0.16);
        transition:
            transform 140ms ease,
            border-color 140ms ease,
            box-shadow 140ms ease,
            filter 140ms ease;
    }

    .stButton > button::after {
        content: "";
        position: absolute;
        inset: 0;
        width: 42%;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.34), transparent);
        transform: translateX(-130%);
        pointer-events: none;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        border-color: rgba(34, 211, 238, 0.85);
        box-shadow:
            0 14px 32px rgba(6, 182, 212, 0.24),
            0 0 0 1px rgba(34, 197, 94, 0.15) inset;
        filter: saturate(1.12);
    }

    .stButton > button:hover::after {
        animation: buttonSweep 860ms ease;
    }

    .stButton > button:active {
        transform: translateY(1px) scale(0.985);
        box-shadow:
            0 5px 14px rgba(6, 182, 212, 0.16),
            0 0 0 2px rgba(34, 197, 94, 0.24) inset;
        filter: brightness(0.95);
    }

    .stButton > button[kind="primary"] {
        animation: buttonGlow 2.4s ease-in-out infinite;
    }

    .button-feedback {
        position: relative;
        overflow: hidden;
        border: 1px solid rgba(34, 211, 238, 0.36);
        background: linear-gradient(90deg, rgba(6, 182, 212, 0.16), rgba(34, 197, 94, 0.11));
        border-radius: 8px;
        padding: 10px 12px;
        margin: 10px 0 12px 0;
        color: #e0f2fe;
        animation: feedbackPop 420ms ease both;
    }

    .button-feedback::before {
        content: "";
        position: absolute;
        top: 0;
        bottom: 0;
        width: 18%;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.18), transparent);
        animation: feedbackScan 1.25s ease;
    }

    .button-feedback strong {
        color: #f8fafc;
        display: block;
        margin-bottom: 2px;
    }

    @media (max-width: 760px) {
        .signal-strip {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .hero-title {
            font-size: 1.7rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _init_session() -> None:
    st.session_state.setdefault("analysis_result", None)
    st.session_state.setdefault("chat_context", "")
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault("live_stream_enabled", True)
    st.session_state.setdefault("last_triggered_fault", "")
    st.session_state.setdefault("last_button_feedback", None)
    st.session_state.setdefault("suppress_next_healthy_tick", False)


def _parse_uploaded_files(uploaded_files: List[Any]) -> Tuple[Dict[str, Any], List[str]]:
    by_name = {file.name.lower(): file for file in uploaded_files}
    missing = [name for name in EXPECTED_FILES if name not in by_name]
    if missing:
        return {}, missing

    payload: Dict[str, Any] = {"persist_outputs": True, "write_memory": True}
    for filename, payload_key in EXPECTED_FILES.items():
        raw = by_name[filename].getvalue().decode("utf-8")
        payload[payload_key] = json.loads(raw)

    return payload, []


def _post_json(endpoint: str, payload: Dict[str, Any], timeout: int = 360) -> Dict[str, Any]:
    response = requests.post(endpoint, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _get_live_logs(backend_url: str, append_healthy: bool = True) -> List[Dict[str, Any]]:
    try:
        response = requests.get(
            f"{backend_url}/api/v1/live-logs",
            params={"append_healthy": append_healthy},
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("logs", [])
    except Exception:
        if not os.path.exists(LIVE_LOG_FILE):
            return []
        with open(LIVE_LOG_FILE, "r", encoding="utf-8") as f:
            try:
                value = json.load(f)
                return value if isinstance(value, list) else []
            except json.JSONDecodeError:
                return []


def _inject_chaos(backend_url: str, scenario: str) -> Dict[str, Any]:
    return _post_json(f"{backend_url}/api/v1/chaos", {"scenario": scenario}, timeout=30)


def _set_button_feedback(title: str, detail: str) -> None:
    st.session_state.last_button_feedback = {
        "title": title,
        "detail": detail,
        "timestamp": time.time(),
    }


def _render_button_feedback() -> None:
    feedback = st.session_state.get("last_button_feedback")
    if not feedback:
        return

    if time.time() - float(feedback.get("timestamp", 0)) > 6:
        st.session_state.last_button_feedback = None
        return

    title = str(feedback.get("title", "Action triggered"))
    detail = str(feedback.get("detail", "ClawOps is processing the request."))
    st.markdown(
        f"""
        <div class="button-feedback">
            <strong>{title}</strong>
            <span>{detail}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _format_live_logs(logs: List[Dict[str, Any]], limit: int = 36) -> str:
    rows = []
    for item in logs[-limit:]:
        timestamp = item.get("timestamp", "")
        level = str(item.get("level", "INFO")).upper()
        service = item.get("service", "system")
        message = item.get("message", "")
        rows.append(f"{timestamp} | {level:<8} | {service:<16} | {message}")
    return "\n".join(rows) or "Waiting for live logs..."


def _has_error(logs: List[Dict[str, Any]]) -> bool:
    fault_levels = {"ERROR", "CRITICAL", "FATAL"}
    return any(str(item.get("level", "")).upper() in fault_levels for item in logs)


def _fault_fingerprint(logs: List[Dict[str, Any]]) -> str:
    for item in reversed(logs):
        level = str(item.get("level", "")).upper()
        if level in {"ERROR", "CRITICAL", "FATAL"}:
            return f"{item.get('timestamp', '')}|{level}|{item.get('service', '')}|{item.get('message', '')}"
    return ""


def _run_analysis(
    backend_url: str,
    payload: Dict[str, Any],
    status_steps: List[str],
) -> Dict[str, Any]:
    with st.status("ClawOps AI is handling the incident...", expanded=True) as status:
        for step in status_steps:
            status.write(step)
            time.sleep(0.45)
        result = _post_json(f"{backend_url}/api/v1/analyze", payload)
        status.update(label="RCA and auto-remediation completed", state="complete")

    st.session_state.analysis_result = result
    st.session_state.chat_context = _build_chat_context(result)
    st.session_state.chat_messages = []
    return result


def _build_chat_context(result: Dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def _render_header() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-title">ClawOps AI - SRE Copilot</div>
            <p class="hero-copy">
                Multi-agent RCA console for production incidents: Vector Memory, Log/Metrics agents,
                Gemini-style Open Web Research, and Qwen-powered auto-remediation in one cockpit.
            </p>
        </div>
        <div class="signal-strip">
            <div class="signal"><span>Workflow</span><strong>LangGraph</strong></div>
            <div class="signal"><span>Memory</span><strong>Chroma RAG</strong></div>
            <div class="signal"><span>Research</span><strong>Open Web Search</strong></div>
            <div class="signal"><span>Remediation</span><strong>SRE Tools</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_live_dashboard(backend_url: str) -> None:
    st.markdown('<div class="section-panel">', unsafe_allow_html=True)
    st.subheader("Live Log Stream")

    controls = st.columns([0.30, 0.20, 0.20, 0.16, 0.14])
    with controls[0]:
        st.session_state.live_stream_enabled = st.toggle(
            "Live stream",
            value=st.session_state.live_stream_enabled,
        )
    with controls[1]:
        inject_db = st.button("💥 Inject DB Timeout")
    with controls[2]:
        inject_oom = st.button("💥 Inject K8s OOM")
    with controls[3]:
        analyze_now = st.button("Analyze Now")
    with controls[4]:
        reset_logs = st.button("Reset")

    if inject_db:
        try:
            _set_button_feedback(
                "Chaos signal armed",
                "DB timeout fault injected into live log stream.",
            )
            _inject_chaos(backend_url, "DB_POOL_EXHAUSTED")
            st.toast("DB timeout fault injected.")
            st.session_state.last_triggered_fault = ""
            st.session_state.suppress_next_healthy_tick = True
        except requests.RequestException as exc:
            st.error(f"Chaos API error: {exc}")

    if inject_oom:
        try:
            _set_button_feedback(
                "Chaos signal armed",
                "K8s OOM fault injected into live log stream.",
            )
            _inject_chaos(backend_url, "OOM_KILLED")
            st.toast("K8s OOM fault injected.")
            st.session_state.last_triggered_fault = ""
            st.session_state.suppress_next_healthy_tick = True
        except requests.RequestException as exc:
            st.error(f"Chaos API error: {exc}")

    if reset_logs:
        try:
            _set_button_feedback(
                "Live stream reset",
                "Healthy heartbeat logs are back on screen.",
            )
            _post_json(f"{backend_url}/api/v1/live-logs/reset", {}, timeout=15)
            st.session_state.last_triggered_fault = ""
            st.session_state.suppress_next_healthy_tick = True
            st.toast("Live logs reset.")
        except requests.RequestException as exc:
            st.error(f"Live log reset API error: {exc}")

    if analyze_now:
        _set_button_feedback(
            "Manual RCA triggered",
            "ClawOps is collecting live logs, snapshots, memory, and web research.",
        )

    _render_button_feedback()

    append_healthy = (
        st.session_state.live_stream_enabled
        and not st.session_state.suppress_next_healthy_tick
    )
    logs = _get_live_logs(backend_url, append_healthy=append_healthy)
    st.session_state.suppress_next_healthy_tick = False
    live_placeholder = st.empty()
    with live_placeholder.container():
        st.code(_format_live_logs(logs), language="text")

    fingerprint = _fault_fingerprint(logs)
    should_auto_trigger = bool(fingerprint) and fingerprint != st.session_state.last_triggered_fault

    if analyze_now or should_auto_trigger:
        if should_auto_trigger:
            st.warning("ERROR detected in live stream. Auto-triggering ClawOps RCA pipeline.")
        try:
            steps = [
                "Đang đọc live log và snapshot incident...",
                "Đang đối chiếu Memory Vector...",
                "🔍 Đang gọi Gemini-style Research Agent quét thông tin sửa lỗi trên Web toàn cầu...",
                "Supervisor Agent đang tổng hợp RCA từ Open Web + Memory + Metrics...",
                "🤖 Đang đề xuất Auto-Remediation Plan...",
            ]
            _run_analysis(
                backend_url,
                {"persist_outputs": True, "write_memory": True},
                steps,
            )
            st.session_state.last_triggered_fault = fingerprint or f"manual-{time.time()}"
            st.success("Live incident handled. Auto-remediation log is available below.")
        except requests.RequestException as exc:
            st.error(f"RCA API error: {exc}")

    st.markdown("</div>", unsafe_allow_html=True)


def _render_upload_console(backend_url: str) -> None:
    st.markdown('<div class="section-panel">', unsafe_allow_html=True)
    st.subheader("Manual Snapshot Intake (Optional)")
    uploaded_files = st.file_uploader(
        "Upload alert.json, logs.json, metrics.json, k8s_events.json",
        type=["json"],
        accept_multiple_files=True,
    )

    col_left, col_right = st.columns([0.62, 0.38])
    with col_left:
        if uploaded_files:
            present = {file.name.lower() for file in uploaded_files}
            badges = []
            for filename in EXPECTED_FILES:
                state = "ready" if filename in present else "missing"
                badges.append(f'<span class="pill">{filename}: {state}</span>')
            st.markdown("".join(badges), unsafe_allow_html=True)
        else:
            st.info("Optional manual mode. Live dashboard can auto-trigger RCA directly from live_logs.json without uploads.")

    with col_right:
        run_clicked = st.button("🚀 Bắt đầu Phân tích RCA", type="primary")

    if run_clicked:
        try:
            _set_button_feedback(
                "Snapshot RCA launched",
                "Uploaded JSON evidence is being sent to the agent graph.",
            )
            _render_button_feedback()
            payload, missing = _parse_uploaded_files(uploaded_files or [])
            if missing:
                st.error("Missing files: " + ", ".join(missing))
                return

            _run_analysis(
                backend_url,
                payload,
                [
                    "Đang đọc log...",
                    "Đang đối chiếu Memory Vector...",
                    "🔍 Đang gọi Gemini-style Research Agent quét thông tin sửa lỗi trên Web toàn cầu...",
                    "Supervisor Agent đang tổng hợp RCA...",
                    "🤖 Đang đề xuất Auto-Remediation Plan...",
                ],
            )
            st.success("Incident analysis completed.")
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON input: {exc}")
        except requests.RequestException as exc:
            st.error(f"Backend API error: {exc}")
        except Exception as exc:
            st.error(f"Unexpected RCA failure: {exc}")

    st.markdown("</div>", unsafe_allow_html=True)


def _render_incident_report(result: Dict[str, Any]) -> None:
    report = result.get("incident_report", {})
    post_mortem = result.get("post_mortem", {})
    agent_findings = result.get("agent_findings", [])
    memory_matches = result.get("matched_historical_incidents", [])
    metadata = result.get("metadata", {})
    remediation_cli_log = metadata.get("remediation_execution_log", "")

    st.markdown('<div class="section-panel">', unsafe_allow_html=True)
    st.subheader("Incident Command Summary")

    top_cols = st.columns(4)
    top_cols[0].metric("Incident ID", report.get("incident_id", "N/A"))
    top_cols[1].metric("Severity", report.get("severity", "N/A"))
    top_cols[2].metric("Service", ", ".join(report.get("impacted_services", [])) or "N/A")
    top_cols[3].metric("Detected At", report.get("detected_at", "N/A"))

    st.markdown(
        f"""
        <span class="pill severity-critical">{report.get("severity", "UNKNOWN")}</span>
        <span class="pill">{report.get("title", "Untitled incident")}</span>
        <span class="pill">Data source: {metadata.get("data_source", "unknown")}</span>
        """,
        unsafe_allow_html=True,
    )
    enrichment_sources = metadata.get("enrichment_sources", [])
    if enrichment_sources:
        st.caption("Enriched with: " + ", ".join(enrichment_sources))
    st.markdown(f"**Summary:** {report.get('short_summary', '')}")
    st.markdown("</div>", unsafe_allow_html=True)

    left, right = st.columns([0.56, 0.44], gap="large")

    with left:
        st.markdown('<div class="section-panel">', unsafe_allow_html=True)
        st.subheader("Root Cause Analysis")
        st.markdown(
            f'<div class="rca-box">{post_mortem.get("root_cause_analysis", "")}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("### Agent Findings")
        for finding in agent_findings:
            with st.expander(
                f"{finding.get('agent_name', 'Agent')} · confidence {finding.get('confidence', 0):.2f}",
                expanded=finding.get("agent_name") == "Research Agent",
            ):
                st.markdown(finding.get("summary", ""))
                evidence = finding.get("evidence", [])
                if evidence:
                    st.markdown("**Evidence**")
                    for item in evidence[:5]:
                        st.markdown(f"- {item}")
                actions = finding.get("recommended_actions", [])
                if actions:
                    st.markdown("**Recommended actions**")
                    for item in actions:
                        st.markdown(f"- {item}")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="section-panel">', unsafe_allow_html=True)
        st.subheader("Timeline")
        for item in post_mortem.get("timeline", []):
            st.markdown(f'<div class="timeline-item">{item}</div>', unsafe_allow_html=True)

        st.subheader("Remediation Actions")
        for action in post_mortem.get("remediation_actions", []):
            st.markdown(f'<div class="action-item">{action}</div>', unsafe_allow_html=True)
        if remediation_cli_log:
            st.subheader("Remediation Execution CLI Log")
            st.code(remediation_cli_log, language="bash")
        st.markdown("</div>", unsafe_allow_html=True)

    if memory_matches:
        st.markdown('<div class="section-panel">', unsafe_allow_html=True)
        st.subheader("Vector Memory Matches")
        for index, match in enumerate(memory_matches, start=1):
            with st.expander(f"Similar incident #{index}", expanded=index == 1):
                st.markdown(match)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_chat(backend_url: str) -> None:
    st.markdown('<div class="section-panel">', unsafe_allow_html=True)
    st.subheader("SRE Copilot Chat")

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input(
        "Ask a follow-up about this incident...",
        disabled=not bool(st.session_state.chat_context),
    )

    if prompt:
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("ClawOps Copilot is reasoning over the post-mortem..."):
                try:
                    payload = {
                        "question": prompt,
                        "context": st.session_state.chat_context,
                    }
                    answer = _post_json(f"{backend_url}/api/v1/chat", payload, timeout=180)[
                        "answer"
                    ]
                    st.markdown(answer)
                except requests.RequestException as exc:
                    answer = f"Backend chat error: {exc}"
                    st.error(answer)

        st.session_state.chat_messages.append({"role": "assistant", "content": answer})

    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    _init_session()
    _render_header()

    with st.sidebar:
        st.header("Runtime")
        backend_url = st.text_input("FastAPI URL", value=DEFAULT_BACKEND_URL)
        st.caption("Backend must be running before RCA analysis.")

    _render_live_dashboard(backend_url.rstrip("/"))
    _render_upload_console(backend_url.rstrip("/"))

    if st.session_state.analysis_result:
        _render_incident_report(st.session_state.analysis_result)

    _render_chat(backend_url.rstrip("/"))

    if st.session_state.live_stream_enabled:
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    main()
