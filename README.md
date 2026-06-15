# Invoice PDF Autoscaling Demo

Ứng dụng nhận dữ liệu hóa đơn dạng JSON, tạo PDF trong RAM và trả file ngay
trong HTTP response. Hệ thống không dùng ảnh đầu vào, database, Persistent
Volume hoặc object storage.

## Các endpoint

### `GET /healthz`

Dùng cho kiểm tra thủ công, readiness probe và liveness probe.

```bash
curl http://localhost:8080/healthz
```

Response cho biết trạng thái dịch vụ và Pod đã xử lý request.

### `POST /api/invoices/render`

Nhận JSON hóa đơn, validate dữ liệu, tính thành tiền, phân trang và dựng PDF.
PDF chỉ tồn tại trong RAM trong lúc xử lý, sau đó được trả về client.

```bash
curl \
  -X POST http://localhost:8080/api/invoices/render \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/pdf' \
  --data-binary @examples/invoice.json \
  --output invoice-example.pdf
```

Các response header quan trọng:

- `Content-Type: application/pdf`: kết quả là PDF.
- `X-Pod-Name`: Pod xử lý request.
- `X-Processing-Time-Ms`: thời gian dựng PDF phía server.

Nếu JSON thiếu trường hoặc có giá trị không hợp lệ, API trả HTTP `400` cùng
thông báo lỗi JSON.

## Chạy local

```bash
cd app
yarn install
node index.js
```

Mở terminal khác tại thư mục `autoscaling-kubernetes` để gọi endpoint hoặc chạy
baseline.

## Đo baseline và chọn ngưỡng

```bash
node scripts/measure-response-time.js
```

Script thực hiện 5 request warm-up, sau đó đo 30 request có 120 dòng sản phẩm.
Kết quả gồm average, median, p90, p95, p99 cho tổng thời gian HTTP và thời gian
dựng PDF. Cuối kết quả có lệnh k6 với ngưỡng đề xuất bằng hai lần baseline.

Có thể thay đổi số mẫu:

```bash
WARMUP_REQUESTS=5 REQUESTS=50 node scripts/measure-response-time.js
```

Khi ứng dụng chạy trên GKE, đo lại qua external IP thay vì dùng số liệu local:

```bash
BASE_URL=http://EXTERNAL_IP REQUESTS=50 node scripts/measure-response-time.js
```

Nên chạy baseline ít nhất ba lần trong cùng điều kiện. Với mỗi chỉ số, lấy giá
trị lớn nhất giữa các lần chạy, nhân hệ số 2 và làm tròn lên theo bước 50 ms.
Ba lần đo hiện tại trên GKE cho ngưỡng HTTP average 250 ms, HTTP p95 450 ms và
PDF render p95 400 ms. Các ngưỡng này chỉ phục vụ thí nghiệm so sánh; nếu hệ
thống có SLA nghiệp vụ cụ thể thì SLA phải được ưu tiên.

## Cài đặt k6 trên Ubuntu/Debian

Cài k6 từ repository chính thức bằng `apt`:

```bash
sudo gpg -k

curl -fsSL https://dl.k6.io/key.gpg | \
  sudo gpg --dearmor -o /usr/share/keyrings/k6-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | \
  sudo tee /etc/apt/sources.list.d/k6.list

sudo apt update
sudo apt install k6 -y
```

Kiểm tra cài đặt:

```bash
k6 version
```

## Chạy thực nghiệm k6

Dùng runner để k6 và Kubernetes collector có chung timestamp:

```bash
BASE_URL=http://EXTERNAL_IP \
SCENARIO=fixed \
LOAD_PROFILE=capacity \
./scripts/run-experiment.sh
```

Profile `capacity` phát lần lượt 5, 8, 11, 14, 17, 20, 23 và 26 request/giây
để xác định knee. Profile `hpa` phát tải
5, 10, 15, 20, 25, 15 và 5 request/giây để quan sát scale-up và phục hồi.
Hai profile dùng arrival rate cố định, vì vậy offered load không tự giảm khi
response time tăng.

Runner lưu raw k6 JSON, Kubernetes CSV, events, trạng thái Pod và tự sinh knee
curve cùng timeline trong thư mục `results/`.

Quy trình đầy đủ, cách lặp ba cấu hình và thiết lập biểu đồ GCP Monitoring nằm
trong [`EXPERIMENT_GUIDE.md`](EXPERIMENT_GUIDE.md).

## Quy trình thử nghiệm trên GKE

1. Build và push image có tên khớp `k8s/deployment.yaml`.
2. Apply `deployment.yaml` và `service.yaml`.
3. Chờ external IP và kiểm tra `/healthz`.
4. Chạy baseline qua external IP để chọn ngưỡng.
5. Chạy capacity test cho cấu hình fixed, HPA 240% và HPA 200%.
6. Thu hẹp dải RPS quanh knee và chạy lại với bước 1--2 request/giây.
7. Chạy HPA reaction profile cho hai target.
8. Lặp mỗi cấu hình ít nhất ba lần và so sánh median cùng min--max.

Các manifest HPA:

```bash
kubectl apply -f k8s/hpa-240.yaml
kubectl apply -f k8s/hpa-200.yaml
```

Để quay về kịch bản fixed trước một lần chạy mới:

```bash
kubectl delete hpa invoice-pdf-api-hpa
kubectl scale deployment invoice-pdf-api --replicas=2
```
