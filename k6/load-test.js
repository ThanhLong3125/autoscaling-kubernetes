import http from "k6/http";
import { sleep, check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";

export const options = {
  stages: [
    { duration: "30s", target: 2 },
    { duration: "45s", target: 2 },

    { duration: "30s", target: 6 },
    { duration: "45s", target: 6 },

    { duration: "30s", target: 10 },
    { duration: "2m", target: 10 },

    { duration: "30s", target: 6 },
    { duration: "45s", target: 6 },

    { duration: "30s", target: 2 },
    { duration: "1m", target: 2 },

    { duration: "30s", target: 0 },
  ],

  thresholds: {
    http_req_duration: ["p(95)<700"],
    http_req_failed: ["rate<0.01"],
  },
};

export default function () {
  const start = Date.now();

  const res = http.get(`${BASE_URL}/cpu`, {
    timeout: "2s",
  });

  const latency = Date.now() - start;

  const ok = check(res, {
    "status is 200": (r) => r.status === 200,
  });

  let body = {};
  try {
    body = res.json();
  } catch (e) {}

  if (!ok || latency > 700) {
    console.log(JSON.stringify({
      timestamp: new Date().toISOString(),
      latencyMs: latency,
      status: res.status,
      processingTimeMs: body.processingTimeMs || null,
      pod: body.pod || null,
    }));
  }

  sleep(1);
}