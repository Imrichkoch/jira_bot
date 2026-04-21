from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.config import Settings


class AIClient:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.openai_model
        default_headers: dict[str, str] = {}
        if settings.openai_base_url and "openrouter.ai" in settings.openai_base_url:
            if settings.openrouter_site_url:
                default_headers["HTTP-Referer"] = settings.openrouter_site_url
            if settings.openrouter_app_name:
                default_headers["X-Title"] = settings.openrouter_app_name

        client_kwargs: dict[str, object] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            client_kwargs["base_url"] = settings.openai_base_url
        if default_headers:
            client_kwargs["default_headers"] = default_headers

        self._client = OpenAI(**client_kwargs)

    def _text_response(self, instructions: str, user_input: str) -> str:
        response = self._client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_input},
            ],
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
            "5) Add ORDER BY updated DESC when useful.\n"
            f"Default project is: {default_project}"
        )
        return self._text_response(instructions, user_query)

    def detect_chat_action(self, *, user_message: str, default_project: str, default_issue_type: str) -> dict[str, Any]:
        instructions = (
            "You are an intent parser for Jira assistant.\n"
            "Return strictly JSON object only.\n"
            "Supported actions: create, summarize, search, help, assets_search, assets_owner, assets_hw, assets_job_file, assets_dora, assets_sla, offboarding, assets_print.\n"
            "JSON schema:\n"
            "{"
            "\"action\":\"create|summarize|search|help|assets_search|assets_owner|assets_hw|assets_job_file|assets_dora|assets_sla|offboarding|assets_print\","
            "\"summary\":\"string or null\","
            "\"description\":\"string or null\","
            "\"issue_key\":\"string or null\","
            "\"query\":\"string or null\","
            "\"issue_type\":\"string or null\","
            "\"project_key\":\"string or null\""
            "}\n"
            "Rules:\n"
            "1) If user asks to create ticket/work item -> action=create.\n"
            "2) If user asks to summarize one ticket -> action=summarize and include issue_key if present.\n"
            "3) If user asks to find/search/list tickets -> action=search and include query.\n"
            "4) If user asks Assets owner lookup -> action=assets_owner.\n"
            "5) If user asks Assets HW inventory for person -> action=assets_hw.\n"
            "6) If user asks which job/file mapping in Assets -> action=assets_job_file.\n"
            "7) If user asks DORA relevance from Assets -> action=assets_dora.\n"
            "8) If user asks SLA/business impact from Assets -> action=assets_sla.\n"
            "9) If user asks end-of-contract access list/checklist -> action=offboarding.\n"
            "10) If user asks print protocol for Assets object -> action=assets_print.\n"
            "11) If user asks what assistant can do or generic help -> action=help.\n"
            f"Default project_key: {default_project}\n"
            f"Default issue_type: {default_issue_type}\n"
            "If a field is unknown, set it to null."
        )
        output = self._text_response(instructions, user_message)
        return self._parse_json_object(output)

    def generate_aql(self, *, user_query: str) -> str:
        instructions = (
            "You convert natural language into Jira Assets AQL query.\n"
            "Return only plain AQL, no markdown, no explanation.\n"
            "Prefer generic object types and attrs that are common: Name, Key, Owner, Department, Service, SLA Tier, Business Impact, File, Job, Hostname, Serial Number, Email.\n"
            "Use contains matching with ~ where possible.\n"
            "Keep query read-only."
        )
        return self._text_response(instructions, user_query)

    def build_offboarding_checklist(self, *, user_identifier: str, items_payload: dict[str, Any]) -> str:
        instructions = (
            "You are IT offboarding assistant. Build concise checklist in markdown.\n"
            "Sections: Immediate Revocations, System Access, Hardware Return, Communication, Final Validation.\n"
            "Use provided Jira ticket list and mention ticket keys."
        )
        input_text = json.dumps({"user": user_identifier, "items": items_payload}, ensure_ascii=False)
        return self._text_response(instructions, input_text)
