from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class LdapUser:
    username: str
    display_name: str
    email: str | None


class LdapAuthenticationError(Exception):
    """A safe, user-facing LDAP authentication failure."""


class LdapAuthenticator:
    """Authenticate administrators against LDAP without retaining user passwords."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @staticmethod
    def _library() -> Any:
        try:
            import ldap3
            from ldap3.utils.conv import escape_filter_chars
        except ImportError as exc:
            raise LdapAuthenticationError("LDAP support is not installed on this server.") from exc
        return ldap3, escape_filter_chars

    def _server(self) -> Any:
        ldap3, _ = self._library()
        url = str(self._config.get("server_url") or "").strip()
        if not url:
            raise LdapAuthenticationError("LDAP server URL is not configured.")
        use_ssl = bool(self._config.get("use_ssl", True))
        parsed = urlparse(url)
        if parsed.scheme not in {"ldap", "ldaps"} or not parsed.hostname:
            raise LdapAuthenticationError("LDAP server URL is invalid.")
        if parsed.scheme == "ldaps":
            use_ssl = True
        return ldap3.Server(
            parsed.hostname,
            port=parsed.port or (636 if use_ssl else 389),
            use_ssl=use_ssl,
            connect_timeout=5,
            get_info=ldap3.NONE,
        )

    def _bind_service_account(self) -> Any:
        ldap3, _ = self._library()
        bind_dn = str(self._config.get("bind_dn") or "").strip()
        bind_password = os.getenv("LDAP_BIND_PASSWORD", "")
        if not bind_dn or not bind_password:
            raise LdapAuthenticationError("LDAP service account is not configured on the server.")
        connection = ldap3.Connection(self._server(), user=bind_dn, password=bind_password, receive_timeout=8)
        if not connection.bind():
            raise LdapAuthenticationError("LDAP service account could not connect.")
        return connection

    def validate_connection(self) -> None:
        connection = self._bind_service_account()
        connection.unbind()

    def authenticate_admin(self, username: str, password: str) -> LdapUser | None:
        ldap3, escape_filter_chars = self._library()
        search_base = str(self._config.get("user_search_base") or "").strip()
        username_attribute = str(self._config.get("username_attribute") or "uid").strip()
        admin_group_dn = str(self._config.get("admin_group_dn") or "").strip()
        if not search_base or not admin_group_dn:
            raise LdapAuthenticationError("LDAP user search base or administrator group is not configured.")

        service = self._bind_service_account()
        escaped_username = escape_filter_chars(username.strip())
        search_filter = f"({username_attribute}={escaped_username})"
        attributes = ["distinguishedName", "cn", "displayName", "mail", "memberOf", username_attribute]
        if not service.search(search_base, search_filter, search_scope=ldap3.SUBTREE, attributes=attributes) or len(service.entries) != 1:
            service.unbind()
            return None

        entry = service.entries[0]
        entry_dn = str(entry.entry_dn)
        group_attribute = getattr(entry, "memberOf", None)
        group_values = getattr(group_attribute, "values", []) if group_attribute else []
        member_of = {str(value).lower() for value in group_values}
        service.unbind()
        if admin_group_dn.lower() not in member_of:
            return None

        user_connection = ldap3.Connection(self._server(), user=entry_dn, password=password, receive_timeout=8)
        if not user_connection.bind():
            return None
        user_connection.unbind()

        def value(name: str) -> str:
            attribute = getattr(entry, name, None)
            return str(attribute.value).strip() if attribute and attribute.value else ""

        return LdapUser(
            username=value(username_attribute) or username.strip(),
            display_name=value("displayName") or value("cn") or username.strip(),
            email=value("mail") or None,
        )
