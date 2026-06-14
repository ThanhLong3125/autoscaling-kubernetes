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

## Chạy k6

Dùng lệnh do script baseline in ra, ví dụ:

```bash
HTTP_AVG_THRESHOLD_MS=250 \
HTTP_P95_THRESHOLD_MS=450 \
RENDER_P95_THRESHOLD_MS=400 \
BASE_URL=http://EXTERNAL_IP \
k6 run k6/load-test.js
```

k6 tạo hóa đơn 120 dòng ngay trong bộ nhớ và gửi tải theo các mức 5, 15, 30 và
60 virtual users. Do mỗi vòng lặp nghỉ 1 giây, 60 VU tương ứng xấp xỉ 57--60
request/giây khi response time còn thấp. Không cần đặt file ảnh hoặc file PDF
mẫu trong project.

## Quy trình thử nghiệm trên GKE

1. Build và push image có tên khớp `k8s/deployment.yaml`.
2. Apply `deployment.yaml` và `service.yaml`.
3. Chờ external IP và kiểm tra `/healthz`.
4. Chạy baseline qua external IP để chọn ngưỡng.
5. Đảm bảo HPA chưa tồn tại, giữ Deployment ở 2 replica và chạy k6 lần fixed.
6. Apply `hpa.yaml`, chờ metrics sẵn sàng rồi chạy lại cùng lệnh k6.
7. Trong khi test, ghi CPU, HPA và số Pod theo thời gian.

Các lệnh theo dõi:

```bash
kubectl get pods -w
kubectl get hpa -w
kubectl top pods
```

Để quay về kịch bản fixed trước một lần chạy mới:

```bash
kubectl delete hpa invoice-pdf-api-hpa
kubectl scale deployment invoice-pdf-api --replicas=2
```
