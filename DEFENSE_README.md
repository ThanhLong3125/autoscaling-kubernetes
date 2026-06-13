# Câu hỏi phản biện đề tài

Tài liệu này dùng để chuẩn bị phần bảo vệ cho đề tài HPA dựa trên CPU đối với
dịch vụ tạo hóa đơn PDF trên GKE.

## Vì sao không dùng một máy ảo đơn lẻ?

Máy ảo đơn lẻ có thể chạy ứng dụng nhưng không thể hiện việc phân phối request
qua nhiều Pod và vòng điều khiển HPA. Kubernetes và khả năng tự động thay đổi
replica là đối tượng cần được đánh giá trong đề tài.

## Vì sao chọn GKE?

Thực nghiệm cần cluster cloud nhiều node, LoadBalancer và resource metrics.
GKE giảm phần vận hành control plane, đồng thời tích hợp với Artifact Registry
và load balancer. Đây là lựa chọn phù hợp cho thực nghiệm, không phải kết luận
GKE luôn tốt nhất hoặc rẻ nhất.

## Vì sao chọn CPU?

Render PDF là workload CPU-bound. Khi số request dựng PDF đồng thời tăng, CPU
usage cũng tăng. CPU metrics có sẵn qua Metrics Server và dễ tái tạo bằng cùng
payload cùng số virtual users.

## Vì sao không dùng memory?

Ứng dụng sử dụng buffer trong thời gian ngắn để tạo PDF nhưng không lưu dữ liệu
dài hạn. CPU phản ánh trực tiếp hơn thao tác tính toán, bố cục và render. Memory
vẫn cần được theo dõi nhưng không phải bottleneck mục tiêu.

## Vì sao không dùng request/second?

RPS là metric nghiệp vụ phù hợp, nhưng HPA theo RPS cần thêm hệ thống thu thập
metrics và adapter cung cấp custom hoặc external metrics. CPU đủ phù hợp để
kiểm chứng HPA resource metric trong phạm vi đề tài.

## Vì sao chọn HPA?

Ứng dụng stateless, các request có thể xử lý độc lập và phân phối qua nhiều Pod.
HPA điều chỉnh đúng số replica của Deployment dựa trên tải mà không cần xây
dựng controller riêng.

## HPA có giảm chi phí cloud không?

Có thể, nhưng phụ thuộc đơn vị billing:

- GKE Autopilot general-purpose tính theo resource request của Pod nên giảm Pod
  có tác động trực tiếp hơn tới chi phí workload.
- GKE Standard tính tiền các VM node đang tồn tại. HPA giảm Pod nhưng giữ
  nguyên node thì tiền VM chưa giảm; tài nguyên trống phải được workload khác
  sử dụng hoặc node phải được thu hồi.

## Vì sao không dùng KEDA hoặc Cluster Autoscaler?

KEDA phù hợp với queue, event hoặc external metrics. Cluster Autoscaler điều
chỉnh số node của cluster. Hai cơ chế giải quyết bài toán khác với việc điều
chỉnh replica của dịch vụ HTTP theo CPU.

## Khi nào HPA không hiệu quả?

HPA có thể không cải thiện hệ thống khi:

- Bottleneck nằm ở database, network hoặc I/O.
- Ứng dụng stateful và không thể phân phối request tự do.
- Pod khởi động hoặc warm-up quá lâu.
- Metric được chọn không phản ánh tải.
- Resource request cấu hình không hợp lý.
- Cluster không còn tài nguyên để scheduling Pod mới.

## Câu trả lời tóm tắt

Chuỗi lập luận chính:

```text
Render PDF tiêu thụ CPU
→ CPU phản ánh tải
→ ứng dụng stateless
→ có thể tăng số Pod
→ HPA tự động điều chỉnh replica
→ GKE cung cấp môi trường Kubernetes cloud để kiểm chứng
```
