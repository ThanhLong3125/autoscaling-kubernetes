import http from "k6/http";
import { check } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8080").replace(/\/$/, "");
const PROFILE = (__ENV.LOAD_PROFILE || "capacity").toLowerCase();
const HTTP_AVG_THRESHOLD_MS = numberEnv("HTTP_AVG_THRESHOLD_MS", 300);
const HTTP_P95_THRESHOLD_MS = numberEnv("HTTP_P95_THRESHOLD_MS", 550);
const RENDER_P95_THRESHOLD_MS = numberEnv("RENDER_P95_THRESHOLD_MS", 450);
const REQUEST_TIMEOUT = __ENV.REQUEST_TIMEOUT || "5s";
const ENFORCE_THRESHOLDS = (__ENV.ENFORCE_THRESHOLDS || "false") === "true";

const processingTime = new Trend("invoice_processing_time", true);
const successfulRequests = new Counter("successful_requests");
const failedRequests = new Counter("failed_requests");
const validResponses = new Rate("valid_responses");

const profiles = {
  capacity: {
    description: "Broad capacity pilot for locating the knee region",
    rates: integerListEnv(
      "CAPACITY_RATES",
      [10, 20, 40, 60, 80, 100, 120],
    ),
    duration: __ENV.CAPACITY_LEVEL_DURATION || "1m",
  },
  hpa: {
    description: "Stepped load for HPA reaction and recovery analysis",
    rates: integerListEnv("HPA_RATES", [5, 10, 15, 20, 25, 15, 5]),
    duration: __ENV.HPA_LEVEL_DURATION || "3m",
  },
};

if (!profiles[PROFILE]) {
  throw new Error(
    `LOAD_PROFILE must be one of: ${Object.keys(profiles).join(", ")}`,
  );
}

const selectedProfile = profiles[PROFILE];

export const options = {
  discardResponseBodies: true,
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  scenarios: buildScenarios(selectedProfile),
  thresholds: ENFORCE_THRESHOLDS
    ? {
        http_req_duration: [
          `avg<${HTTP_AVG_THRESHOLD_MS}`,
          `p(95)<${HTTP_P95_THRESHOLD_MS}`,
        ],
        http_req_failed: ["rate<0.01"],
        checks: ["rate>0.99"],
        invoice_processing_time: [`p(95)<${RENDER_P95_THRESHOLD_MS}`],
      }
    : {},
};

const items = Array.from({ length: 120 }, (_, index) => ({
  description: `Cloud service item ${String(index + 1).padStart(3, "0")}`,
  quantity: (index % 5) + 1,
  unitPrice: 10 + (index % 17) * 1.75,
}));

export function renderInvoice() {
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
    timeout: REQUEST_TIMEOUT,
    responseType: "none",
  });

  const processingHeader = response.headers["X-Processing-Time-Ms"];
  if (processingHeader) {
    const value = Number(processingHeader);
    if (Number.isFinite(value)) {
      processingTime.add(value);
    }
  }

  const passed = check(response, {
    "status is 200": (result) => result.status === 200,
    "response is PDF": (result) =>
      result.headers["Content-Type"]?.includes("application/pdf"),
    "request was handled by a pod": (result) =>
      Boolean(result.headers["X-Pod-Name"]),
  });

  validResponses.add(passed);
  if (passed) {
    successfulRequests.add(1);
  } else {
    failedRequests.add(1);
  }
}

function buildScenarios(profile) {
  const levelDurationSeconds = durationToSeconds(profile.duration);
  const scenarios = {};
  let startSeconds = 0;

  profile.rates.forEach((rate, index) => {
    const phase = `${String(index + 1).padStart(2, "0")}-${rate}rps`;
    const preAllocatedVUs = Math.max(
      numberEnv("PRE_ALLOCATED_VUS", 0),
      Math.ceil(rate * 1.5),
    );
    const maxVUs = Math.max(
      numberEnv("MAX_VUS", 0),
      Math.ceil(rate * 6),
      preAllocatedVUs,
    );

    scenarios[`level_${phase}`] = {
      executor: "constant-arrival-rate",
      exec: "renderInvoice",
      rate,
      timeUnit: "1s",
      duration: profile.duration,
      startTime: `${startSeconds}s`,
      preAllocatedVUs,
      maxVUs,
      gracefulStop: "5s",
      tags: {
        load_profile: PROFILE,
        load_level: String(rate),
        phase,
      },
    };

    startSeconds += levelDurationSeconds;
  });

  return scenarios;
}

function durationToSeconds(value) {
  const match = /^(\d+)(s|m|h)$/.exec(value);
  if (!match) {
    throw new Error(`Unsupported duration "${value}"; use an integer with s, m, or h`);
  }

  const amount = Number(match[1]);
  const multiplier = { s: 1, m: 60, h: 3600 }[match[2]];
  return amount * multiplier;
}

function integerListEnv(name, defaultValue) {
  const raw = __ENV[name];
  if (!raw) {
    return defaultValue;
  }

  const values = raw.split(",").map((item) => Number(item.trim()));
  if (
    values.length === 0 ||
    values.some((value) => !Number.isInteger(value) || value <= 0)
  ) {
    throw new Error(`${name} must be a comma-separated list of positive integers`);
  }

  return values;
}

function numberEnv(name, defaultValue) {
  const value = Number(__ENV[name] ?? defaultValue);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`${name} must be a non-negative number`);
  }
  return value;
}
