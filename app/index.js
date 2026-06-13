const express = require("express");
const os = require("os");

const app = express();
const PORT = 8080;
const HEALTH_DELAY_MS = getDelay("HEALTH_DELAY_MS", 640);
const MESSAGES_DELAY_MS = getDelay("MESSAGES_DELAY_MS", 640);

function getDelay(name, defaultValue) {
  const value = Number(process.env[name] ?? defaultValue);

  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`${name} must be a non-negative number`);
  }

  return value;
}

/**
 * Health Check
 */
app.get("/health", (req, res) => {
  setTimeout(() => {
    res.json({
      status: "ok",
      service: "chat-demo-api",
      pod: os.hostname(),
      timestamp: new Date().toISOString(),
    });
  }, HEALTH_DELAY_MS);
});

/**
 * Simulate chat messages
 */
app.get("/messages", (req, res) => {
  setTimeout(() => {
    res.json({
      conversationId: "demo-room-1",
      messages: [
        {
          id: 1,
          sender: "user_a",
          content: "Xin chào",
          createdAt: new Date().toISOString(),
        },
        {
          id: 2,
          sender: "user_b",
          content: "Chào bạn",
          createdAt: new Date().toISOString(),
        },
      ],
      servedBy: os.hostname(),
    });
  }, MESSAGES_DELAY_MS);
});

/**
 * CPU workload endpoint
 *
 * ~100ms CPU time
 */
app.get("/cpu", (req, res) => {
  const start = Date.now();

  while (Date.now() - start < 100) {
    Math.sqrt(Math.random());
  }

  const processingTime = Date.now() - start;

  res.json({
    status: "ok",
    pod: os.hostname(),
    processingTimeMs: processingTime,
    timestamp: new Date().toISOString(),
  });
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Chat Demo API started`);
  console.log(`PORT=${PORT}`);
});
