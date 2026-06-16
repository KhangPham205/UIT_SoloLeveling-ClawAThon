import json
import os
from datetime import datetime

def generate_incident_scenario(scenario_type: str, output_dir: str = "data/current_incident"):
    # Đảm bảo thư mục tồn tại
    os.makedirs(output_dir, exist_ok=True)
    now = datetime.utcnow().isoformat() + "Z"
    
    # 1. Khởi tạo Base Data (Trạng thái bình thường)
    alert = {"alert_id": "ALRT-001", "timestamp": now, "severity": "CRITICAL", "service": "web-api", "summary": "Unknown Error", "description": "System anomaly detected."}
    logs = [{"timestamp": now, "level": "INFO", "service": "web-api", "message": "Service operational", "trace_id": "req-123"}]
    k8s_events = [{"timestamp": now, "namespace": "production", "pod_name": "web-api-pod-xyz", "reason": "Started", "message": "Pod started successfully", "type": "Normal"}]
    metrics = {"timestamp": now, "service": "web-api", "cpu_usage_pct": 15.0, "memory_usage_pct": 40.0, "error_rate_pct": 0.0, "latency_ms": 45.0}

    # 2. Tiêm kịch bản lỗi (Inject Faults)
    if scenario_type == "DB_POOL_EXHAUSTED":
        alert.update({"service": "backend-service", "summary": "Database Connection Timeout", "description": "HTTP 500 errors spiking due to DB unavailability"})
        logs = [
            {"timestamp": now, "level": "ERROR", "service": "backend-service", "message": "vngcloud.postgresql.Driver - Connection stubborn: Timeout waiting for idle object in pool", "trace_id": "req-999"},
            {"timestamp": now, "level": "WARN", "service": "backend-service", "message": "HikariPool-1 - Connection is not available, request timed out after 30000ms.", "trace_id": "req-999"}
        ]
        metrics.update({"service": "backend-service", "error_rate_pct": 88.5, "latency_ms": 30000.0})

    elif scenario_type == "OOM_KILLED":
        alert.update({"service": "data-worker", "summary": "Container Terminated Unexpectedly", "description": "Pod memory limits breached"})
        k8s_events = [{"timestamp": now, "namespace": "production", "pod_name": "data-worker-99-vng", "reason": "OOMKilled", "message": "Container data-worker consumed close to limits and was killed by host", "type": "Warning"}]
        metrics.update({"service": "data-worker", "memory_usage_pct": 101.2})
        logs = [{"timestamp": now, "level": "FATAL", "service": "data-worker", "message": "java.lang.OutOfMemoryError: Java heap space"}]

    elif scenario_type == "HIGH_CPU":
        alert.update({"service": "auth-service", "summary": "High CPU Usage Alert", "description": "CPU usage exceeded threshold 90%"})
        metrics.update({"service": "auth-service", "cpu_usage_pct": 98.5, "latency_ms": 2500.0})
        logs = [{"timestamp": now, "level": "WARN", "service": "auth-service", "message": "Thread pool exhausted. Blocking tasks detected in bcrypt hashing operations."}]

    # Bạn có thể bổ sung các kịch bản khác vào đây sau...
    
    # 3. Ghi ra tệp JSON
    files_to_write = {
        "alert.json": alert,
        "logs.json": logs,
        "k8s_events.json": k8s_events,
        "metrics.json": metrics
    }
    
    for filename, data in files_to_write.items():
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
    print(f"✅ Đã tạo thành công kịch bản sự cố: {scenario_type} tại thư mục {output_dir}")

# Cho phép chạy file trực tiếp để test sinh dữ liệu
if __name__ == "__main__":
    print("Đang khởi tạo thảm họa giả lập...")
    generate_incident_scenario("DB_POOL_EXHAUSTED")