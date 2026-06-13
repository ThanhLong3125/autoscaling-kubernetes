import http from "k6/http";
import { sleep } from "k6";

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
  http.get("http://EXTERNAL_IP/cpu");
  sleep(1);
}