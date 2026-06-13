const express = require("express");
const os = require("os");
const PDFDocument = require("pdfkit");

const app = express();
const PORT = Number(process.env.PORT || 8080);
const MAX_ITEMS = 200;

app.use(express.json({ limit: "1mb" }));

app.get("/healthz", (req, res) => {
  res.json({
    status: "ok",
    service: "invoice-pdf-api",
    pod: os.hostname(),
    timestamp: new Date().toISOString(),
  });
});

app.post("/api/invoices/render", async (req, res, next) => {
  try {
    const invoice = validateInvoice(req.body);
    const start = process.hrtime.bigint();
    const pdf = await renderInvoice(invoice);
    const processingTimeMs =
      Number(process.hrtime.bigint() - start) / 1_000_000;

    res.set({
      "Content-Type": "application/pdf",
      "Content-Disposition": `inline; filename="${invoice.invoiceNumber}.pdf"`,
      "Content-Length": pdf.length,
      "X-Pod-Name": os.hostname(),
      "X-Processing-Time-Ms": processingTimeMs.toFixed(2),
    });
    res.send(pdf);
  } catch (error) {
    next(error);
  }
});

app.use((error, req, res, next) => {
  if (res.headersSent) {
    next(error);
    return;
  }

  const status = error.status || 500;
  res.status(status).json({
    error: status === 500 ? "Failed to render invoice" : error.message,
  });
});

function validateInvoice(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw badRequest("Request body must be a JSON object");
  }

  const invoiceNumber = requiredText(value.invoiceNumber, "invoiceNumber", 60);
  const customerName = requiredText(value.customerName, "customerName", 120);
  const currency = requiredText(value.currency || "USD", "currency", 8);

  if (!Array.isArray(value.items) || value.items.length === 0) {
    throw badRequest("items must be a non-empty array");
  }

  if (value.items.length > MAX_ITEMS) {
    throw badRequest(`items must contain at most ${MAX_ITEMS} entries`);
  }

  const items = value.items.map((item, index) => {
    const position = `items[${index}]`;

    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw badRequest(`${position} must be an object`);
    }

    const quantity = positiveNumber(item.quantity, `${position}.quantity`);
    const unitPrice = positiveNumber(item.unitPrice, `${position}.unitPrice`);

    return {
      description: requiredText(
        item.description,
        `${position}.description`,
        160,
      ),
      quantity,
      unitPrice,
      amount: quantity * unitPrice,
    };
  });

  return {
    invoiceNumber,
    customerName,
    currency,
    issuedAt: optionalText(value.issuedAt, new Date().toISOString(), 40),
    items,
  };
}

function requiredText(value, field, maxLength) {
  if (typeof value !== "string" || value.trim() === "") {
    throw badRequest(`${field} must be a non-empty string`);
  }

  if (value.length > maxLength) {
    throw badRequest(`${field} must not exceed ${maxLength} characters`);
  }

  return value.trim();
}

function optionalText(value, defaultValue, maxLength) {
  if (value === undefined || value === null || value === "") {
    return defaultValue;
  }

  return requiredText(value, "issuedAt", maxLength);
}

function positiveNumber(value, field) {
  const number = Number(value);

  if (!Number.isFinite(number) || number <= 0) {
    throw badRequest(`${field} must be a positive number`);
  }

  return number;
}

function badRequest(message) {
  const error = new Error(message);
  error.status = 400;
  return error;
}

function renderInvoice(invoice) {
  return new Promise((resolve, reject) => {
    const document = new PDFDocument({
      size: "A4",
      margin: 48,
      info: {
        Title: `Invoice ${invoice.invoiceNumber}`,
        Author: "Invoice PDF API",
      },
    });
    const chunks = [];

    document.on("data", (chunk) => chunks.push(chunk));
    document.on("end", () => resolve(Buffer.concat(chunks)));
    document.on("error", reject);

    document.fontSize(22).text("INVOICE", { align: "center" });
    document.moveDown();
    document.fontSize(11);
    document.text(`Invoice number: ${invoice.invoiceNumber}`);
    document.text(`Customer: ${invoice.customerName}`);
    document.text(`Issued at: ${invoice.issuedAt}`);
    document.moveDown();

    drawTableHeader(document);

    let total = 0;
    invoice.items.forEach((item, index) => {
      ensureTableSpace(document);
      total += item.amount;
      const y = document.y;

      document.text(String(index + 1), 48, y, { width: 30 });
      document.text(item.description, 82, y, { width: 255 });
      document.text(formatNumber(item.quantity), 345, y, {
        width: 55,
        align: "right",
      });
      document.text(formatMoney(item.unitPrice), 405, y, {
        width: 70,
        align: "right",
      });
      document.text(formatMoney(item.amount), 480, y, {
        width: 67,
        align: "right",
      });
      document.moveDown(1.25);
    });

    document.moveDown();
    document
      .font("Helvetica-Bold")
      .fontSize(13)
      .text(
        `Total: ${formatMoney(total)} ${invoice.currency}`,
        { align: "right" },
      );
    document.end();
  });
}

function drawTableHeader(document) {
  document.font("Helvetica-Bold").fontSize(10);
  const y = document.y;
  document.text("#", 48, y, { width: 30 });
  document.text("Description", 82, y, { width: 255 });
  document.text("Qty", 345, y, { width: 55, align: "right" });
  document.text("Unit price", 405, y, { width: 70, align: "right" });
  document.text("Amount", 480, y, { width: 67, align: "right" });
  document.moveDown(1.4);
  document.font("Helvetica").fontSize(9);
}

function ensureTableSpace(document) {
  if (document.y < 750) {
    return;
  }

  document.addPage();
  drawTableHeader(document);
}

function formatMoney(value) {
  return value.toFixed(2);
}

function formatNumber(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Invoice PDF API listening on port ${PORT}`);
});
