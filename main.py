"""
CLI entry point for running ClawOps AI against data/current_incident.

For the production API, run:
    uvicorn src.main:app --host 0.0.0.0 --port 8000
"""

from src.graph import run_clawops_analysis


def main() -> None:
    print("=====================================================")
    print("CLAWOPS AI - MULTI-AGENT INCIDENT RCA")
    print("=====================================================\n")

    final_state = run_clawops_analysis()

    report = final_state["incident_report"]
    print("\nAnalysis completed.")
    print(f"Incident ID: {report.incident_id}")
    print("Report written to data/current_incident/incident_report.json")
    print("Post-mortem written to data/current_incident/POST_MORTEM.md")


if __name__ == "__main__":
    main()
