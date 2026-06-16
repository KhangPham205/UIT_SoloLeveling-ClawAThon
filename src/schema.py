from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Alert(BaseModel):
    alert_id: str
    timestamp: str
    severity: str
    service: str
    summary: str
    description: str


class LogEntry(BaseModel):
    timestamp: str
    level: str
    service: str
    message: str
    trace_id: Optional[str] = None


class K8sEvent(BaseModel):
    timestamp: str
    namespace: str
    pod_name: str
    reason: str
    message: str
    type: str


class MetricSnapshot(BaseModel):
    timestamp: str
    service: str
    cpu_usage_pct: float
    memory_usage_pct: float
    error_rate_pct: float
    latency_ms: float


class AgentFinding(BaseModel):
    agent_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    evidence: List[str] = Field(default_factory=list)
    suspected_causes: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)


class IncidentReport(BaseModel):
    incident_id: str
    title: str
    severity: str
    detected_at: str
    impacted_services: List[str]
    short_summary: str = Field(
        description="A concise incident summary under 300 characters."
    )


class PostMortem(BaseModel):
    incident_id: str
    title: str
    root_cause_analysis: str = Field(
        description="Detailed root cause analysis with evidence and logic."
    )
    timeline: List[str] = Field(
        description="Incident timeline from detection through RCA."
    )
    remediation_actions: List[str] = Field(
        description="Immediate mitigation and prevention actions."
    )
    similar_past_incidents: List[str] = Field(
        description="Top similar historical incidents from memory."
    )


class AnalyzeRequest(BaseModel):
    alert: Optional[Alert] = None
    logs: Optional[List[LogEntry]] = None
    k8s_events: Optional[List[K8sEvent]] = None
    metrics: Optional[MetricSnapshot] = None
    persist_outputs: bool = True
    write_memory: bool = True


class AnalyzeResponse(BaseModel):
    incident_report: IncidentReport
    post_mortem: PostMortem
    agent_findings: List[AgentFinding]
    matched_historical_incidents: List[str]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    context: str = Field(min_length=1)


class ChatResponse(BaseModel):
    answer: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
