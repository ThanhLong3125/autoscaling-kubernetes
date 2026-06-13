const express = require("express");
const os = require("os");

const app = express();
const PORT = 8080;

/**
 * Health Check
 */
app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    service: "chat-demo-api",
    pod: os.hostname(),
    timestamp: new Date().toISOString(),
  });
});

/**
 * Simulate chat messages
 */
app.get("/messages", (req, res) => {
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

  res.json({
    status: "ok",
    pod: os.hostname(),
    processingTimeMs: Date.now() - start,
  });
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Chat Demo API started`);
  console.log(`PORT=${PORT}`);
});