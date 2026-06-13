import http from "k6/http";
import { sleep, check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";
const VUS = Number(__ENV.VUS || 20);
const DURATION = __ENV.DURATION || "2m";

export const options = {
  vus: VUS,
  duration: DURATION,
};

export default function () {
  const res = http.get(`${BASE_URL}/cpu`, {
    timeout: "10s",
  });

  check(res, {
    "status is 200": (r) => r.status === 200,
  });

  sleep(1);
}