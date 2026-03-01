import { Hono } from "hono";
import { cors } from "hono/cors";
import type { Env, Variables } from "./lib/types.js";
import auth from "./routes/auth.js";
import packages from "./routes/packages.js";
import resolve from "./routes/resolve.js";
import agent from "./routes/agent.js";

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// ── Global Middleware ──────────────────────────────────────────────────

// CORS: allow all origins for now
app.use("*", cors({
  origin: "*",
  allowMethods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
  allowHeaders: ["Content-Type", "Authorization"],
  exposeHeaders: ["Content-Length"],
  maxAge: 86400,
}));

// Default JSON content type for API responses
app.use("/v1/*", async (c, next) => {
  await next();
  if (!c.res.headers.get("Content-Type")) {
    c.res.headers.set("Content-Type", "application/json");
  }
});

// ── Error Handling ─────────────────────────────────────────────────────

app.onError((err, c) => {
  console.error(`[ERROR] ${err.message}`, err.stack);

  if (err.message.includes("JSON")) {
    return c.json({ error: "Invalid JSON in request body" }, 400);
  }

  return c.json(
    { error: "Internal server error", message: err.message },
    500
  );
});

app.notFound((c) => {
  return c.json({ error: "Not found" }, 404);
});

// ── Health Check ───────────────────────────────────────────────────────

app.get("/", (c) => {
  return c.json({
    name: "SecureSkillHub API",
    version: c.env.API_VERSION || "v1",
    status: "ok",
  });
});

app.get("/health", (c) => {
  return c.json({ status: "ok" });
});

// ── Route Groups ───────────────────────────────────────────────────────

// Auth routes: /v1/auth/*
app.route("/v1/auth", auth);

// Package management routes: /v1/me/packages/*
app.route("/v1/me/packages", packages);

// Resolve routes are mounted at /v1 since they handle both
// /v1/me/packages/:id/resolve and /v1/packages/:id/resolve
app.route("/v1", resolve);

// Agent routes: /v1/agent/*
app.route("/v1/agent", agent);

export default app;
