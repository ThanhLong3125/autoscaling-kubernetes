const { performance } = require("node:perf_hooks");

const BASE_URL = (process.env.BASE_URL || "http://localhost:8080").replace(
  /\/$/,
  "",
);
const WARMUP_REQUESTS = positiveInteger("WARMUP_REQUESTS", 5);
const REQUESTS = positiveInteger("REQUESTS", 30);
const REQUEST_TIMEOUT_MS = positiveNumber("REQUEST_TIMEOUT_MS", 5000);
const THRESHOLD_MULTIPLIER = positiveNumber("THRESHOLD_MULTIPLIER", 2);

const invoice = {
  invoiceNumber: "INV-BASELINE",
  customerName: "Baseline customer",
  currency: "USD",
  issuedAt: new Date().toISOString(),
  items: Array.from({ length: 120 }, (_, index) => ({
    description: `Cloud service item ${String(index + 1).padStart(3, "0")}`,
    quantity: (index % 5) + 1,
    unitPrice: 10 + (index % 17) * 1.75,
  })),
};

function positiveNumber(name, defaultValue) {
  const value = Number(process.env[name] ?? defaultValue);

  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} must be a positive number`);
  }

  return value;
}

function positiveInteger(name, defaultValue) {
  const value = positiveNumber(name, defaultValue);

  if (!Number.isInteger(value)) {
    throw new Error(`${name} must be an integer`);
  }

  return value;
}

function percentile(sortedValues, percentileValue) {
  const rank = Math.ceil((percentileValue / 100) * sortedValues.length);
  return sortedValues[Math.max(0, rank - 1)];
}

function summarize(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const total = sorted.reduce((sum, value) => sum + value, 0);

  return {
    average: total / sorted.length,
    min: sorted[0],
    median: percentile(sorted, 50),
    p90: percentile(sorted, 90),
    p95: percentile(sorted, 95),
    p99: percentile(sorted, 99),
    max: sorted[sorted.length - 1],
  };
}

function roundThreshold(value) {
  return Math.max(50, Math.ceil(value / 50) * 50);
}

async function requestInvoice(iteration, phase) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const start = performance.now();

  try {
    const response = await fetch(`${BASE_URL}/api/invoices/render`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/pdf",
      },
      body: JSON.stringify({
        ...invoice,
        invoiceNumber: `${invoice.invoiceNumber}-${phase}-${iteration}`,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }

    if (!response.headers.get("content-type")?.includes("application/pdf")) {
      throw new Error("response is not a PDF");
    }

    const pdf = await response.arrayBuffer();
    const durationMs = performance.now() - start;
    const processingTimeMs = Number(
      response.headers.get("x-processing-time-ms"),
    );

    if (!Number.isFinite(processingTimeMs)) {
      throw new Error("response is missing X-Processing-Time-Ms");
    }

    return {
      durationMs,
      processingTimeMs,
      bytes: pdf.byteLength,
      pod: response.headers.get("x-pod-name") || "unknown",
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function main() {
  console.log(`Base URL: ${BASE_URL}`);
  console.log(`Payload: ${invoice.items.length} invoice items`);
  console.log(`Warm-up requests: ${WARMUP_REQUESTS}`);
  console.log(`Measured requests: ${REQUESTS}\n`);

  for (let iteration = 1; iteration <= WARMUP_REQUESTS; iteration += 1) {
    const result = await requestInvoice(iteration, "warmup");
    console.log(
      `Warm-up ${String(iteration).padStart(2)}: HTTP=${result.durationMs.toFixed(2)} ms, render=${result.processingTimeMs.toFixed(2)} ms`,
    );
  }

  console.log("\nMeasured requests");
  const results = [];

  for (let iteration = 1; iteration <= REQUESTS; iteration += 1) {
    const result = await requestInvoice(iteration, "measure");
    results.push(result);
    console.log(
      `Request ${String(iteration).padStart(2)}: HTTP=${result.durationMs.toFixed(2)} ms, render=${result.processingTimeMs.toFixed(2)} ms, PDF=${result.bytes} bytes, pod=${result.pod}`,
    );
  }

  const http = summarize(results.map(({ durationMs }) => durationMs));
  const render = summarize(
    results.map(({ processingTimeMs }) => processingTimeMs),
  );
  const rows = [
    {
      metric: "HTTP response",
      average: http.average,
      median: http.median,
      p90: http.p90,
      p95: http.p95,
      p99: http.p99,
      max: http.max,
    },
    {
      metric: "PDF render",
      average: render.average,
      median: render.median,
      p90: render.p90,
      p95: render.p95,
      p99: render.p99,
      max: render.max,
    },
  ];

  console.log("\nBaseline summary (ms)");
  console.table(
    rows.map((row) => ({
      metric: row.metric,
      average: row.average.toFixed(2),
      median: row.median.toFixed(2),
      p90: row.p90.toFixed(2),
      p95: row.p95.toFixed(2),
      p99: row.p99.toFixed(2),
      max: row.max.toFixed(2),
    })),
  );

  const httpAverageThreshold = roundThreshold(
    http.average * THRESHOLD_MULTIPLIER,
  );
  const httpP95Threshold = roundThreshold(http.p95 * THRESHOLD_MULTIPLIER);
  const renderP95Threshold = roundThreshold(
    render.p95 * THRESHOLD_MULTIPLIER,
  );

  console.log(
    `Suggested exploratory thresholds (${THRESHOLD_MULTIPLIER}x baseline):`,
  );
  console.log(`  HTTP average < ${httpAverageThreshold} ms`);
  console.log(`  HTTP p95     < ${httpP95Threshold} ms`);
  console.log(`  Render p95   < ${renderP95Threshold} ms`);
  console.log("\nRun k6 with:");
  console.log(
    `HTTP_AVG_THRESHOLD_MS=${httpAverageThreshold} HTTP_P95_THRESHOLD_MS=${httpP95Threshold} RENDER_P95_THRESHOLD_MS=${renderP95Threshold} BASE_URL=${BASE_URL} k6 run k6/load-test.js`,
  );
  console.log(
    "\nThese are baseline-derived experimental thresholds, not production SLAs.",
  );
}

main().catch((error) => {
  const reason =
    error.name === "AbortError"
      ? `request timed out after ${REQUEST_TIMEOUT_MS} ms`
      : error.message;
  console.error(`ERROR: ${reason}`);
  process.exitCode = 1;
});
