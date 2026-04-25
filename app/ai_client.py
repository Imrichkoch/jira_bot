from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from openai import OpenAI

from app.config import Settings


class AIClient:
    def __init__(self, settings: Settings, runtime_context: Callable[[], dict[str, str]] | None = None) -> None:
        self._model = settings.openai_model
        self._runtime_context = runtime_context
        self._use_chat_completions = bool(settings.openai_base_url)
        default_headers: dict[str, str] = {}
        if settings.openai_base_url and "openrouter.ai" in settings.openai_base_url:
            if settings.openrouter_site_url:
                default_headers["HTTP-Referer"] = settings.openrouter_site_url
            if settings.openrouter_app_name:
                default_headers["X-Title"] = settings.openrouter_app_name
                default_headers["X-OpenRouter-Title"] = settings.openrouter_app_name

        client_kwargs: dict[str, object] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            client_kwargs["base_url"] = settings.openai_base_url
        if default_headers:
            client_kwargs["default_headers"] = default_headers

        self._client = OpenAI(**client_kwargs)

    def _current_context(self) -> dict[str, str]:
        if not self._runtime_context:
            return {}
        try:
            return self._runtime_context()
        except Exception:
            return {}

    def _runtime_instructions(self, instructions: str) -> str:
        context = self._current_context()
        system_prompt = (context.get("system_prompt") or "").strip()
        skills_md = (context.get("skills_md") or "").strip()
        parts = []
        if system_prompt:
            parts.append(f"Admin system prompt:\n{system_prompt}")
        if skills_md:
            parts.append(f"skills.md:\n{skills_md}")
        parts.append(f"Task instructions:\n{instructions}")
        return "\n\n".join(parts)

    def _current_model(self) -> str:
        context = self._current_context()
        return (context.get("model") or self._model).strip() or self._model

    def _text_response(self, instructions: str, user_input: str, *, apply_runtime: bool = True) -> str:
        final_instructions = self._runtime_instructions(instructions) if apply_runtime else instructions
        messages = [
            {"role": "system", "content": final_instructions},
            {"role": "user", "content": user_input},
        ]
        if self._use_chat_completions:
            response = self._client.chat.completions.create(
                model=self._current_model(),
                messages=messages,
            )
            message = response.choices[0].message if response.choices else None
            return (message.content if message and message.content else "").strip()
        response = self._client.responses.create(
            model=self._current_model(),
            input=messages,
        )
        return response.output_text.strip()

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json\n", "", 1).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in model output.")
        return json.loads(cleaned[start : end + 1])

    def summarize_issue(self, issue_payload: dict[str, Any]) -> str:
        instructions = (
            "You summarize Jira tickets for engineers. "
            "Return concise markdown with sections: TLDR, Key Details, Risks/Blockers, Next Step."
        )
        return self._text_response(instructions, json.dumps(issue_payload, ensure_ascii=False))

    def generate_jql(self, *, user_query: str, default_project: str) -> str:
        instructions = (
            "You convert natural language into Jira JQL.\n"
            "Rules:\n"
            "1) Return only plain JQL, no markdown, no explanation.\n"
            "2) Prefer project = <default_project> unless user clearly requests another project.\n"
            "3) Keep query safe/read-only (no SQL-like statements).\n"
            "4) Use common fields only: project, summary, description, status, assignee, reporter, labels, priority, created, updated, type.\n"
            "5) Prefer statusCategory for open/closed filters (status names can be localized).\n"
            "6) Add ORDER BY updated DESC when useful.\n"
            f"Default project is: {default_project}"
        )
        return self._text_response(instructions, user_query, apply_runtime=False)

    def detect_chat_action(self, *, user_message: str, default_project: str, default_issue_type: str) -> dict[str, Any]:
        instructions = (
            "You are an intent parser for Jira assistant.\n"
            "Return strictly JSON object only.\n"
            "Supported actions: create, summarize, search, assign, close, help, chat, assets_search, assets_owner, assets_hw, assets_job_file, assets_dora, assets_sla, offboarding, assets_print.\n"
            "JSON schema:\n"
            "{"
            "\"action\":\"create|summarize|search|assign|close|help|chat|assets_search|assets_owner|assets_hw|assets_job_file|assets_dora|assets_sla|offboarding|assets_print\","
            "\"summary\":\"string or null\","
            "\"description\":\"string or null\","
            "\"issue_key\":\"string or null\","
            "\"assignee\":\"string or null\","
            "\"query\":\"string or null\","
            "\"issue_type\":\"string or null\","
            "\"project_key\":\"string or null\""
            "}\n"
            "Rules:\n"
            "1) If user asks to create ticket/work item -> action=create.\n"
            "2) If user asks to summarize one ticket -> action=summarize and include issue_key if present.\n"
            "3) If user asks to find/search/list tickets -> action=search and include query.\n"
            "3b) If user asks to assign ticket to someone -> action=assign and include issue_key + assignee if possible.\n"
            "3c) If user asks to close/resolve ticket -> action=close and include issue_key if possible.\n"
            "4) If user asks Assets owner lookup -> action=assets_owner.\n"
            "5) If user asks Assets HW inventory for person -> action=assets_hw.\n"
            "6) If user asks which job/file mapping in Assets -> action=assets_job_file.\n"
            "7) If user asks DORA relevance from Assets -> action=assets_dora.\n"
            "8) If user asks SLA/business impact from Assets -> action=assets_sla.\n"
            "9) If user asks to offboard someone, end-of-contract, preberaci/odovzdavaci protokol, or prepare handover/return document -> action=offboarding.\n"
            "10) If user asks print protocol for a specific Assets object key like CDX-4 -> action=assets_print.\n"
            "11) If user asks what assistant can do or generic help -> action=help.\n"
            "12) For general conversation/small talk not requiring tool action -> action=chat.\n"
            f"Default project_key: {default_project}\n"
            f"Default issue_type: {default_issue_type}\n"
            "If a field is unknown, set it to null."
        )
        output = self._text_response(instructions, user_message, apply_runtime=False)
        return self._parse_json_object(output)

    def general_chat_reply(self, *, user_message: str, assets_enabled: bool) -> str:
        instructions = (
            "You are a friendly Jira assistant talking to the user in Slovak.\n"
            "Be concise, natural, and helpful.\n"
            "You can work with Jira tickets (create/search/summarize/assign/list users/list tickets/offboarding documents).\n"
            f"Assets features currently {'enabled' if assets_enabled else 'disabled'}.\n"
            "If user asks about unavailable Assets features, explain briefly they are currently unavailable."
        )
        return self._text_response(instructions, user_message)

    def generate_aql(self, *, user_query: str) -> str:
        instructions = (
            "You convert natural language into Jira Assets AQL query.\n"
            "Return only plain AQL, no markdown, no explanation.\n"
            "Prefer generic object types and attrs that are common: Name, Key, Owner, Department, Service, SLA Tier, Business Impact, File, Job, Hostname, Serial Number, Email.\n"
            "Use contains matching with ~ where possible.\n"
            "Keep query read-only."
        )
        return self._text_response(instructions, user_query, apply_runtime=False)

    def build_offboarding_checklist(self, *, user_identifier: str, items_payload: dict[str, Any]) -> str:
        instructions = (
            "You are IT offboarding assistant. Build concise checklist in markdown.\n"
            "Sections: Immediate Revocations, System Access, Hardware Return, Communication, Final Validation.\n"
            "Use provided Jira ticket list and mention ticket keys."
        )
        input_text = json.dumps({"user": user_identifier, "items": items_payload}, ensure_ascii=False)
        return self._text_response(instructions, input_text)
