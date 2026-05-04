import Resolver from "@forge/resolver";
import api from "@forge/api";

const resolver = new Resolver();

resolver.define("sendMessage", async ({ payload, context }) => {
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
  const pendingAction = payload?.pendingAction && typeof payload.pendingAction === "object" ? payload.pendingAction : null;
  const message = String(payload?.message || "").trim();
  if (!message) {
    return { ok: false, error: "Message is empty." };
  }
  const currentUser = {
    account_id: context?.accountId || null,
    cloud_id: context?.cloudId || null,
    module_key: context?.moduleKey || null
  };

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
      current_user: currentUser,
      history,
      pending_action: pendingAction
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

  const publicBackendUrl = backendUrl.replace(/\/$/, "");
  for (const key of ["document_url", "protocol_url"]) {
    if (typeof data?.data?.[key] === "string" && data.data[key].startsWith("/")) {
      data.data[key] = `${publicBackendUrl}${data.data[key]}`;
    }
  }

  return { ok: true, data };
});

export const handler = resolver.getDefinitions();
