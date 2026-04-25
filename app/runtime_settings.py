from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SYSTEM_PROMPT = (
    "You are a practical Jira assistant for an IT team. "
    "Answer in Slovak unless the user asks otherwise. "
    "Be concise, concrete, and use Jira/Assets context when available."
)

DEFAULT_SKILLS_MD = """# Jira Bot Skills

## Ticket operations
- Create, search, summarize, assign, and close Jira tickets.
- Ask for clarification only when the requested action is unsafe or missing a required issue key/user.

## Assets operations
- For questions about a person's hardware, first resolve the Jira user, then return only assets assigned to that user.
- For handover protocol requests, include the user and assigned hardware when possible.

## Response style
- Prefer concise Slovak answers with concrete object keys, issue keys, names, and next steps.
"""


class RuntimeSettingsStore:
    def __init__(self, data_dir: Path, default_model: str, repo_skills_path: Path) -> None:
        self._data_dir = data_dir
        self._settings_path = data_dir / "bot_settings.json"
        self._skills_path = data_dir / "skills.md"
        self._repo_skills_path = repo_skills_path
        self._default_model = default_model
        self._data_dir.mkdir(parents=True, exist_ok=True)
        if not self._repo_skills_path.exists():
            self._repo_skills_path.write_text(DEFAULT_SKILLS_MD, encoding="utf-8")

    def get(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self._settings_path.exists():
            try:
                raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except json.JSONDecodeError:
                data = {}
        skills_path = self._skills_path if self._skills_path.exists() else self._repo_skills_path
        skills_md = skills_path.read_text(encoding="utf-8") if skills_path.exists() else DEFAULT_SKILLS_MD
        return {
            "model": str(data.get("model") or self._default_model),
            "system_prompt": str(data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT),
            "skills_md": skills_md,
        }

    def update(self, *, model: str, system_prompt: str, skills_md: str) -> dict[str, Any]:
        model = model.strip()
        system_prompt = system_prompt.strip()
        skills_md = skills_md.strip()
        if not model:
            raise ValueError("Model is required.")
        if not system_prompt:
            raise ValueError("System prompt is required.")
        self._settings_path.write_text(
            json.dumps({"model": model, "system_prompt": system_prompt}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._skills_path.write_text(skills_md or DEFAULT_SKILLS_MD, encoding="utf-8")
        return self.get()

    def ai_context(self) -> dict[str, str]:
        data = self.get()
        return {
            "model": data["model"],
            "system_prompt": data["system_prompt"],
            "skills_md": data["skills_md"],
        }

