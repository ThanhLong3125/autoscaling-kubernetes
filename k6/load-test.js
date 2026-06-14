import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8080").replace(/\/$/, "");
const HTTP_AVG_THRESHOLD_MS = Number(__ENV.HTTP_AVG_THRESHOLD_MS || 250);
const HTTP_P95_THRESHOLD_MS = Number(__ENV.HTTP_P95_THRESHOLD_MS || 450);
const RENDER_P95_THRESHOLD_MS = Number(__ENV.RENDER_P95_THRESHOLD_MS || 400);
const processingTime = new Trend("invoice_processing_time", true);

export const options = {
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  stages: [
    { duration: "30s", target: 5 },
    { duration: "1m", target: 5 },
    { duration: "30s", target: 15 },
    { duration: "2m", target: 15 },
    { duration: "30s", target: 30 },
    { duration: "2m", target: 30 },
    { duration: "30s", target: 60 },
    { duration: "3m", target: 60 },
    { duration: "30s", target: 30 },
    { duration: "1m", target: 30 },
    { duration: "30s", target: 15 },
    { duration: "1m", target: 15 },
    { duration: "30s", target: 5 },
    { duration: "1m", target: 5 },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_duration: [
      `avg<${HTTP_AVG_THRESHOLD_MS}`,
      `p(95)<${HTTP_P95_THRESHOLD_MS}`,
    ],
    http_req_failed: ["rate<0.01"],
    checks: ["rate>0.99"],
    invoice_processing_time: [`p(95)<${RENDER_P95_THRESHOLD_MS}`],
  },
};

const items = Array.from({ length: 120 }, (_, index) => ({
  description: `Cloud service item ${String(index + 1).padStart(3, "0")}`,
  quantity: (index % 5) + 1,
  unitPrice: 10 + (index % 17) * 1.75,
}));

export default function () {
  const payload = JSON.stringify({
    invoiceNumber: `INV-${__VU}-${__ITER}`,
    customerName: `Load test customer ${__VU}`,
    currency: "USD",
    issuedAt: new Date().toISOString(),
    items,
  });

  const response = http.post(`${BASE_URL}/api/invoices/render`, payload, {
    headers: {
      "Content-Type": "application/json",
      Accept: "application/pdf",
    },
    timeout: "3s",
    responseType: "none",
  });

  const processingHeader = response.headers["X-Processing-Time-Ms"];
  if (processingHeader) {
    processingTime.add(Number(processingHeader));
  }

  check(response, {
    "status is 200": (result) => result.status === 200,
    "response is PDF": (result) =>
      result.headers["Content-Type"]?.includes("application/pdf"),
    "request was handled by a pod": (result) =>
      Boolean(result.headers["X-Pod-Name"]),
  });

  sleep(1);
}
