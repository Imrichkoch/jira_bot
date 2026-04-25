from __future__ import annotations

import hashlib
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

