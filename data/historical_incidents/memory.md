# LỊCH SỬ SỰ CỐ PRODUCTION

## Sự cố INC-2026-05A
- **Loại lỗi:** CRASH_LOOP_BACKOFF
- **Triệu chứng:** Pod liên tục khởi động lại do lỗi cấu hình ENV.
- **Khắc phục:** Kiểm tra lại tệp cấu hình biến môi trường hệ thống.

## Sự cố INC-2026-05B
- **Loại lỗi:** DB_POOL_EXHAUSTED
- **Triệu chứng:** HikariPool trả về Timeout 30000ms.
- **Khắc phục:** Đã tăng kích thước pool tối đa lên 50 kết nối.

## Sự cố INC-20260610-100902
- **Tiêu đề:** Post-Mortem: Database Connection Timeout
- **Phân tích Root Cause:** 

Sự cố bắt nguồn từ việc cạn kiệt pool kết nối cơ sở dữ liệu (DB Connection Pool Exhaustion), khiến backend không thể lấy được connection rảnh và trả về lỗi HTTP 500 hàng loạt. Log lỗi xác nhận rõ việc "Timeout waiting for idle object in pool" sau 30000ms, hoàn toàn khớp với chỉ số latency cao điểm trên metrics, trong khi tài nguyên CPU và Memory backend vẫn ở mức an toàn. Tham chiếu lịch sử sự cố INC-2026-05B với triệu chứng tương tự đã từng được xử lý bằng việc tăng kích thước pool, khẳng định đây là vấn đề về giới hạn cấu hình kết nối chứ không phải lỗi hạ tầng Database.
- **Ngày xử lý:** Ghi nhận tự động bởi ClawOps Agent.


## Incident INC-20260615-161222
- Title: Post-Mortem: Database Connection Timeout
- Root Cause Analysis: {'primary_cause': 'Database Connection Pool Exhaustion (HikariCP)', 'confidence_score': 0.95, 'summary': 'The backend-service is experiencing HTTP 500 errors due to the inability to acquire available database connections within the configured timeout threshold of 30000ms. This is caused by the HikariCP connection pool reaching its maximum capacity faster than connections are being released.', 'contributing_factors': ["Insufficient 'maximum-pool-size' configuration relative to current traffic volume", 'Potential long-running transactions or queries holding connections open', 'Possible connection leaks in application code'], 'evidence_sources': {'logs': "Errors 'Timeout waiting for idle object in pool' and 'Connection is not available' confirm pool saturation.", 'metrics': 'CPU (15%) and Memory (40%) usage are low, ruling out host resource exhaustion. Latency matches 30s timeout exactly.', 'historical_incidents': ['INC-20260610-100902 (similarity=0.495): Confirmed same symptom and resolution (pool increase).', 'INC-2026-05B (similarity=0.360): Previously resolved by increasing max pool size to 50.']}, 'infrastructure_health': 'Database instance health and backend host resources are stable; the bottleneck is strictly at the connection pool layer.'}
- Recorded At: 2026-06-15T16:12:22Z
