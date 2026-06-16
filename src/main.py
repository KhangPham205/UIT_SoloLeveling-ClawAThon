from datetime import datetime
from typing import Dict, Optional

from fastapi import Body, FastAPI, HTTPException
from langchain_core.prompts import ChatPromptTemplate

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
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Missing incident input file: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ClawOps analysis failed: {exc}") from exc


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
