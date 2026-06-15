# Quy trình thực nghiệm Chương 5

## Mục tiêu

Quy trình mới tạo dữ liệu time-series có timestamp thay cho ảnh snapshot:

- k6 phát tải theo `request/s` bằng `constant-arrival-rate`.
- Mỗi mức tải có tag `load_level` và `phase`.
- Kubernetes CPU, Ready, restart và HPA replicas được lấy mỗi 5 giây.
- Tool dựng knee curve, timeline đồng bộ và bảng CSV theo từng mức tải.

Cloud Monitoring được dùng để đối chiếu. Không dùng ảnh Cloud Monitoring làm
nguồn duy nhất để xác định knee vì nhiều GKE system metrics được lấy mẫu theo
chu kỳ 60 giây và có độ trễ hiển thị.

## Chuẩn bị trước mỗi lần chạy

1. Dùng cùng image, cluster, payload và giới hạn tài nguyên cho mọi cấu hình.
2. Đảm bảo Metrics Server hoạt động bằng `kubectl top pods`.
3. Chờ tất cả Pod Ready, CPU trở về mức nền và restart không còn tăng.
4. Ghi lại thời gian UTC bắt đầu/kết thúc.
5. Không rollout, build image hoặc chạy workload khác trong lúc thử nghiệm.

Chạy một lần chẩn đoán ngắn trước bộ số liệu chính. Nếu `events-after.txt` cho
thấy liveness probe thất bại và kubelet restart container, cần quyết định rõ:
giữ probe như một phần của hệ thống được đánh giá, hoặc hiệu chỉnh probe rồi
chạy lại toàn bộ ba cấu hình. Không trộn kết quả trước và sau khi đổi probe.

Mỗi cấu hình phải chạy ít nhất ba lần. Nên đổi thứ tự cấu hình giữa các vòng:

```text
Vòng 1: fixed -> hpa-240 -> hpa-200
Vòng 2: hpa-200 -> fixed -> hpa-240
Vòng 3: hpa-240 -> hpa-200 -> fixed
```

## Cấu hình ba kịch bản

### Fixed 2 Pod

```bash
kubectl delete hpa invoice-pdf-api-hpa --ignore-not-found
kubectl scale deployment invoice-pdf-api --replicas=2
kubectl rollout status deployment/invoice-pdf-api
```

### HPA target 300% mới

```bash
kubectl apply -f k8s/hpa-300.yaml
kubectl get hpa invoice-pdf-api-hpa
```

### HPA target 250% mới

```bash
kubectl apply -f k8s/hpa-250.yaml
kubectl get hpa invoice-pdf-api-hpa
```

Hai manifest `hpa-240.yaml` và `hpa-200.yaml` được giữ để truy vết phép thử cũ,
không phải target chính của vòng kiểm chứng mới.

## Capacity test để xác định knee

Manifest `deployment.yaml` dùng startup probe và tăng tolerance thời gian cho
liveness probe để tránh restart container chỉ vì event loop chậm tạm thời khi
render PDF. Vì probe là một phần của cấu hình thực nghiệm, sau khi thay đổi
probe phải chạy lại ba fixed-capacity run và tính lại knee trước khi tiếp tục
với HPA.

Pilot rộng ngày 15/06/2026 cho thấy 10 RPS còn đạt tiêu chí, trong khi 20 RPS
đã có HTTP p95 1.58 giây và error rate 6.84%. Vì vậy lần chạy mặc định tiếp
theo đo chi tiết:

```text
10, 12, 14, 16, 18, 20 request/s
```

Mỗi mức giữ 3 phút. Chạy ba lần với `SCENARIO` khác nhau:

```bash
BASE_URL=http://EXTERNAL_IP \
SCENARIO=fixed-knee-run1 \
LOAD_PROFILE=capacity \
./scripts/run-experiment.sh
```

Lặp lại với `fixed-knee-run2` và `fixed-knee-run3`. Trước mỗi lần chạy phải đưa
Deployment về 2 Pod, chờ cả hai Pod Ready và CPU trở về mức nền.

Có thể ghi đè dải tải khi cần:

```bash
BASE_URL=http://EXTERNAL_IP \
SCENARIO=fixed \
LOAD_PROFILE=capacity \
CAPACITY_RATES=10,12,14,16,18,20 \
CAPACITY_LEVEL_DURATION=3m \
./scripts/run-experiment.sh
```

Latency trong lần đo mới được tổng hợp từ metric
`successful_http_req_duration`, tức chỉ các response vượt qua đủ ba check.
Timeout, connection error và response không hợp lệ vẫn được phản ánh trong
error rate. Cách tách này tránh duration bằng 0 của lỗi kết nối làm giảm p50
hoặc percentile latency.

Knee không được xác định chỉ bằng CPU; cần đọc đồng thời:

- HTTP p95/p99 bắt đầu tăng nhanh.
- Error rate vượt 1%.
- Achieved RPS không tăng theo offered RPS.
- Dropped iterations xuất hiện.
- CPU gần limit, Pod mất Ready hoặc restart.

Ba lần đo fixed đã xác định mức cuối đạt tiêu chí là 16 RPS và mức đầu không
đạt là 18 RPS. Median CPU tại 16 RPS khoảng 394.7m/Pod, tương ứng 394.7% CPU
request. Hai target ứng viên là:

```text
300%: phương án gần knee, ưu tiên sử dụng tài nguyên
250%: phương án có dự phòng, scale sớm hơn
```

## Kiểm chứng hai target HPA mới

Mỗi target chạy ba lần với đúng profile capacity 10--20 RPS. Với target 300%:

```bash
kubectl apply -f k8s/hpa-300.yaml
kubectl get hpa invoice-pdf-api-hpa
kubectl wait --for=condition=Ready pod \
  -l app=invoice-pdf-api \
  --timeout=180s

BASE_URL=http://EXTERNAL_IP \
SCENARIO=hpa-300-run1 \
LOAD_PROFILE=capacity \
./scripts/run-experiment.sh
```

Lặp lại với `hpa-300-run2` và `hpa-300-run3`. Chờ HPA trở về 2 replica, tất cả
Pod Ready và CPU ổn định trước mỗi lần.

Với target 250%:

```bash
kubectl apply -f k8s/hpa-250.yaml

BASE_URL=http://EXTERNAL_IP \
SCENARIO=hpa-250-run1 \
LOAD_PROFILE=capacity \
./scripts/run-experiment.sh
```

Lặp lại với `hpa-250-run2` và `hpa-250-run3`. Không thay đổi image, probe,
resource request/limit hoặc cluster giữa sáu lần chạy.

Sau sáu run, so sánh:

- HTTP p95 và error rate tại 16, 18 và 20 RPS.
- Thời gian từ khi CPU vượt target đến desired replicas tăng.
- Thời gian Pod mới đạt Ready.
- Số restart và thời gian không đủ Pod Ready.
- Achieved RPS và pod-seconds.

## HPA reaction test

Profile mặc định:

```text
5 -> 10 -> 15 -> 20 -> 25 -> 15 -> 5 request/s
```

Mỗi mức giữ 3 phút:

```bash
BASE_URL=http://EXTERNAL_IP \
SCENARIO=hpa-240 \
LOAD_PROFILE=hpa \
./scripts/run-experiment.sh
```

Profile tăng--giảm chỉ chạy sau khi hoàn tất kiểm chứng 300% và 250%. Các mức
RPS sẽ được chốt theo target thắng vòng capacity. Timeline cho phép đo khoảng
cách giữa:

```text
tải tăng -> CPU tăng -> desired replicas tăng -> Pod Ready -> latency phục hồi
```

## File kết quả

Mỗi run nằm trong:

```text
results/SCENARIO/TIMESTAMP/
```

Các file chính:

- `k6-points.json`: metric k6 theo thời gian.
- `k6-summary.json`: summary và metadata profile.
- `k8s-metrics.csv`: CPU, Ready, restart, desired/current replicas.
- `collector-console.txt`: lỗi truy cập Metrics API hoặc Kubernetes API.
- `events-before.txt`, `events-after.txt`: bằng chứng Kubernetes events.
- `pods-after.json`: trạng thái kết thúc và restart của container.
- `charts/level-summary.csv`: thống kê theo offered RPS.
- `charts/knee.svg`: knee curve.
- `charts/timeline.svg`: timeline đồng bộ.

Nếu có `rsvg-convert`, tool tạo thêm PNG.

## So sánh các lần lặp

Ví dụ so sánh ba cấu hình tại 20 request/s:

```bash
python3 scripts/compare-experiments.py \
  --level 20 \
  --run fixed=results/fixed/RUN1/charts/level-summary.csv \
  --run fixed=results/fixed/RUN2/charts/level-summary.csv \
  --run fixed=results/fixed/RUN3/charts/level-summary.csv \
  --run hpa-240=results/hpa-240/RUN1/charts/level-summary.csv \
  --run hpa-240=results/hpa-240/RUN2/charts/level-summary.csv \
  --run hpa-240=results/hpa-240/RUN3/charts/level-summary.csv \
  --run hpa-200=results/hpa-200/RUN1/charts/level-summary.csv \
  --run hpa-200=results/hpa-200/RUN2/charts/level-summary.csv \
  --run hpa-200=results/hpa-200/RUN3/charts/level-summary.csv \
  --output results/comparison-20rps.svg
```

## Biểu đồ trên GCP Monitoring

Vào **Kubernetes Engine > Workloads > invoice-pdf-api > Observability**. Chọn
đúng khoảng thời gian UTC của run và bật Kubernetes events.

Nên lưu các biểu đồ sau:

1. **CPU request utilization**:
   `kubernetes.io/container/cpu/request_utilization`, tách theo Pod.
2. **CPU limit utilization**:
   `kubernetes.io/container/cpu/limit_utilization`, tách theo Pod.
3. **Memory limit utilization**:
   `kubernetes.io/container/memory/limit_utilization`, để loại trừ memory
   bottleneck.
4. **HPA recommendation latency**:
   `kubernetes.io/autoscaler/latencies/per_hpa_recommendation_scale_latency_seconds`,
   nếu metric có dữ liệu.
5. **Kubernetes events**, đặc biệt FailedScheduling, Unhealthy, Killing và
   BackOff.

Khi tạo custom dashboard:

- Filter cluster, namespace `default`, workload `invoice-pdf-api` và container
  `invoice-pdf-api`.
- Không gộp tất cả Pod thành một đường duy nhất; giữ series theo `pod_name`.
- Dùng cùng timezone UTC và cùng khoảng bắt đầu/kết thúc với metadata của run.
- Không đọc một điểm 60 giây như thời điểm scale chính xác; dùng CSV 5 giây để
  đo thời gian, dùng GCP chart để xác nhận xu hướng.

Tài liệu Google Cloud:

- https://cloud.google.com/kubernetes-engine/docs/how-to/view-observability-metrics
- https://cloud.google.com/monitoring/api/metrics_kubernetes
- https://cloud.google.com/monitoring/charts
