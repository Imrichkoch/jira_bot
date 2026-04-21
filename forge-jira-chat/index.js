import Resolver from "@forge/resolver";
import api from "@forge/api";

const resolver = new Resolver();

resolver.define("sendMessage", async ({ payload }) => {
  const backendUrl = process.env.BOT_BACKEND_URL;
  const widgetSecret = process.env.BOT_WIDGET_SECRET || "";
  if (!backendUrl) {
    return {
      ok: false,
      error: "BOT_BACKEND_URL is not set in Forge variables."
    };
  }

  const issueKey = payload?.issueKey || null;
  const history = Array.isArray(payload?.history) ? payload.history.slice(-20) : [];
  const message = String(payload?.message || "").trim();
  if (!message) {
    return { ok: false, error: "Message is empty." };
  }

  const headers = {
    "Content-Type": "application/json"
  };
  if (widgetSecret) {
    headers["x-widget-secret"] = widgetSecret;
  }

  const response = await api.fetch(`${backendUrl.replace(/\/$/, "")}/chat/widget`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      message,
      max_results: 20,
      max_comments: 20,
      current_issue_key: issueKey,
      history
    })
  });

  const raw = await response.text();
  let data;
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    data = { detail: raw };
  }

  if (!response.ok) {
    return {
      ok: false,
      error: data?.detail || `Backend error (${response.status})`
    };
  }

  return { ok: true, data };
});

export const handler = resolver.getDefinitions();
