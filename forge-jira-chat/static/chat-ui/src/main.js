import { invoke, view, Modal } from "@forge/bridge";
import "./styles.css";

const chatEl = document.getElementById("chat");
const formEl = document.getElementById("form");
const inputEl = document.getElementById("input");
const sendEl = document.getElementById("send");
const popoutEl = document.getElementById("popout");
const issueEl = document.getElementById("issue");

let issueKey = null;
const conversation = [];

function addBubble(text, role, links = []) {
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  const body = document.createElement("div");
  body.textContent = text;
  el.appendChild(body);
  for (const link of links) {
    const a = document.createElement("a");
    a.className = "download-link";
    a.href = link.href;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = link.label;
    el.appendChild(a);
  }
  chatEl.appendChild(el);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function addToConversation(role, content) {
  conversation.push({ role, content: String(content || "") });
  if (conversation.length > 40) {
    conversation.splice(0, conversation.length - 40);
  }
}

function normalizeResponse(data) {
  if (!data) return "No response.";
  if (data.action === "assets_print" && data.data?.protocol) {
    return data.data.protocol;
  }

  if (String(data.action || "").startsWith("assets_")) {
    const lines = [];
    lines.push(data.message || "Assets response.");
    if (data.data?.aql) lines.push(`AQL: ${data.data.aql}`);
    if (typeof data.data?.total === "number") lines.push(`Total: ${data.data.total}`);
    if (Array.isArray(data.data?.objects) && data.data.objects.length) {
      lines.push("\nAssets:");
      for (const obj of data.data.objects.slice(0, 12)) {
        const key = obj.objectKey || obj.id || "?";
        const label = obj.label || "(no label)";
        const type = obj.objectType || "Object";
        lines.push(`- ${key}: ${label} (${type})`);
        const attrs = obj.attributes || {};
        const preferred = [
          "Assigned user",
          "Owner",
          "Name",
          "Serial Number",
          "Hostname",
          "Department",
          "Email",
          "SLA Tier",
          "Business Impact"
        ];
        const picked = [];
        for (const name of preferred) {
          if (attrs[name] !== undefined && attrs[name] !== null && String(attrs[name]).trim()) {
            picked.push([name, attrs[name]]);
          }
        }
        if (!picked.length) {
          const fallback = Object.entries(attrs).slice(0, 4);
          for (const [k, v] of fallback) {
            picked.push([k, v]);
          }
        }
        for (const [k, v] of picked.slice(0, 4)) {
          lines.push(`  - ${k}: ${v}`);
        }
      }
    } else {
      lines.push("Nenasiel som ziadne konkretne assety pre tento dotaz.");
    }
    return lines.join("\n");
  }

  const lines = [];
  lines.push(data.message || "Done.");
  if (data.action === "offboarding" && data.data?.document_url) {
    if (data.data?.template?.name) lines.push(`Sablona: ${data.data.template.name}`);
    if (data.data?.format) lines.push(`Format: ${data.data.format}`);
    if (Array.isArray(data.data?.assets)) lines.push(`Zariadenia: ${data.data.assets.length}`);
    lines.push(`Subor: ${data.data.document_url}`);
    return lines.join("\n");
  }
  if (data.data?.summary) lines.push(`\n${data.data.summary}`);
  if (data.data?.jql) lines.push(`JQL: ${data.data.jql}`);
  if (Array.isArray(data.data?.issues) && data.data.issues.length) {
    lines.push("\nIssues:");
    for (const it of data.data.issues.slice(0, 8)) {
      lines.push(`- ${it.key}: ${it.summary || "(no summary)"}`);
    }
  }
  if (Array.isArray(data.data?.users) && data.data.users.length) {
    lines.push("\nUsers:");
    for (const u of data.data.users.slice(0, 10)) {
      lines.push(`- ${u.display_name || "(no name)"}`);
    }
  }
  return lines.join("\n");
}

function responseLinks(data) {
  const links = [];
  if (data?.data?.document_url) {
    links.push({
      href: data.data.document_url,
      label: `Stiahnut ${data.data.file_name || "dokument"}`
    });
  }
  if (data?.data?.protocol_url) {
    links.push({ href: data.data.protocol_url, label: "Stiahnut protokol" });
  }
  return links;
}

async function boot() {
  const ctx = await view.getContext();
  issueKey = ctx?.extension?.issue?.key || ctx?.extension?.modal?.issueKey || null;
  const modalHistory = ctx?.extension?.modal?.history;
  if (Array.isArray(modalHistory) && modalHistory.length) {
    for (const item of modalHistory) {
      addBubble(item.content || "", item.role === "user" ? "user" : "bot");
      addToConversation(item.role === "user" ? "user" : "assistant", item.content || "");
    }
  } else {
    const hello = "Ahoj, som Jira bot v Jira paneli. Napis poziadavku.";
    addBubble(hello, "bot");
    addToConversation("assistant", hello);
  }
  issueEl.textContent = `Issue: ${issueKey || "-"}`;

  const inModal = Boolean(ctx?.extension?.modal);
  if (inModal) {
    popoutEl.style.display = "none";
  } else {
    popoutEl.addEventListener("click", async () => {
      const modal = new Modal({
        resource: "chat-modal",
        size: "max",
        title: `Jira AI Chat ${issueKey ? `- ${issueKey}` : ""}`,
        context: { issueKey, history: conversation.slice(-20) }
      });
      await modal.open();
    });
  }
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = inputEl.value.trim();
  if (!message) return;

  addBubble(message, "user");
  addToConversation("user", message);
  inputEl.value = "";
  sendEl.disabled = true;

  try {
    const result = await invoke("sendMessage", {
      message,
      issueKey,
      history: conversation.slice(-20)
    });
    if (!result?.ok) {
      const err = `Error: ${result?.error || "Request failed"}`;
      addBubble(err, "bot");
      addToConversation("assistant", err);
    } else {
      const text = normalizeResponse(result.data);
      addBubble(text, "bot", responseLinks(result.data));
      addToConversation("assistant", text);
    }
  } catch (err) {
    const msg = `Error: ${err?.message || String(err)}`;
    addBubble(msg, "bot");
    addToConversation("assistant", msg);
  } finally {
    sendEl.disabled = false;
    inputEl.focus();
  }
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

boot();
