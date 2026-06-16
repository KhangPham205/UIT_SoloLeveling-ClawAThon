import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional


CURRENT_INCIDENT_DIR = "data/current_incident"
LIVE_LOG_FILE = os.path.join(CURRENT_INCIDENT_DIR, "live_logs.json")
MAX_LIVE_LOG_LINES = 200


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)


def _read_live_logs() -> List[Dict[str, Any]]:
    if not os.path.exists(LIVE_LOG_FILE):
        return []
    with open(LIVE_LOG_FILE, "r", encoding="utf-8") as f:
        try:
            value = json.load(f)
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []


def get_live_logs() -> List[Dict[str, Any]]:
    return _read_live_logs()


def has_fault_logs(logs: List[Dict[str, Any]]) -> bool:
    fault_levels = {"ERROR", "CRITICAL", "FATAL", "WARN", "WARNING"}
    return any(str(item.get("level", "")).upper() in fault_levels for item in logs)


def _write_live_logs(logs: List[Dict[str, Any]]) -> None:
    _write_json(LIVE_LOG_FILE, logs[-MAX_LIVE_LOG_LINES:])


def append_normal_logs_tick() -> List[Dict[str, Any]]:
    logs = _read_live_logs()
    now = _utc_now()
    logs.extend(
        [
            {
                "timestamp": now,
                "level": "INFO",
                "service": "web-api",
                "message": "System Healthy",
                "latency_ms": 42,
            },
            {
                "timestamp": now,
                "level": "INFO",
                "service": "web-api",
                "message": "Latency: 42ms",
                "latency_ms": 42,
            },
        ]
    )
    _write_live_logs(logs)
    return logs[-MAX_LIVE_LOG_LINES:]


def reset_live_logs() -> List[Dict[str, Any]]:
    _write_live_logs([])
    return append_normal_logs_tick()


def stream_normal_logs(output_dir: str = CURRENT_INCIDENT_DIR, stop_after: Optional[int] = None) -> None:
    """Append two healthy log lines every second to live_logs.json."""
    global LIVE_LOG_FILE
    LIVE_LOG_FILE = os.path.join(output_dir, "live_logs.json")

    ticks = 0
    while True:
        append_normal_logs_tick()
        ticks += 1
        if stop_after is not None and ticks >= stop_after:
            return
        time.sleep(1)


def generate_incident_scenario(scenario_type: str, output_dir: str = CURRENT_INCIDENT_DIR) -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    now = _utc_now()

    alert = {
        "alert_id": "ALRT-001",
        "timestamp": now,
        "severity": "CRITICAL",
        "service": "web-api",
        "summary": "Unknown Error",
        "description": "System anomaly detected.",
    }
    logs = [
        {
            "timestamp": now,
            "level": "INFO",
            "service": "web-api",
            "message": "Service operational",
            "trace_id": "req-123",
        }
    ]
    k8s_events = [
        {
            "timestamp": now,
            "namespace": "production",
            "pod_name": "web-api-pod-xyz",
            "reason": "Started",
            "message": "Pod started successfully",
            "type": "Normal",
        }
    ]
    metrics = {
        "timestamp": now,
        "service": "web-api",
        "cpu_usage_pct": 15.0,
        "memory_usage_pct": 40.0,
        "error_rate_pct": 0.0,
        "latency_ms": 45.0,
    }

    if scenario_type == "DB_POOL_EXHAUSTED":
        alert.update(
            {
                "service": "backend-service",
                "summary": "Database Connection Timeout",
                "description": "HTTP 500 errors spiking due to DB pool exhaustion",
            }
        )
        logs = [
            {
                "timestamp": now,
                "level": "ERROR",
                "service": "backend-service",
                "message": "vngcloud.postgresql.Driver - Connection stubborn: Timeout waiting for idle object in pool",
                "trace_id": "req-999",
            },
            {
                "timestamp": now,
                "level": "CRITICAL",
                "service": "backend-service",
                "message": "HikariPool-1 - Connection is not available, request timed out after 30000ms.",
                "trace_id": "req-999",
            },
        ]
        metrics.update(
            {
                "service": "backend-service",
                "error_rate_pct": 88.5,
                "latency_ms": 30000.0,
            }
        )

    elif scenario_type == "OOM_KILLED":
        alert.update(
            {
                "service": "data-worker",
                "summary": "Container Terminated Unexpectedly",
                "description": "Pod memory limits breached and workload was OOMKilled",
            }
        )
        k8s_events = [
            {
                "timestamp": now,
                "namespace": "production",
                "pod_name": "data-worker-99-vng",
                "reason": "OOMKilled",
                "message": "Container data-worker consumed memory above limit and was killed by the node",
                "type": "Warning",
            }
        ]
        metrics.update({"service": "data-worker", "memory_usage_pct": 101.2})
        logs = [
            {
                "timestamp": now,
                "level": "CRITICAL",
                "service": "data-worker",
                "message": "Kubernetes OOMKilled: container data-worker exceeded memory limit",
            },
            {
                "timestamp": now,
                "level": "ERROR",
                "service": "data-worker",
                "message": "java.lang.OutOfMemoryError: Java heap space",
            },
        ]

    elif scenario_type == "HIGH_CPU":
        alert.update(
            {
                "service": "auth-service",
                "summary": "High CPU Usage Alert",
                "description": "CPU usage exceeded threshold 90%",
            }
        )
        metrics.update({"service": "auth-service", "cpu_usage_pct": 98.5, "latency_ms": 2500.0})
        logs = [
            {
                "timestamp": now,
                "level": "WARN",
                "service": "auth-service",
                "message": "Thread pool exhausted. Blocking tasks detected in bcrypt hashing operations.",
            }
        ]

    files_to_write = {
        "alert.json": alert,
        "logs.json": logs,
        "k8s_events.json": k8s_events,
        "metrics.json": metrics,
    }
    for filename, data in files_to_write.items():
        _write_json(os.path.join(output_dir, filename), data)

    return {
        "alert": alert,
        "logs": logs,
        "k8s_events": k8s_events,
        "metrics": metrics,
    }


def inject_chaos_fault(scenario: str) -> Dict[str, Any]:
    """Overwrite live_logs.json with severe fault logs and update current incident files."""
    scenario = scenario.upper()
    if scenario in {"DB_TIMEOUT", "DB_POOL", "DB_POOL_TIMEOUT"}:
        scenario = "DB_POOL_EXHAUSTED"
    elif scenario in {"K8S_OOM", "OOM", "OOMKILLED"}:
        scenario = "OOM_KILLED"

    incident = generate_incident_scenario(scenario)
    live_logs: List[Dict[str, Any]] = []
    for log in incident["logs"]:
        live_logs.append(log)
    for event in incident["k8s_events"]:
        if str(event.get("type", "")).lower() == "warning":
            live_logs.append(
                {
                    "timestamp": event.get("timestamp"),
                    "level": "CRITICAL",
                    "service": incident["alert"].get("service", "unknown-service"),
                    "message": f"K8s {event.get('reason')}: {event.get('message')}",
                    "pod_name": event.get("pod_name"),
                }
            )

    _write_live_logs(live_logs)
    return {
        "scenario": scenario,
        "live_logs": live_logs,
        "incident": incident,
    }


if __name__ == "__main__":
    generate_incident_scenario("DB_POOL_EXHAUSTED")
    inject_chaos_fault("DB_POOL_EXHAUSTED")
