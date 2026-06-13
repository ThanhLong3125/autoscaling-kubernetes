const express = require("express");
const os = require("os");

const app = express();
const PORT = 8080;

app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    service: "chat-demo-api"
  });
});

app.get("/messages", (req, res) => {
  res.json({
    conversationId: "demo-room-1",
    messages: [
      {
        id: 1,
        sender: "user_a",
        content: "Xin chào",
        createdAt: new Date().toISOString()
      },
      {
        id: 2,
        sender: "user_b",
        content: "Chào bạn",
        createdAt: new Date().toISOString()
      }
    ],
    servedBy: os.hostname()
  });
});

app.get("/cpu", (req, res) => {
  const start = Date.now();

  while (Date.now() - start < 500) {
    Math.sqrt(Math.random() * 1000000);
  }

  res.json({
    message: "CPU workload completed",
    durationMs: Date.now() - start,
    servedBy: os.hostname()
  });
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Chat demo API running on port ${PORT}`);
  console.log(`Health check endpoint: http://localhost:${PORT}/health`);
  console.log(`Messages endpoint: http://localhost:${PORT}/messages`);
  console.log(`CPU workload endpoint: http://localhost:${PORT}/cpu`);
});