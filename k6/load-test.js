import http from "k6/http";
import { sleep, check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";

export const options = {
  stages: [
    { duration: "30s", target: 5 },
    { duration: "45s", target: 5 },

    { duration: "30s", target: 10 },
    { duration: "45s", target: 10 },

    { duration: "30s", target: 15 },
    { duration: "45s", target: 15 },

    { duration: "30s", target: 20 },
    { duration: "45s", target: 20 },

    { duration: "30s", target: 0 },
  ],

  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
  },
};

export default function () {
  const start = Date.now();

  const res = http.get(`${BASE_URL}/cpu`, {
    timeout: "1s",
  });

  const latency = Date.now() - start;

  const ok = check(res, {
    "status is 200": (r) => r.status === 200,
  });

  let body = {};
  try {
    body = res.json();
  } catch (e) {
    body = {};
  }

  if (!ok || latency > 500) {
    console.log(
      JSON.stringify({
        timestamp: new Date().toISOString(),
        latencyMs: latency,
        status: res.status,
        processingTimeMs: body.processingTimeMs || null,
        pod: body.pod || null,
      })
    );
  }

  sleep(1);
}