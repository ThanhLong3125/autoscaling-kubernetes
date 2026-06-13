const { performance } = require("node:perf_hooks");

const BASE_URL = (process.env.BASE_URL || "http://localhost:8080").replace(
  /\/$/,
  "",
);
const REQUESTS_PER_ENDPOINT = parsePositiveInteger(
  "REQUESTS_PER_ENDPOINT",
  10,
);
const THRESHOLD_MS = parsePositiveNumber("THRESHOLD_MS", 700);
const REQUEST_TIMEOUT_MS = parsePositiveNumber("REQUEST_TIMEOUT_MS", 2000);
const ENDPOINTS = ["/health", "/messages", "/cpu"];

function parsePositiveNumber(name, defaultValue) {
  const value = Number(process.env[name] ?? defaultValue);

  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} must be a positive number`);
  }

  return value;
}

function parsePositiveInteger(name, defaultValue) {
  const value = parsePositiveNumber(name, defaultValue);

  if (!Number.isInteger(value)) {
    throw new Error(`${name} must be an integer`);
  }

  return value;
}

function percentile(values, percentileValue) {
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.ceil((percentileValue / 100) * sorted.length);
  return sorted[Math.max(0, rank - 1)];
}

function summarize(values) {
  const total = values.reduce((sum, value) => sum + value, 0);

  return {
    mean: total / values.length,
    p95: percentile(values, 95),
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

function formatMilliseconds(value) {
  return `${value.toFixed(2)} ms`;
}

async function measure(endpoint, iteration) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const start = performance.now();

  try {
    const response = await fetch(`${BASE_URL}${endpoint}`, {
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    await response.arrayBuffer();
    const duration = performance.now() - start;
    console.log(
      `${endpoint.padEnd(10)} request ${String(iteration).padStart(2)}: ${formatMilliseconds(duration)}`,
    );
    return duration;
  } catch (error) {
    const reason =
      error.name === "AbortError"
        ? `timeout after ${REQUEST_TIMEOUT_MS} ms`
        : error.message;
    throw new Error(`${endpoint} request ${iteration} failed: ${reason}`);
  } finally {
    clearTimeout(timeout);
  }
}

async function main() {
  console.log(`Base URL: ${BASE_URL}`);
  console.log(
    `Measuring ${ENDPOINTS.length} endpoints, ${REQUESTS_PER_ENDPOINT} requests each`,
  );
  console.log(`Threshold: mean and p95 < ${THRESHOLD_MS} ms\n`);

  const results = new Map();

  for (const endpoint of ENDPOINTS) {
    const durations = [];

    for (let iteration = 1; iteration <= REQUESTS_PER_ENDPOINT; iteration += 1) {
      durations.push(await measure(endpoint, iteration));
    }

    results.set(endpoint, durations);
    console.log();
  }

  const summaries = [...results.entries()].map(([endpoint, durations]) => ({
    endpoint,
    ...summarize(durations),
  }));
  const combined = summarize([...results.values()].flat());

  console.log("Summary");
  console.table(
    summaries.map(({ endpoint, mean, p95, min, max }) => ({
      endpoint,
      "mean (ms)": mean.toFixed(2),
      "p95 (ms)": p95.toFixed(2),
      "min (ms)": min.toFixed(2),
      "max (ms)": max.toFixed(2),
    })),
  );
  console.log(
    `Combined (${ENDPOINTS.length * REQUESTS_PER_ENDPOINT} requests): mean=${formatMilliseconds(combined.mean)}, p95=${formatMilliseconds(combined.p95)}, min=${formatMilliseconds(combined.min)}, max=${formatMilliseconds(combined.max)}`,
  );

  const failures = summaries
    .filter(({ mean, p95 }) => mean >= THRESHOLD_MS || p95 >= THRESHOLD_MS)
    .map(({ endpoint }) => endpoint);

  if (combined.mean >= THRESHOLD_MS || combined.p95 >= THRESHOLD_MS) {
    failures.push("combined");
  }

  if (failures.length > 0) {
    console.error(
      `\nFAIL: threshold was not met by ${failures.join(", ")}.`,
    );
    process.exitCode = 1;
    return;
  }

  console.log(`\nPASS: all endpoint and combined means/p95 are below ${THRESHOLD_MS} ms.`);
}

main().catch((error) => {
  console.error(`\nERROR: ${error.message}`);
  process.exitCode = 1;
});
