from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_LDAP_SETTINGS = {
    "mode": "local",
    "server_url": "",
    "use_ssl": True,
    "bind_dn": "",
    "user_search_base": "",
    "username_attribute": "uid",
    "admin_group_dn": "",
}


class LdapSettingsStore:
    """Stores non-secret LDAP settings separately from process environment secrets."""

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "ldap_settings.json"
        data_dir.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict[str, Any]:
        data = dict(DEFAULT_LDAP_SETTINGS)
        if self._path.exists():
            try:
                stored = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    data.update({key: stored.get(key, value) for key, value in DEFAULT_LDAP_SETTINGS.items()})
            except (OSError, json.JSONDecodeError):
                pass
        data["bind_password_configured"] = bool(__import__("os").environ.get("LDAP_BIND_PASSWORD", ""))
        return data

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        mode = str(values.get("mode") or "local").lower().strip()
        if mode not in {"local", "ldap", "hybrid"}:
            raise ValueError("Authentication mode must be local, ldap, or hybrid.")
        data = {
            "mode": mode,
            "server_url": str(values.get("server_url") or "").strip(),
            "use_ssl": bool(values.get("use_ssl", True)),
            "bind_dn": str(values.get("bind_dn") or "").strip(),
            "user_search_base": str(values.get("user_search_base") or "").strip(),
            "username_attribute": str(values.get("username_attribute") or "uid").strip(),
            "admin_group_dn": str(values.get("admin_group_dn") or "").strip(),
        }
        if mode != "local":
            required = ["server_url", "bind_dn", "user_search_base", "username_attribute", "admin_group_dn"]
            missing = [key for key in required if not data[key]]
            if missing:
                raise ValueError(f"LDAP mode requires: {', '.join(missing)}.")
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get()
