from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class AdminStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    admin_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(admin_id) REFERENCES admins(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_group_permissions (
                    group_id INTEGER NOT NULL,
                    permission TEXT NOT NULL,
                    PRIMARY KEY(group_id, permission),
                    FOREIGN KEY(group_id) REFERENCES bot_groups(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_group_members (
                    group_id INTEGER NOT NULL,
                    account_id TEXT NOT NULL,
                    display_name TEXT,
                    email TEXT,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, account_id),
                    FOREIGN KEY(group_id) REFERENCES bot_groups(id) ON DELETE CASCADE
                )
                """
            )

    @staticmethod
    def _hash_password(password: str, salt: str | None = None) -> str:
        if salt is None:
            salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
        return f"pbkdf2_sha256${salt}${digest.hex()}"

    @staticmethod
    def _verify_password(password: str, password_hash: str) -> bool:
        try:
            algo, salt, expected = password_hash.split("$", 2)
        except ValueError:
            return False
        if algo != "pbkdf2_sha256":
            return False
        actual = AdminStore._hash_password(password, salt).split("$", 2)[2]
        return secrets.compare_digest(actual, expected)

    def count_admins(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM admins").fetchone()
            return int(row["count"])

    def bootstrap_admin(self, username: str | None, password: str | None) -> bool:
        if not username or not password or self.count_admins() > 0:
            return False
        self.create_admin(username=username, password=password, display_name=username)
        return True

    def create_admin(self, *, username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
        username = username.strip().lower()
        if len(username) < 3:
            raise ValueError("Username must have at least 3 characters.")
        if len(password) < 10:
            raise ValueError("Password must have at least 10 characters.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO admins (username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (username, display_name or username, self._hash_password(password), now),
            )
            row = conn.execute(
                "SELECT id, username, display_name, created_at FROM admins WHERE username = ?",
                (username,),
            ).fetchone()
        return dict(row)

    def list_admins(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, username, display_name, created_at FROM admins ORDER BY created_at ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def authenticate(self, *, username: str, password: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, display_name, password_hash, created_at FROM admins WHERE username = ?",
                (username.strip().lower(),),
            ).fetchone()
        if not row or not self._verify_password(password, row["password_hash"]):
            return None
        admin = dict(row)
        admin.pop("password_hash", None)
        return admin

    def create_session(self, admin_id: int, hours: int = 12) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=hours)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token, admin_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token, admin_id, expires_at.isoformat(), now.isoformat()),
            )
        return token

    def get_session_admin(self, token: str) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT admins.id, admins.username, admins.display_name, admins.created_at
                FROM sessions
                JOIN admins ON admins.id = sessions.admin_id
                WHERE sessions.token = ? AND sessions.expires_at > ?
                """,
                (token, now),
            ).fetchone()
        return dict(row) if row else None

    def _group_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        group = dict(row)
        group_id = int(group["id"])
        permissions = conn.execute(
            "SELECT permission FROM bot_group_permissions WHERE group_id = ? ORDER BY permission ASC",
            (group_id,),
        ).fetchall()
        members = conn.execute(
            """
            SELECT account_id, display_name, email, added_at
            FROM bot_group_members
            WHERE group_id = ?
            ORDER BY lower(COALESCE(display_name, email, account_id)) ASC
            """,
            (group_id,),
        ).fetchall()
        group["permissions"] = [str(item["permission"]) for item in permissions]
        group["members"] = [dict(item) for item in members]
        return group

    def list_bot_groups(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, description, created_at FROM bot_groups ORDER BY lower(name) ASC"
            ).fetchall()
            return [self._group_from_row(conn, row) for row in rows]

    def bot_groups_configured(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM bot_groups").fetchone()
            return int(row["count"]) > 0

    def create_bot_group(
        self,
        *,
        name: str,
        description: str | None = None,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        clean_name = re.sub(r"\s+", " ", name or "").strip()
        if len(clean_name) < 2:
            raise ValueError("Group name must have at least 2 characters.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO bot_groups (name, description, created_at) VALUES (?, ?, ?)",
                (clean_name, (description or "").strip() or None, now),
            )
            group_id = int(cur.lastrowid)
            self._replace_group_permissions(conn, group_id, permissions or [])
            row = conn.execute(
                "SELECT id, name, description, created_at FROM bot_groups WHERE id = ?",
                (group_id,),
            ).fetchone()
            return self._group_from_row(conn, row)

    def update_bot_group(
        self,
        group_id: int,
        *,
        name: str,
        description: str | None = None,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        clean_name = re.sub(r"\s+", " ", name or "").strip()
        if len(clean_name) < 2:
            raise ValueError("Group name must have at least 2 characters.")
        with self._connect() as conn:
            conn.execute(
                "UPDATE bot_groups SET name = ?, description = ? WHERE id = ?",
                (clean_name, (description or "").strip() or None, group_id),
            )
            if conn.total_changes <= 0:
                raise ValueError("Group not found.")
            self._replace_group_permissions(conn, group_id, permissions or [])
            row = conn.execute(
                "SELECT id, name, description, created_at FROM bot_groups WHERE id = ?",
                (group_id,),
            ).fetchone()
            if not row:
                raise ValueError("Group not found.")
            return self._group_from_row(conn, row)

    def delete_bot_group(self, group_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM bot_group_permissions WHERE group_id = ?", (group_id,))
            conn.execute("DELETE FROM bot_group_members WHERE group_id = ?", (group_id,))
            cur = conn.execute("DELETE FROM bot_groups WHERE id = ?", (group_id,))
            if cur.rowcount <= 0:
                raise ValueError("Group not found.")

    def _replace_group_permissions(
        self,
        conn: sqlite3.Connection,
        group_id: int,
        permissions: list[str],
    ) -> None:
        conn.execute("DELETE FROM bot_group_permissions WHERE group_id = ?", (group_id,))
        unique_permissions = sorted({str(permission).strip() for permission in permissions if str(permission).strip()})
        conn.executemany(
            "INSERT INTO bot_group_permissions (group_id, permission) VALUES (?, ?)",
            [(group_id, permission) for permission in unique_permissions],
        )

    def add_bot_group_member(
        self,
        group_id: int,
        *,
        account_id: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        clean_account_id = (account_id or "").strip()
        if not clean_account_id:
            raise ValueError("Jira account_id is required.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            exists = conn.execute("SELECT id FROM bot_groups WHERE id = ?", (group_id,)).fetchone()
            if not exists:
                raise ValueError("Group not found.")
            conn.execute(
                """
                INSERT INTO bot_group_members (group_id, account_id, display_name, email, added_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_id, account_id)
                DO UPDATE SET display_name = excluded.display_name, email = excluded.email
                """,
                (
                    group_id,
                    clean_account_id,
                    (display_name or "").strip() or None,
                    (email or "").strip() or None,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT account_id, display_name, email, added_at
                FROM bot_group_members
                WHERE group_id = ? AND account_id = ?
                """,
                (group_id, clean_account_id),
            ).fetchone()
            return dict(row)

    def remove_bot_group_member(self, group_id: int, account_id: str) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM bot_group_members WHERE group_id = ? AND account_id = ?",
                (group_id, account_id),
            )
            if cur.rowcount <= 0:
                raise ValueError("Group member not found.")

    def permissions_for_account(self, account_id: str) -> set[str]:
        clean_account_id = (account_id or "").strip()
        if not clean_account_id:
            return set()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT permission
                FROM bot_group_members
                JOIN bot_group_permissions ON bot_group_permissions.group_id = bot_group_members.group_id
                WHERE bot_group_members.account_id = ?
                """,
                (clean_account_id,),
            ).fetchall()
        return {str(row["permission"]) for row in rows}
