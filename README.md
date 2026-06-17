# ClawOps AI

> **> Multi-Agent AI SRE Copilot for Incident Detection, Root Cause Analysis, and Auto-Remediation**

## Problem Statement

Modern cloud-native systems are increasingly built on distributed microservices architectures, making incident response significantly more complex.

When production incidents occur, Site Reliability Engineers (SREs) and DevOps teams must manually inspect logs, correlate metrics, analyze Kubernetes events, search internal documentation, and investigate external resources before identifying the root cause. This process is time-consuming, stressful, and highly dependent on individual expertise, often resulting in prolonged service outages and increased Mean Time To Recovery (MTTR).

## 🎯 Target Users

ClawOps AI is designed for:

- Site Reliability Engineers (SREs)
- DevOps Engineers
- Platform Engineering Teams
- Backend Engineers responsible for production operations
- Enterprise Operations Teams managing cloud infrastructure

These users frequently handle critical incidents and require rapid, accurate insights to restore system stability.

## 🤖 How ClawOps AI Solves the Problem

ClawOps AI acts as an autonomous SRE Copilot powered by a multi-agent architecture.

When an alert is triggered, the system automatically initiates an incident investigation workflow:

#### 1. Detection

Continuously monitors real-time logs and operational signals to identify anomalies and incidents as soon as they occur.

#### 2. Investigation

Specialized AI agents analyze logs, metrics, traces, and infrastructure events to gather evidence and understand the incident context.

#### 3. Knowledge Retrieval (RAG)

A Vector RAG system searches historical incidents, runbooks, and operational documentation to identify similar failure patterns and previously successful resolutions.

#### 4. Open Web Research

Additional agents perform targeted web searches to discover solutions for emerging issues that are not yet documented internally.

#### 5. Root Cause Analysis (RCA)

All collected evidence is synthesized into a structured Root Cause Analysis report with supporting reasoning and confidence scores.

#### 6. Remediation Simulation

The system evaluates potential remediation actions and simulates automated recovery procedures before presenting recommendations to engineers.

## ⚡ Value Proposition

ClawOps AI dramatically reduces incident investigation time from hours of manual analysis to seconds of autonomous reasoning.

By automating Root Cause Analysis, surfacing relevant historical knowledge, and recommending evidence-based remediation actions, the platform helps organizations:

- Reduce Mean Time To Recovery (MTTR)
- Minimize human error during critical outages
- Improve operational efficiency
- Accelerate knowledge sharing across engineering teams
- Lower cognitive load and operational stress on SREs and DevOps engineers
- Improve overall system reliability and service availability

ClawOps AI transforms incident management from a reactive troubleshooting process into a proactive, intelligent, and scalable operational workflow.


## 🔄 High-Level Workflow

```text
Alert Triggered
       │
       ▼
Real-Time Detection
       │
       ▼
Multi-Agent Investigation
       │
       ├── Log Analysis
       ├── Metrics Analysis
       ├── Kubernetes Events Analysis
       ├── Historical Incident RAG
       └── Open Web Search
       │
       ▼
Root Cause Analysis (RCA)
       │
       ▼
Remediation Simulation
       │
       ▼
Actionable Recommendations
```

### 🏆 Impact

**From Hours → Seconds**

ClawOps AI enables engineering teams to respond faster, learn from previous incidents, and maintain system reliability at scale through autonomous AI-driven incident response.

---

## Highlight Features

### 🔴 Real-time Log Monitoring

ClawOps AI includes a live Streamlit dashboard that simulates a running production system. Healthy logs stream continuously, and chaos scenarios can be injected directly from the UI.

- Live log stream from `data/current_incident/live_logs.json`
- Automatic incident trigger when `ERROR`, `CRITICAL`, `FATAL`, or `WARNING` appears
- Hybrid evidence enrichment from alerts, metrics, Kubernetes events, and historical data

### 🧠 Multi-Agent Orchestration

The incident response workflow is powered by LangGraph and multiple cooperating agents:

- **LogAgent**: analyzes application logs and Kubernetes signals
- **MetricsAgent**: checks CPU, memory, error rate, and latency
- **ResearchAgent**: investigates the open web for similar issues and fixes
- **SupervisorAgent**: synthesizes all evidence into final RCA
- **GenReports**: generates incident report, post-mortem, and remediation output

### 🌐 Gemini-style Web Search Research

The ResearchAgent acts like a web investigator. It uses Qwen to extract the core framework, exception, and symptom from the log line, then creates an open-web search query.

Example generated query:

```text
HikariPool connection timeout root cause analysis solution fix
```

The agent searches across official docs, engineering blogs, forums, GitHub issues, Dev.to, Medium, and public technical discussions to enrich the SupervisorAgent context.

### 🤖 Auto-Remediation via Tool Calling

ClawOps AI includes simulated SRE tools that demonstrate how remediation can be automated after RCA:

- DB pool issue -> scale database connection pool
- OOM / pod failure -> restart Kubernetes pod

Example remediation execution log:

```bash
Successfully executed: ALTER SYSTEM SET max_connections = 100; for backend-service
```

> Note: remediation commands are simulated for demo safety and do not modify real infrastructure.

### 🧬 Vector-based Memory with ChromaDB

Historical incidents are stored in ChromaDB and retrieved semantically using local embeddings.

- Persistent vector database in `data/vectordb/`
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`
- Top-2 similar incidents are injected into the RCA context
- Helps the agent recognize recurring production failure patterns

---

## Quick Start

### Requirements

- Python 3.10+
- GreenNode MaaS API key
- Qwen-3-27B compatible model endpoint
- Recommended OS: Windows, macOS, or Linux

Create a `.env` file in the project root:

```env
GREENNODE_API_KEY=your_api_key_here
GREENNODE_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
GREENNODE_MODEL=qwen/qwen3-5-27b
```

For offline testing without LLM or web search:

```env
CLAWOPS_DISABLE_LLM=1
CLAWOPS_DISABLE_RESEARCH=1
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Backend

```bash
uvicorn src.main:app --reload
```

Backend will be available at:

```text
http://localhost:8000
```

Health check:

```text
http://localhost:8000/health
```

### Run Frontend

```bash
streamlit run app.py
```

Streamlit dashboard will be available at:

```text
http://localhost:8501
```

---

## Project Structure

```text
UIT_SoloLeveling-ClawAThon/
│
├── app.py                         # Streamlit live SRE dashboard
├── main.py                        # CLI entry point for local graph execution
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Container build file
├── README.md                      # Project documentation
│
├── src/
│   ├── __init__.py
│   ├── graph.py                   # LangGraph multi-agent workflow
│   ├── main.py                    # FastAPI backend and API endpoints
│   ├── memory.py                  # ChromaDB vector RAG memory
│   ├── generator.py               # Live log simulator and chaos injection
│   └── schema.py                  # Pydantic request/response schemas
│
├── data/
│   ├── current_incident/
│   │   ├── alert.json             # Current alert snapshot
│   │   ├── logs.json              # Current application log snapshot
│   │   ├── metrics.json           # Current metrics snapshot
│   │   ├── k8s_events.json        # Kubernetes event snapshot
│   │   ├── live_logs.json         # Real-time simulated log stream
│   │   ├── incident_report.json   # Generated structured incident report
│   │   └── POST_MORTEM.md         # Generated post-mortem
│   │
│   ├── historical_incidents/
│   │   └── memory.md              # Human-readable historical incidents
│   │
│   └── vectordb/                  # ChromaDB persistent vector memory
│
└── greennode-agentbase-skills/     # Optional AgentBase skill resources
```

---

## Demo & Results

### Judge Demo Flow

1. Start the backend:

   ```bash
   uvicorn src.main:app --reload
   ```

2. Start the frontend:

   ```bash
   streamlit run app.py
   ```

3. Open the dashboard:

   ```text
   http://localhost:8501
   ```

4. Watch the **Live Log Stream** showing healthy logs:

   ```text
   INFO | web-api | System Healthy
   INFO | web-api | Latency: 42ms
   ```

5. Click one of the chaos buttons:

   - `Inject DB Timeout`
   - `Inject K8s OOM`

6. Observe ClawOps AI automatically:

   - Detects the incident from the live log stream
   - Enriches evidence with alert, metrics, and Kubernetes snapshots
   - Retrieves similar historical incidents from ChromaDB
   - Runs Gemini-style open web research
   - Synthesizes RCA through the SupervisorAgent
   - Generates an incident report and post-mortem
   - Simulates SRE auto-remediation

### Example Output

```text
Root Cause:
Database connection pool exhaustion in backend-service.

Evidence:
HikariPool-1 - Connection is not available, request timed out after 30000ms.

Auto-Remediation:
Successfully executed: ALTER SYSTEM SET max_connections = 100; for backend-service
```

### Why It Matters

ClawOps AI demonstrates a complete incident response loop:

```text
Detect -> Investigate -> Retrieve Memory -> Research Web -> Diagnose -> Remediate -> Report
```

This reduces MTTR from hours of manual investigation to seconds of autonomous reasoning.

---

## Technology Stack

| Layer | Technology |
| --- | --- |
| Agent Orchestration | LangGraph |
| LLM Framework | LangChain |
| LLM | Qwen-3-27B via GreenNode MaaS |
| Backend API | FastAPI |
| Frontend Dashboard | Streamlit |
| Vector Memory | ChromaDB |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Web Research | DuckDuckGoSearchRun / DDGS |
| Data Validation | Pydantic |
| Runtime Language | Python |

---

## API Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | Backend health check |
| `/api/v1/analyze` | POST | Run full LangGraph RCA workflow |
| `/api/v1/chat` | POST | Ask follow-up questions about the incident |
| `/api/v1/live-logs` | GET | Read or append simulated live logs |
| `/api/v1/live-logs/reset` | POST | Reset live log stream to healthy state |
| `/api/v1/chaos` | POST | Inject DB timeout or Kubernetes OOM fault |

---

## Hackathon Value

ClawOps AI is not just a chatbot. It is an autonomous operational workflow that combines:

- Real-time incident detection
- Multi-agent RCA
- Vector memory retrieval
- Open web research
- Simulated SRE tool execution
- Human-readable reporting

The result is a production-inspired SRE copilot that helps engineering teams respond faster, learn from past incidents, and reduce operational stress during critical outages.

---

## License

This project is built for AI hackathon demonstration and educational use.
