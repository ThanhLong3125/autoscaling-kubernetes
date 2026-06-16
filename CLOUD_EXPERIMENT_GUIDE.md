# Chạy thực nghiệm HPA tự động trên GKE

## Luồng mới

Máy cá nhân không trực tiếp phát tải. Máy chỉ dùng `kubectl` để tạo một
Kubernetes Job chạy k6 trong GKE:

```text
run-cloud-suite.sh
  -> reset fixed 2 Pod
  -> chờ 2/2 Ready
  -> tạo k6 Job chạy 12 -> 14 -> 16 -> 14 -> 12 RPS
  -> thu kết quả và vẽ biểu đồ
  -> reset về 2 Pod
  -> apply HPA 300%
  -> chạy lại cùng profile
```

Job dùng Service DNS nội bộ:

```text
http://invoice-pdf-api-service.default.svc.cluster.local
```

Vì vậy kết quả tập trung vào ứng dụng và HPA, không bao gồm độ trễ của external
LoadBalancer.

## Chuẩn bị một lần

Triển khai ứng dụng:

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl rollout status deployment/invoice-pdf-api --timeout=180s
```

Kiểm tra Metrics API:

```bash
kubectl top pods -l app=invoice-pdf-api
```

Máy điều phối cần `kubectl` và `python3`, nhưng không cần cài k6.

## Chạy thử ngắn

Lần đầu chỉ chạy một vòng, mỗi mức tải một phút:

```bash
RUNS=1 \
HPA_LEVEL_DURATION=1m \
STABILIZATION_SECONDS=20 \
./scripts/run-cloud-suite.sh
```

Suite chạy hai bài:

1. Deployment cố định 2 Pod.
2. HPA target 300%, từ 2 đến 5 Pod.

Nếu lần thử ngắn hoàn tất và có biểu đồ, chạy bộ chính:

```bash
./scripts/run-cloud-suite.sh
```

Mặc định bộ chính chạy ba vòng. Thứ tự được đảo giữa các vòng:

```text
Vòng 1: fixed -> HPA
Vòng 2: HPA -> fixed
Vòng 3: fixed -> HPA
```

Việc đảo thứ tự hạn chế ảnh hưởng của thời điểm chạy lên một cấu hình duy nhất.

## Vòng lặp nhanh nhưng vẫn đủ chất lượng

Không nên rút tất cả phase xuống 1 phút. HPA cần thời gian lấy metrics, tính
replica và chờ Pod mới Ready. Cách tiết kiệm thời gian tốt hơn là dùng duration
không đều: giai đoạn đầu ngắn, giai đoạn quá tải đủ dài, giai đoạn phục hồi vừa
đủ.

Quan trọng: dữ liệu cũ cho thấy miền cần quan sát nằm quanh 12--16 RPS. Mức
18 RPS chỉ dùng như bằng chứng fixed 2 Pod đã quá tải, không dùng làm tải chính
để chọn target HPA. Nếu chuyển sang runner mới, dữ liệu cũ chỉ nên được xem là
pilot; dữ liệu kết luận nên chạy lại bằng cùng một profile mới.

Dùng quy trình hai tầng:

1. Calibration nhanh với fixed 2 Pod quanh 12--16 RPS.
2. Chạy HPA-only cho từng target ứng viên.
3. Chỉ target thắng mới chạy bộ xác nhận dài hơn.

Calibration fixed 2 Pod, khoảng sáu phút tải:

```bash
kubectl delete hpa invoice-pdf-api-hpa --ignore-not-found
kubectl scale deployment invoice-pdf-api --replicas=2

SCENARIO=fast-fixed-calibration \
LOAD_PROFILE=capacity \
CAPACITY_RATES=12,14,16,14,12 \
CAPACITY_LEVEL_DURATIONS=45s,90s,2m,90s,45s \
./scripts/run-cloud-experiment.sh
```

Test nhanh riêng HPA 300%, khoảng bảy phút tải. Trong đó 14 và 16 RPS được giữ
đủ lâu để HPA có thời gian scale-up và latency kịp ổn định:

```bash
RUNS=1 \
MODES=hpa \
HPA_MANIFEST=./k8s/hpa-300.yaml \
HPA_RATES=12,14,16,14,12 \
HPA_LEVEL_DURATIONS=45s,2m,3m,90s,45s \
STABILIZATION_SECONDS=20 \
./scripts/run-cloud-suite.sh
```

Test nhanh HPA 250%:

```bash
RUNS=1 \
MODES=hpa \
HPA_MANIFEST=./k8s/hpa-250.yaml \
HPA_RATES=12,14,16,14,12 \
HPA_LEVEL_DURATIONS=45s,2m,3m,90s,45s \
STABILIZATION_SECONDS=20 \
./scripts/run-cloud-suite.sh
```

Sau vòng nhanh, chỉ chạy xác nhận với target đã chọn:

```bash
RUNS=2 \
MODES=fixed,hpa \
HPA_MANIFEST=./k8s/hpa-300.yaml \
HPA_RATES=12,14,16,14,12 \
HPA_LEVEL_DURATIONS=1m,3m,4m,2m,1m \
./scripts/run-cloud-suite.sh
```

Khi viết báo cáo, phân biệt rõ: vòng nhanh dùng để chọn cấu hình, còn vòng xác
nhận dùng làm dữ liệu kết luận.

## Chạy fixed 2 Pod ba lần

Để làm lại `test_2` trước, chạy riêng fixed 2 Pod ba lần. Trước mỗi run, script
tự xóa HPA, scale Deployment về 2 replica, chờ `2/2 Ready`, đợi ổn định rồi mới
phát tải:

```bash
RUNS=3 \
MODES=fixed \
SUITE_ID=test-2-fixed-knee \
STABILIZATION_SECONDS=60 \
./scripts/run-cloud-suite.sh
```

Profile mặc định của suite là:

```text
12 RPS trong 1 phút
14 RPS trong 3 phút
16 RPS trong 4 phút
14 RPS trong 2 phút
12 RPS trong 1 phút
```

Mỗi run có 11 phút tải, chưa tính thời gian chờ ổn định và thu kết quả.

## Thay profile tải

Profile mặc định:

```text
12 RPS trong 3 phút
14 RPS trong 3 phút
16 RPS trong 3 phút
14 RPS trong 3 phút
12 RPS trong 3 phút
```

Nếu muốn có một bài stress/failure riêng để chứng minh fixed 2 Pod sụp ở ngoài
vùng thiết kế, mới dùng 18 RPS:

```bash
HPA_RATES=14,16,18,16,14 \
HPA_LEVEL_DURATION=3m \
./scripts/run-cloud-suite.sh
```

Hai mức `18` liên tiếp tương đương giữ tải cao sáu phút.

## Kết quả

Mỗi lần chạy tạo thư mục:

```text
results/SUITE-fixed-run1/TIMESTAMP/
results/SUITE-hpa-run1/TIMESTAMP/
```

File quan trọng:

- `k6-console.txt`: log của k6 Job.
- `k6-points.json`: dữ liệu tải theo thời gian.
- `k8s-metrics.csv`: CPU, Ready và replica mỗi 5 giây.
- `events-after.txt`: sự kiện probe, scheduling và restart.
- `charts/timeline.svg`: tải, latency, CPU và replica trên cùng timeline.
- `charts/level-summary.csv`: thống kê theo mức RPS.
- `charts/phase-summary.csv`: tách riêng từng giai đoạn, gồm 12 RPS trước và
  sau vùng biên.

Đọc `timeline.svg` để trả lời:

1. Fixed 2 Pod phản ứng thế nào khi tải đi từ 12 lên 14 và 16 RPS?
2. HPA yêu cầu replica mới sau bao nhiêu giây?
3. Pod mới mất bao lâu để Ready?
4. Latency và error rate có phục hồi sau scale-up không?
5. HPA có giảm replica khi tải trở lại 14 và 12 RPS không?

## Chạy riêng một bài

Nếu chỉ cần chạy một Job mà không chạy cả suite:

```bash
SCENARIO=diagnostic \
HPA_RATES=12,14,16,14,12 \
HPA_LEVEL_DURATIONS=45s,2m,3m,90s,45s \
./scripts/run-cloud-experiment.sh
```

Script giữ Job đến khi đã tải `k6-points.json` và `k6-summary.json` về máy.

## Lưu ý về tài nguyên

Manifest dùng pod anti-affinity dạng ưu tiên để cố gắng đặt k6 khác node với
ứng dụng. Với bộ số liệu chính, nên tạo node pool riêng cho load generator hoặc
kiểm tra `cluster-before.txt` để xác nhận k6 không tranh CPU đáng kể với Pod ứng
dụng.
