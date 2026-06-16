import json
import time
from typing import Any, Dict, List, Tuple

import requests
import streamlit as st


DEFAULT_BACKEND_URL = "http://localhost:8000"
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

    .stButton > button {
        width: 100%;
        border-radius: 8px;
        border: 1px solid rgba(34, 197, 94, 0.65);
        background: linear-gradient(90deg, #16a34a, #0891b2);
        color: white;
        font-weight: 800;
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


def _build_chat_context(result: Dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def _render_header() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-title">ClawOps AI - SRE Copilot</div>
            <p class="hero-copy">
                Multi-agent RCA console for production incidents: Vector Memory, Log/Metrics agents,
                external research, and Qwen-powered remediation guidance in one cockpit.
            </p>
        </div>
        <div class="signal-strip">
            <div class="signal"><span>Workflow</span><strong>LangGraph</strong></div>
            <div class="signal"><span>Memory</span><strong>Chroma RAG</strong></div>
            <div class="signal"><span>Research</span><strong>StackOverflow/GitHub</strong></div>
            <div class="signal"><span>Copilot</span><strong>Qwen</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_upload_console(backend_url: str) -> None:
    st.markdown('<div class="section-panel">', unsafe_allow_html=True)
    st.subheader("Incident Intake")
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
            st.info("Upload 4 incident JSON files to unlock the RCA pipeline.")

    with col_right:
        run_clicked = st.button("🚀 Bắt đầu Phân tích RCA", type="primary")

    if run_clicked:
        try:
            payload, missing = _parse_uploaded_files(uploaded_files or [])
            if missing:
                st.error("Missing files: " + ", ".join(missing))
                return

            with st.status("Initializing ClawOps RCA pipeline...", expanded=True) as status:
                status.write("Đang đọc log...")
                time.sleep(0.35)
                status.write("Đang đối chiếu Memory Vector...")
                time.sleep(0.35)
                status.write("Đang tra cứu StackOverflow/GitHub...")
                time.sleep(0.35)
                status.write("Supervisor Agent đang tổng hợp RCA...")
                result = _post_json(f"{backend_url}/api/v1/analyze", payload)
                status.update(label="RCA pipeline completed", state="complete")

            st.session_state.analysis_result = result
            st.session_state.chat_context = _build_chat_context(result)
            st.session_state.chat_messages = []
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
        """,
        unsafe_allow_html=True,
    )
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

    _render_upload_console(backend_url.rstrip("/"))

    if st.session_state.analysis_result:
        _render_incident_report(st.session_state.analysis_result)

    _render_chat(backend_url.rstrip("/"))


if __name__ == "__main__":
    main()
