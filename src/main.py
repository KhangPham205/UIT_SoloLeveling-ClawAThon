from datetime import datetime
from typing import Dict, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from langchain_core.prompts import ChatPromptTemplate

from src.generator import append_normal_logs_tick, get_live_logs, has_fault_logs, inject_chaos_fault, reset_live_logs
from src.graph import _build_llm, _strip_qwen_thinking, run_clawops_analysis
from src.schema import AnalyzeRequest, AnalyzeResponse, ChatRequest, ChatResponse


app = FastAPI(
    title="ClawOps AI",
    version="1.0.0",
    description="Multi-agent incident RCA API powered by LangGraph and Qwen.",
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "clawops-ai"}


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
def analyze_incident(
    request: Optional[AnalyzeRequest] = Body(default=None),
) -> AnalyzeResponse:
    try:
        final_state = run_clawops_analysis(request or AnalyzeRequest())
        return AnalyzeResponse(
            incident_report=final_state["incident_report"],
            post_mortem=final_state["post_mortem"],
            agent_findings=final_state.get("agent_findings", []),
            matched_historical_incidents=final_state.get("matched_historical_incidents", []),
            metadata={
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "llm_provider": "GreenNode MaaS",
                "workflow": "FetchData -> MatchMemory -> LogAgent + MetricsAgent -> ResearchAgent -> SupervisorAgent -> GenReports",
                "remediation_execution_log": final_state.get("remediation_execution_log", ""),
                "data_source": final_state.get("data_source", "request_or_current_incident_json"),
                "enrichment_sources": final_state.get("enrichment_sources", []),
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Missing incident input file: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ClawOps analysis failed: {exc}") from exc


@app.get("/api/v1/live-logs")
def live_logs(append_healthy: bool = Query(default=True)) -> Dict[str, object]:
    try:
        current_logs = get_live_logs()
        if append_healthy and not has_fault_logs(current_logs):
            logs = append_normal_logs_tick()
        else:
            logs = current_logs
        return {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "logs": logs,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read live logs: {exc}") from exc


@app.post("/api/v1/chaos")
def inject_chaos(request: Dict[str, str] = Body(...)) -> Dict[str, object]:
    scenario = request.get("scenario", "DB_POOL_EXHAUSTED")
    try:
        result = inject_chaos_fault(scenario)
        return {
            "status": "injected",
            "scenario": result["scenario"],
            "live_logs": result["live_logs"],
            "incident": result["incident"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chaos injection failed: {exc}") from exc


@app.post("/api/v1/live-logs/reset")
def reset_live_log_stream() -> Dict[str, object]:
    try:
        return {
            "status": "reset",
            "logs": reset_live_logs(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Live log reset failed: {exc}") from exc


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat_with_incident(request: ChatRequest) -> ChatResponse:
    llm = _build_llm()
    if llm is None:
        fallback_answer = (
            "LLM is not configured for chat yet. Please set GREENNODE_API_KEY and "
            "GREENNODE_BASE_URL, then retry. Based on the provided post-mortem, "
            "focus on the listed root cause, remediation actions, and validation metrics."
        )
        return ChatResponse(
            answer=fallback_answer,
            metadata={
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "llm_provider": "GreenNode MaaS",
                "mode": "fallback",
            },
        )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are ClawOps AI, a senior SRE copilot. Answer the user's "
                "follow-up question using only the incident context provided. "
                "Be practical, concise, and include production-ready commands or "
                "config snippets when useful. If the user asks for code, return "
                "clear fenced code blocks.",
            ),
            (
                "user",
                "Incident context:\n{context}\n\nUser question:\n{question}",
            ),
        ]
    )

    try:
        response = (prompt | llm).invoke(
            {"context": request.context, "question": request.question}
        )
        answer = _strip_qwen_thinking(response.content).strip()
        if not answer:
            answer = "The model returned an empty answer. Please retry with a more specific question."
        return ChatResponse(
            answer=answer,
            metadata={
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "llm_provider": "GreenNode MaaS",
                "mode": "llm",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ClawOps chat failed: {exc}") from exc


def main() -> None:
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
