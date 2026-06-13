import http from "k6/http";
import { sleep, check } from "k6";

const BASE_URL =
  __ENV.BASE_URL || "http://localhost:8080";

export const options = {
  stages: [
    { duration: "1m", target: 20 },
    { duration: "2m", target: 50 },
    { duration: "2m", target: 100 },
    { duration: "2m", target: 150 },
    { duration: "1m", target: 0 }
  ],
};

export default function () {
  const res = http.get(`${BASE_URL}/cpu`);

  check(res, {
    "status is 200": (r) => r.status === 200,
  });

  sleep(1);
}