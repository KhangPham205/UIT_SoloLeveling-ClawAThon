# ClawOps AI

ClawOps AI is an autonomous AI Agent built for the Data Analysis track. It leverages LangGraph to automatically analyze synthetic system data (alerts, Kubernetes events, metrics, and logs) to determine the Root Cause of system incidents and generate comprehensive Post-Mortem reports.

## Problem Statement
Troubleshooting complex distributed systems requires correlating data from multiple sources (metrics, logs, events, alerts). This manual process is time-consuming and error-prone.

## Target Users
- Site Reliability Engineers (SRE)
- DevOps Engineers
- System Administrators

## Workflow
1. **Data Ingestion**: Consume synthetic incident data (logs, metrics, alerts, k8s events).
2. **Analysis**: Use LLM-powered nodes via LangGraph to analyze different data streams.
3. **Correlation**: Correlate findings across different data sources.
4. **Root Cause Analysis**: Determine the most likely root cause of the incident.
5. **Post-Mortem Generation**: Generate a structured post-mortem report.

## Note
This agent uses **synthetic data** for analysis and simulation purposes.
