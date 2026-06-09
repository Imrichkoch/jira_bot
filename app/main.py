import base64
import hashlib
import hmac
import re
import json
import secrets
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.admin_store import AdminStore
from app.ai_client import AIClient
from app.analysis import cosine_similarity, extract_adf_text, flatten_assets_object, overlap_keywords
from app.config import get_settings
from app.jira_client import JiraClient
from app.jql_guard import JQLValidationError, validate_jql
from app.offboarding_documents import OffboardingTemplateStore, render_offboarding_document
from app.runtime_settings import RuntimeSettingsStore
from app.schemas import (
    CreateTicketRequest,
    CreateTicketResponse,
    ClassifyIncidentRequest,
    ClassifyIncidentResponse,
    AssignTicketRequest,
    AssignTicketResponse,
    ChatRequest,
    ChatResponse,
    CorrelateChangesRequest,
    CorrelateChangesResponse,
    AssetsQueryRequest,
    AssetsQueryResponse,
    OffboardingChecklistRequest,
    OffboardingChecklistResponse,
    AssetsPrintProtocolRequest,
    AssetsPrintProtocolResponse,
    SearchTicketsRequest,
    SearchTicketsResponse,
    SimilarTicketsRequest,
    SimilarTicketsResponse,
    SummarizeTicketRequest,
    SummarizeTicketResponse,
)

app = FastAPI(title="Jira AI Bot API", version="0.1.0")

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = Path(settings.app_data_dir) if settings.app_data_dir else PROJECT_DIR / "data"
runtime_settings = RuntimeSettingsStore(
    data_dir=DATA_DIR,
    default_model=settings.openai_model,
    repo_skills_path=PROJECT_DIR / "skills.md",
)
admin_store = AdminStore(DATA_DIR / "admin.sqlite3")
admin_store.bootstrap_admin(settings.admin_bootstrap_username, settings.admin_bootstrap_password)
template_store = OffboardingTemplateStore(DATA_DIR, root_name="offboarding_templates")
onboarding_template_store = OffboardingTemplateStore(DATA_DIR, root_name="onboarding_templates")
jira = JiraClient(settings)
ai = AIClient(settings, runtime_context=runtime_settings.ai_context)
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = DATA_DIR / "generated"
PENDING_ACTION_TTL_SECONDS = 30 * 60
DOWNLOAD_TOKEN_TTL_SECONDS = 4 * 60 * 60
_SECURITY_SECRET = (settings.widget_shared_secret or "").strip() or secrets.token_urlsafe(32)


class RestrictedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]) -> Any:
        first_segment = path.replace("\\", "/").split("/", 1)[0].lower()
        if first_segment in {"offboarding", "onboarding", "protocols"}:
            raise StarletteHTTPException(status_code=404)
        return await super().get_response(path, scope)


app.mount("/static", RestrictedStaticFiles(directory=str(STATIC_DIR)), name="static")


MODEL_CATALOG = [
    {
        "provider": "OpenAI direct",
        "note": "Direct OpenAI models. Use these when OPENAI_BASE_URL is empty.",
        "models": [
            {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini"},
            {"id": "gpt-5.4", "label": "GPT-5.4"},
            {"id": "gpt-5.3-codex", "label": "GPT-5.3 Codex"},
            {"id": "gpt-5-mini", "label": "GPT-5 Mini"},
            {"id": "gpt-4.1", "label": "GPT-4.1"},
            {"id": "o4-mini", "label": "o4-mini"},
        ],
    },
    {
        "provider": "OpenAI via OpenRouter",
        "note": "OpenRouter model IDs. Requires OPENAI_BASE_URL=https://openrouter.ai/api/v1.",
        "models": [
            {"id": "openai/gpt-5.5-pro", "label": "GPT-5.5 Pro"},
            {"id": "openai/gpt-5.5", "label": "GPT-5.5"},
            {"id": "openai/gpt-5.4-mini", "label": "OpenRouter: GPT-5.4 Mini"},
            {"id": "openai/gpt-5.4", "label": "OpenRouter: GPT-5.4"},
            {"id": "openai/gpt-5.3-codex", "label": "GPT-5.3 Codex"},
            {"id": "openai/gpt-5.2-codex", "label": "GPT-5.2 Codex"},
        ],
    },
    {
        "provider": "Anthropic",
        "note": "OpenRouter model IDs. Requires OPENAI_BASE_URL=https://openrouter.ai/api/v1.",
        "models": [
            {"id": "anthropic/claude-opus-4.7", "label": "Claude Opus 4.7"},
            {"id": "anthropic/claude-opus-4.6", "label": "Claude Opus 4.6"},
            {"id": "anthropic/claude-sonnet-4.6", "label": "Claude Sonnet 4.6"},
            {"id": "anthropic/claude-opus-4.5", "label": "Claude Opus 4.5"},
            {"id": "anthropic/claude-haiku-4.5", "label": "Claude Haiku 4.5"},
            {"id": "anthropic/claude-sonnet-4.5", "label": "Claude Sonnet 4.5"},
            {"id": "anthropic/claude-opus-4.1", "label": "Claude Opus 4.1"},
            {"id": "anthropic/claude-sonnet-4", "label": "Claude Sonnet 4"},
            {"id": "anthropic/claude-3.7-sonnet", "label": "Claude 3.7 Sonnet"},
        ],
    },
    {
        "provider": "Google",
        "note": "OpenRouter model IDs. Requires OPENAI_BASE_URL=https://openrouter.ai/api/v1.",
        "models": [
            {"id": "google/gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro Preview"},
            {"id": "google/gemini-3.1-flash-lite-preview", "label": "Gemini 3.1 Flash Lite Preview"},
            {"id": "google/gemini-3-flash-preview", "label": "Gemini 3 Flash Preview"},
            {"id": "google/gemini-2.0-flash-001", "label": "Gemini 2.0 Flash"},
            {"id": "google/gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
            {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        ],
    },
    {
        "provider": "DeepSeek",
        "note": "OpenRouter model IDs. Requires OPENAI_BASE_URL=https://openrouter.ai/api/v1.",
        "models": [
            {"id": "deepseek/deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
            {"id": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
            {"id": "deepseek/deepseek-v3.2", "label": "DeepSeek V3.2"},
            {"id": "deepseek/deepseek-v3.1-terminus", "label": "DeepSeek V3.1 Terminus"},
            {"id": "deepseek/deepseek-chat", "label": "DeepSeek Chat"},
            {"id": "deepseek/deepseek-chat-v3.1", "label": "DeepSeek Chat v3.1"},
            {"id": "deepseek/deepseek-r1", "label": "DeepSeek R1"},
            {"id": "deepseek/deepseek-r1-0528", "label": "DeepSeek R1 0528"},
        ],
    },
    {
        "provider": "Meta / Llama",
        "note": "OpenRouter model IDs. Requires OPENAI_BASE_URL=https://openrouter.ai/api/v1.",
        "models": [
            {"id": "meta-llama/llama-4-maverick", "label": "Llama 4 Maverick"},
            {"id": "meta-llama/llama-4-scout", "label": "Llama 4 Scout"},
            {"id": "meta-llama/llama-3.3-70b-instruct", "label": "Llama 3.3 70B Instruct"},
        ],
    },
    {
        "provider": "Mistral",
        "note": "OpenRouter model IDs. Requires OPENAI_BASE_URL=https://openrouter.ai/api/v1.",
        "models": [
            {"id": "mistralai/mistral-large-2512", "label": "Mistral Large 25.12"},
            {"id": "mistralai/mistral-large", "label": "Mistral Large"},
            {"id": "mistralai/mistral-medium-3.1", "label": "Mistral Medium 3.1"},
            {"id": "mistralai/codestral-2508", "label": "Codestral"},
            {"id": "mistralai/mixtral-8x22b-instruct", "label": "Mixtral 8x22B"},
        ],
    },
    {
        "provider": "Qwen",
        "note": "OpenRouter model IDs. Requires OPENAI_BASE_URL=https://openrouter.ai/api/v1.",
        "models": [
            {"id": "qwen/qwen3.6-plus", "label": "Qwen 3.6 Plus"},
            {"id": "qwen/qwen3-coder-next", "label": "Qwen 3 Coder Next"},
            {"id": "qwen/qwen3-max-thinking", "label": "Qwen 3 Max Thinking"},
            {"id": "qwen/qwen-2.5-coder-32b-instruct", "label": "Qwen 2.5 Coder 32B"},
            {"id": "qwen/qwen-2.5-72b-instruct", "label": "Qwen 2.5 72B"},
            {"id": "qwen/qwq-32b", "label": "QwQ 32B"},
        ],
    },
    {
        "provider": "xAI",
        "note": "OpenRouter model IDs. Requires OPENAI_BASE_URL=https://openrouter.ai/api/v1.",
        "models": [
            {"id": "x-ai/grok-4.20", "label": "Grok 4.20"},
            {"id": "x-ai/grok-4.1-fast", "label": "Grok 4.1 Fast"},
            {"id": "x-ai/grok-code-fast-1", "label": "Grok Code Fast 1"},
            {"id": "x-ai/grok-4", "label": "Grok 4"},
            {"id": "x-ai/grok-3", "label": "Grok 3"},
            {"id": "x-ai/grok-3-mini", "label": "Grok 3 Mini"},
        ],
    },
    {
        "provider": "Other",
        "note": "Manual custom model ID. Use this when a model appears on OpenRouter before it is in this preset list.",
        "models": [
            {"id": "custom", "label": "Custom model ID"},
        ],
    },
]
AVAILABLE_MODELS = [model["id"] for group in MODEL_CATALOG for model in group["models"] if model["id"] != "custom"]
BOT_PERMISSIONS = [
    {
        "id": "chat",
        "label": "Chat",
        "description": "Vseobecne odpovede a pomoc bez zapisu do Jira.",
    },
    {
        "id": "tickets.read",
        "label": "Tickety - citanie",
        "description": "Vyhladavanie, zoznam a sumarizacia ticketov.",
    },
    {
        "id": "tickets.write",
        "label": "Tickety - vytvaranie",
        "description": "Vytvaranie novych ticketov.",
    },
    {
        "id": "tickets.assign",
        "label": "Tickety - priradenie",
        "description": "Priradovanie ticketov pouzivatelom.",
    },
    {
        "id": "tickets.close",
        "label": "Tickety - zatvaranie",
        "description": "Zatvaranie alebo riesenie ticketov.",
    },
    {
        "id": "users.read",
        "label": "Jira pouzivatelia",
        "description": "Zobrazenie Jira pouzivatelov cez bota.",
    },
    {
        "id": "assets.read",
        "label": "Assets - citanie",
        "description": "Vyhladavanie v Assets a zobrazenie zariadeni.",
    },
    {
        "id": "assets.write",
        "label": "Assets - zapis",
        "description": "Priradenie alebo odobratie zariadeni v Assets.",
    },
    {
        "id": "documents.generate",
        "label": "Dokumenty",
        "description": "Generovanie onboarding/offboarding protokolov.",
    },
]
BOT_PERMISSION_IDS = {permission["id"] for permission in BOT_PERMISSIONS}
ACTION_PERMISSION_MAP = {
    "chat": ["chat"],
    "help": ["chat"],
    "whoami": ["chat"],
    "search": ["tickets.read"],
    "list_tickets": ["tickets.read"],
    "summarize": ["tickets.read"],
    "similar": ["tickets.read"],
    "create": ["tickets.write"],
    "assign": ["tickets.assign"],
    "assign_bulk": ["tickets.assign"],
    "close": ["tickets.close"],
    "list_users": ["users.read"],
    "offboarding_checklist": ["tickets.read"],
    "assets_search": ["assets.read"],
    "assets_owner": ["assets.read"],
    "assets_hw": ["assets.read"],
    "assets_job_file": ["assets.read"],
    "assets_dora": ["assets.read"],
    "assets_sla": ["assets.read"],
    "assets_print": ["assets.read", "documents.generate"],
    "offboarding": ["assets.read", "assets.write", "documents.generate"],
    "onboarding": ["assets.read", "assets.write", "documents.generate"],
}


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=500)


class AdminCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=500)
    display_name: str | None = Field(default=None, max_length=120)


class BotGroupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list)


class BotGroupMemberRequest(BaseModel):
    account_id: str = Field(min_length=5, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)


class BotSettingsRequest(BaseModel):
    model: str = Field(min_length=2, max_length=120)
    system_prompt: str = Field(min_length=1, max_length=8000)
    skills_md: str = Field(default="", max_length=20000)


class OffboardingTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    file_name: str = Field(min_length=4, max_length=255)
    content_base64: str = Field(min_length=1)
    template_format: str | None = Field(default=None, max_length=10)
    fields: dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class OffboardingDocumentRequest(BaseModel):
    user_identifier: str = Field(min_length=2, max_length=255)
    extra_text: str | None = Field(default=None, max_length=2000)
    template_id: str | None = Field(default=None, max_length=80)


def _admin_from_authorization(authorization: str | None) -> dict[str, Any] | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return admin_store.get_session_admin(token)


def _require_admin(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    admin = _admin_from_authorization(authorization)
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid or expired admin session.")
    return admin


def _has_valid_widget_secret(x_widget_secret: str | None) -> bool:
    expected = (settings.widget_shared_secret or "").strip()
    supplied = (x_widget_secret or "").strip()
    return bool(expected and supplied and secrets.compare_digest(supplied, expected))


def _require_api_access(
    authorization: str | None = Header(default=None),
    x_widget_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    if _has_valid_widget_secret(x_widget_secret):
        return {"type": "widget"}
    admin = _admin_from_authorization(authorization)
    if admin:
        return {"type": "admin", "admin": admin}
    raise HTTPException(status_code=401, detail="API access requires an admin session or a valid widget secret.")


def _require_widget_access(x_widget_secret: str | None = Header(default=None)) -> dict[str, Any]:
    if not (settings.widget_shared_secret or "").strip():
        raise HTTPException(status_code=503, detail="WIDGET_SHARED_SECRET is not configured.")
    if not _has_valid_widget_secret(x_widget_secret):
        raise HTTPException(status_code=401, detail="Unauthorized widget request.")
    return {"type": "widget"}


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign_bytes(raw: bytes) -> str:
    return _b64url_encode(hmac.new(_SECURITY_SECRET.encode("utf-8"), raw, hashlib.sha256).digest())


def _signed_pending_action(pending: dict[str, Any]) -> dict[str, str]:
    envelope = {
        "v": 1,
        "exp": int(time.time()) + PENDING_ACTION_TTL_SECONDS,
        "payload": pending,
    }
    raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"token": f"{_b64url_encode(raw)}.{_sign_bytes(raw)}"}


def _pending_data(pending: dict[str, Any], **extra: Any) -> dict[str, Any]:
    data = {"pending_action": _signed_pending_action(pending)}
    data.update(extra)
    return data


def _decode_pending_action(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    token = value.get("token") if isinstance(value, dict) else None
    if not isinstance(token, str) or "." not in token:
        raise HTTPException(status_code=400, detail="Pending action is missing or unsigned. Please repeat the previous request.")
    raw_part, sig_part = token.split(".", 1)
    try:
        raw = _b64url_decode(raw_part)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Pending action is invalid. Please repeat the previous request.") from exc
    expected_sig = _sign_bytes(raw)
    if not secrets.compare_digest(sig_part, expected_sig):
        raise HTTPException(status_code=400, detail="Pending action signature is invalid. Please repeat the previous request.")
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Pending action is invalid. Please repeat the previous request.") from exc
    if int(envelope.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=400, detail="Pending action expired. Please repeat the previous request.")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Pending action is invalid. Please repeat the previous request.")
    return payload


def _download_signature(kind: str, file_name: str, expires: int) -> str:
    raw = f"{kind}/{file_name}:{expires}".encode("utf-8")
    return _sign_bytes(raw)


def _signed_download_url(kind: str, file_name: str) -> str:
    expires = int(time.time()) + DOWNLOAD_TOKEN_TTL_SECONDS
    token = _download_signature(kind, file_name, expires)
    return f"/download/{kind}/{file_name}?expires={expires}&token={token}"


def _generated_file_path(kind: str, file_name: str) -> Path:
    if kind not in {"offboarding", "onboarding", "protocols"}:
        raise HTTPException(status_code=404, detail="Unknown download type.")
    safe_name = Path(file_name).name
    if safe_name != file_name or not safe_name:
        raise HTTPException(status_code=404, detail="File not found.")
    path = (GENERATED_DIR / kind / safe_name).resolve()
    root = (GENERATED_DIR / kind).resolve()
    if root not in path.parents and path != root:
        raise HTTPException(status_code=404, detail="File not found.")
    return path


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def chat_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/download/{kind}/{file_name}")
def download_generated_file(kind: str, file_name: str, expires: int = Query(...), token: str = Query(...)) -> FileResponse:
    if expires < int(time.time()):
        raise HTTPException(status_code=403, detail="Download link expired.")
    expected = _download_signature(kind, file_name, expires)
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid download token.")
    path = _generated_file_path(kind, file_name)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, filename=file_name)


@app.post("/admin/api/login")
def admin_login(payload: AdminLoginRequest) -> dict[str, Any]:
    admin = admin_store.authenticate(username=payload.username, password=payload.password)
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = admin_store.create_session(int(admin["id"]))
    return {"token": token, "admin": admin}


@app.get("/admin/api/me")
def admin_me(admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    return {"admin": admin}


@app.get("/admin/api/admins")
def admin_list(admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    return {"admins": admin_store.list_admins()}


@app.post("/admin/api/admins")
def admin_create(payload: AdminCreateRequest, admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    try:
        created = admin_store.create_admin(
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Admin account could not be created.") from exc
    return {"admin": created}


def _validate_bot_permissions(permissions: list[str]) -> list[str]:
    clean_permissions = sorted({str(permission).strip() for permission in permissions if str(permission).strip()})
    unknown = [permission for permission in clean_permissions if permission not in BOT_PERMISSION_IDS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown bot permission(s): {', '.join(unknown)}")
    return clean_permissions


def _map_jira_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_id": user.get("accountId") or user.get("account_id"),
        "display_name": user.get("displayName") or user.get("display_name"),
        "email": user.get("emailAddress") or user.get("email"),
        "active": user.get("active"),
    }


@app.get("/admin/api/jira-users")
def admin_jira_users(
    query: str = Query(default="", max_length=120),
    max_results: int = Query(default=100, ge=1, le=200),
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    users: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        if query.strip():
            users.extend(jira.search_users(query=query.strip(), max_results=max_results))
        else:
            users.extend(jira.list_assignable_users(project_key=settings.jira_project_key, max_results=max_results))
    except Exception as exc:
        errors.append(str(exc))
    if not users and query.strip():
        try:
            users.extend(jira.list_assignable_users(project_key=settings.jira_project_key, max_results=max_results))
        except Exception as exc:
            errors.append(str(exc))

    seen: set[str] = set()
    mapped: list[dict[str, Any]] = []
    query_norm = _normalize_lookup_text(query)
    for user in users:
        item = _map_jira_user(user)
        account_id = str(item.get("account_id") or "").strip()
        if not account_id or account_id in seen:
            continue
        text = _normalize_lookup_text(f"{item.get('display_name') or ''} {item.get('email') or ''}")
        if query_norm and query_norm not in text:
            tokens = [token for token in re.findall(r"[a-z0-9]{2,}", query_norm) if token not in {"user", "users"}]
            if tokens and not all(token in text for token in tokens):
                continue
        seen.add(account_id)
        mapped.append(item)
    return {"users": mapped[:max_results], "errors": errors}


@app.get("/admin/api/bot-permissions")
def admin_bot_permissions(admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    return {"permissions": BOT_PERMISSIONS}


@app.get("/admin/api/bot-groups")
def admin_bot_groups(admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    return {"groups": admin_store.list_bot_groups()}


@app.post("/admin/api/bot-groups")
def admin_create_bot_group(payload: BotGroupRequest, admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    permissions = _validate_bot_permissions(payload.permissions)
    try:
        group = admin_store.create_bot_group(
            name=payload.name,
            description=payload.description,
            permissions=permissions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Bot group could not be created.") from exc
    return {"group": group, "groups": admin_store.list_bot_groups()}


@app.put("/admin/api/bot-groups/{group_id}")
def admin_update_bot_group(
    group_id: int,
    payload: BotGroupRequest,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    permissions = _validate_bot_permissions(payload.permissions)
    try:
        group = admin_store.update_bot_group(
            group_id,
            name=payload.name,
            description=payload.description,
            permissions=permissions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Bot group could not be updated.") from exc
    return {"group": group, "groups": admin_store.list_bot_groups()}


@app.delete("/admin/api/bot-groups/{group_id}")
def admin_delete_bot_group(group_id: int, admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    try:
        admin_store.delete_bot_group(group_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"groups": admin_store.list_bot_groups()}


@app.post("/admin/api/bot-groups/{group_id}/members")
def admin_add_bot_group_member(
    group_id: int,
    payload: BotGroupMemberRequest,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        member = admin_store.add_bot_group_member(
            group_id,
            account_id=payload.account_id,
            display_name=payload.display_name,
            email=payload.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"member": member, "groups": admin_store.list_bot_groups()}


@app.delete("/admin/api/bot-groups/{group_id}/members/{account_id}")
def admin_remove_bot_group_member(
    group_id: int,
    account_id: str,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        admin_store.remove_bot_group_member(group_id, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"groups": admin_store.list_bot_groups()}


@app.get("/admin/api/settings")
def admin_get_settings(admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    data = runtime_settings.get()
    return {"settings": data, "available_models": AVAILABLE_MODELS, "model_catalog": MODEL_CATALOG}


@app.put("/admin/api/settings")
def admin_update_settings(payload: BotSettingsRequest, admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    try:
        data = runtime_settings.update(
            model=payload.model,
            system_prompt=payload.system_prompt,
            skills_md=payload.skills_md,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"settings": data, "available_models": AVAILABLE_MODELS, "model_catalog": MODEL_CATALOG}


@app.get("/admin/api/offboarding-templates")
def admin_list_offboarding_templates(admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    return {"templates": template_store.list_templates()}


@app.post("/admin/api/offboarding-templates")
def admin_add_offboarding_template(
    payload: OffboardingTemplateRequest,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        template = template_store.add_template(
            name=payload.name,
            file_name=payload.file_name,
            content_base64=payload.content_base64,
            template_format=payload.template_format,
            fields=payload.fields,
            active=payload.active,
        )
        return {"template": template, "templates": template_store.list_templates()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/admin/api/offboarding-templates/{template_id}/active")
def admin_activate_offboarding_template(
    template_id: str,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        template = template_store.set_active(template_id)
        return {"template": template, "templates": template_store.list_templates()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/admin/api/offboarding-templates/{template_id}/fields")
def admin_update_offboarding_template_fields(
    template_id: str,
    fields: dict[str, Any],
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        template = template_store.update_fields(template_id, fields)
        return {"template": template, "templates": template_store.list_templates()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/admin/api/offboarding-templates/{template_id}")
def admin_delete_offboarding_template(
    template_id: str,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        template_store.delete(template_id)
        return {"templates": template_store.list_templates()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/admin/api/onboarding-templates")
def admin_list_onboarding_templates(admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    return {"templates": onboarding_template_store.list_templates()}


@app.post("/admin/api/onboarding-templates")
def admin_add_onboarding_template(
    payload: OffboardingTemplateRequest,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        template = onboarding_template_store.add_template(
            name=payload.name,
            file_name=payload.file_name,
            content_base64=payload.content_base64,
            template_format=payload.template_format,
            fields=payload.fields,
            active=payload.active,
        )
        return {"template": template, "templates": onboarding_template_store.list_templates()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/admin/api/onboarding-templates/{template_id}/active")
def admin_activate_onboarding_template(
    template_id: str,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        template = onboarding_template_store.set_active(template_id)
        return {"template": template, "templates": onboarding_template_store.list_templates()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/admin/api/onboarding-templates/{template_id}/fields")
def admin_update_onboarding_template_fields(
    template_id: str,
    fields: dict[str, Any],
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        template = onboarding_template_store.update_fields(template_id, fields)
        return {"template": template, "templates": onboarding_template_store.list_templates()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/admin/api/onboarding-templates/{template_id}")
def admin_delete_onboarding_template(
    template_id: str,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        onboarding_template_store.delete(template_id)
        return {"templates": onboarding_template_store.list_templates()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _search_logic(query: str, max_results: int) -> SearchTicketsResponse:
    raw_jql = ai.generate_jql(user_query=query, default_project=settings.jira_project_key)
    jql_candidate = raw_jql.strip()
    if not re.search(r"\bproject\s*=", jql_candidate, flags=re.IGNORECASE):
        if jql_candidate:
            jql_candidate = f"project = {settings.jira_project_key} AND ({jql_candidate})"
        else:
            jql_candidate = f"project = {settings.jira_project_key} ORDER BY updated DESC"
    safe_jql = validate_jql(jql_candidate)
    result = jira.search(jql=safe_jql, max_results=max_results)
    issues = []
    for issue in result.get("issues", []):
        fields = issue.get("fields", {})
        assignee = fields.get("assignee") or {}
        issues.append(
            {
                "key": issue.get("key"),
                "summary": fields.get("summary"),
                "status": (fields.get("status") or {}).get("name"),
                "priority": (fields.get("priority") or {}).get("name"),
                "assignee": assignee.get("displayName"),
                "updated": fields.get("updated"),
                "created": fields.get("created"),
                "issue_type": (fields.get("issuetype") or {}).get("name"),
            }
        )
    total = result.get("total")
    if not isinstance(total, int):
        total = len(issues)
    return SearchTicketsResponse(jql=safe_jql, total=total, issues=issues)


def _issue_text(fields: dict[str, Any]) -> str:
    summary = fields.get("summary") or ""
    desc = extract_adf_text(fields.get("description"))
    return f"{summary}\n{desc}".strip()


def _require_assets_workspace() -> str:
    workspace_id = settings.assets_workspace_id
    if not workspace_id:
        raise HTTPException(
            status_code=400,
            detail="ASSETS_WORKSPACE_ID is not configured. Add it to env file and restart service.",
        )
    return workspace_id


def _assets_enabled() -> bool:
    return bool(settings.assets_workspace_id)


def _assets_search_from_nl(nl_query: str, max_results: int) -> AssetsQueryResponse:
    workspace_id = _require_assets_workspace()
    aql = ai.generate_aql(user_query=nl_query)
    data = None
    used_aql = aql
    used_fallback = False
    try:
        data = jira.assets_query(workspace_id=workspace_id, aql=aql, max_results=max_results)
    except Exception:
        # Fallback for invalid AQL or unknown attributes in custom schemas.
        fallback = "objectId > 0"
        data = jira.assets_query(workspace_id=workspace_id, aql=fallback, max_results=max(100, max_results))
        used_aql = fallback
        used_fallback = True

    objects_raw = data.get("objectEntries") or data.get("results", {}).get("objectEntries") or data.get("values") or []
    if not objects_raw and not used_fallback:
        fallback = "objectId > 0"
        data = jira.assets_query(workspace_id=workspace_id, aql=fallback, max_results=max(100, max_results))
        used_aql = fallback
        objects_raw = data.get("objectEntries") or data.get("results", {}).get("objectEntries") or data.get("values") or []
    objects = [flatten_assets_object(obj) for obj in objects_raw]
    if used_aql == "objectId > 0" and nl_query.strip():
        terms = [t for t in re.findall(r"[a-zA-Z0-9]{2,}", nl_query.lower()) if t not in {"najdi", "find", "assets"}]
        if terms:
            filtered = []
            for obj in objects:
                text = f"{obj.get('label','')} {obj.get('objectKey','')} {json.dumps(obj.get('attributes', {}), ensure_ascii=False)}".lower()
                score = sum(1 for t in terms if t in text)
                if score > 0:
                    filtered.append((score, obj))
            filtered.sort(key=lambda x: x[0], reverse=True)
            if filtered:
                objects = [o for _, o in filtered][:max_results]
            else:
                objects = objects[:max_results]
        else:
            objects = objects[:max_results]
    total = data.get("total")
    if not isinstance(total, int):
        total = len(objects)
    return AssetsQueryResponse(aql=used_aql, total=total if used_aql != "objectId > 0" else len(objects), objects=objects)


def _extract_issue_key(text: str) -> str | None:
    match = re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", text.upper())
    return match.group(0) if match else None


def _normalize_lookup_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def _extract_person_query(text: str) -> str | None:
    normalized = text.strip()
    if not normalized:
        return None
    match = re.search(r"\b(?:pre|for|user|pouzivatel|pouzivatela)\b[:\s-]*(.+)$", normalized, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip(" .,:;!?()[]{}\"'")
        return candidate if len(candidate) >= 2 else None
    return None


def _resolve_user_for_assets(user_query: str) -> dict[str, Any] | None:
    users = jira.search_users(query=user_query, max_results=20)
    if not users:
        users = jira.list_assignable_users(project_key=settings.jira_project_key, max_results=100)
    if not users:
        return None
    query_n = _normalize_lookup_text(user_query)
    query_tokens = set(re.findall(r"[a-z0-9]{2,}", query_n))
    best_user = users[0]
    best_score = -1
    for u in users:
        dn = str(u.get("displayName") or "")
        em = str(u.get("emailAddress") or "")
        text_n = _normalize_lookup_text(f"{dn} {em}")
        score = 0
        for token in query_tokens:
            if token in text_n:
                score += 1
        if query_n and query_n in text_n:
            score += 5
        if score > best_score:
            best_score = score
            best_user = u
    if query_tokens and best_score <= 0:
        return None
    return best_user


def _current_user_from_payload(payload: ChatRequest) -> dict[str, Any] | None:
    current_user = payload.current_user if isinstance(payload.current_user, dict) else {}
    account_id = str(current_user.get("account_id") or current_user.get("accountId") or "").strip()
    if not account_id:
        return None
    try:
        user = jira.get_user(account_id=account_id)
        if isinstance(user, dict) and user.get("accountId"):
            return user
    except Exception:
        pass
    return {
        "accountId": account_id,
        "displayName": current_user.get("display_name") or current_user.get("displayName") or account_id,
        "emailAddress": current_user.get("email") or current_user.get("emailAddress"),
    }


def _current_user_query(payload: ChatRequest) -> str | None:
    user = _current_user_from_payload(payload)
    if not user:
        return None
    return str(user.get("displayName") or user.get("emailAddress") or user.get("accountId") or "").strip() or None


def _bot_permission_error(
    *,
    action: str,
    current_user: dict[str, Any] | None,
    api_access: dict[str, Any] | Any,
    extra_permissions: list[str] | None = None,
) -> ChatResponse | None:
    if isinstance(api_access, dict) and api_access.get("type") == "admin":
        return None
    if not admin_store.bot_groups_configured():
        return None
    required = list(ACTION_PERMISSION_MAP.get(action, ["tickets.read"]))
    required.extend(extra_permissions or [])
    required = sorted({permission for permission in required if permission})
    account_id = str((current_user or {}).get("accountId") or "").strip()
    if not account_id:
        return ChatResponse(
            action="forbidden",
            message=(
                "Nemam potvrdenu identitu aktualneho Jira pouzivatela, preto tuto akciu nemozem spustit. "
                "Skus to prosim z Jira panelu po obnove stranky, alebo poziadaj admina o kontrolu Forge appky."
            ),
            data={"required_permissions": required},
        )
    user_permissions = admin_store.permissions_for_account(account_id)
    missing = [permission for permission in required if permission not in user_permissions]
    if not missing:
        return None
    return ChatResponse(
        action="forbidden",
        message=(
            "Na tuto akciu nemas v JiraBote nastavene prava. "
            f"Chybajuce prava: {', '.join(missing)}."
        ),
        data={
            "account_id": account_id,
            "required_permissions": required,
            "missing_permissions": missing,
            "user_permissions": sorted(user_permissions),
        },
    )


def _assets_text(obj: dict[str, Any]) -> str:
    attrs = obj.get("attributes") or {}
    return _normalize_lookup_text(
        f"{obj.get('label','')} {obj.get('objectKey','')} {obj.get('objectType','')} {json.dumps(attrs, ensure_ascii=False)}"
    )


def _is_hw_like(obj: dict[str, Any]) -> bool:
    text = _assets_text(obj)
    hw_words = ["laptop", "notebook", "computer", "pc", "hardware", "device", "workstation", "serial"]
    return any(w in text for w in hw_words)


def _extract_person_query_fallback(text: str) -> str | None:
    normalized = text.strip()
    if not normalized:
        return None
    # Example: "aky laptop ma imrich koch"
    match = re.search(r"\b(?:ma|má|has)\s+([a-zA-Z0-9._%+\-@ ]{2,120})$", normalized, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip(" .,:;!?()[]{}\"'")
        return candidate if len(candidate) >= 2 else None
    return None


def _hydrate_assets_objects(workspace_id: str, objects: list[dict[str, Any]], limit: int = 120) -> list[dict[str, Any]]:
    detailed_objects: list[dict[str, Any]] = []
    for base_obj in objects[:limit]:
        object_id_or_key = str(base_obj.get("objectKey") or base_obj.get("id") or "").strip()
        if not object_id_or_key:
            continue
        try:
            raw_detail = jira.get_asset_object(workspace_id=workspace_id, object_id_or_key=object_id_or_key)
            detailed_objects.append(flatten_assets_object(raw_detail))
        except Exception:
            detailed_objects.append(base_obj)
    return detailed_objects


def _assets_for_user(nl_query: str, max_results: int, only_hw: bool) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    person_query = _extract_person_query(nl_query) or _extract_person_query_fallback(nl_query) or nl_query.strip()
    if not person_query:
        return None, []
    matched_user = _resolve_user_for_assets(person_query)
    if not matched_user:
        return None, []

    workspace_id = _require_assets_workspace()
    data = jira.assets_query(workspace_id=workspace_id, aql="objectId > 0", max_results=max(300, max_results * 50))
    objects_raw = data.get("objectEntries") or data.get("results", {}).get("objectEntries") or data.get("values") or []
    objects = [flatten_assets_object(o) for o in objects_raw]
    objects = _hydrate_assets_objects(workspace_id=workspace_id, objects=objects, limit=120)

    display_name = str(matched_user.get("displayName") or "")
    email = str(matched_user.get("emailAddress") or "")
    account_id = str(matched_user.get("accountId") or "")
    user_tokens = [t for t in [display_name, email, account_id, person_query] if t]

    matched: list[dict[str, Any]] = []
    for candidate in objects:
        text = _assets_text(candidate)
        if any(_normalize_lookup_text(token) in text for token in user_tokens):
            matched.append(candidate)

    if only_hw:
        matched = [a for a in matched if _is_hw_like(a)]

    return matched_user, matched[:max_results]


def _stringify_asset_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v is not None)
    if value is None:
        return ""
    return str(value)


def _asset_attr_value(asset: dict[str, Any], names: list[str]) -> str:
    attrs = asset.get("attributes") or {}
    normalized_names = {_normalize_lookup_text(name) for name in names}
    for key, value in attrs.items():
        if _normalize_lookup_text(str(key)) in normalized_names:
            return _stringify_asset_value(value)
    for key, value in attrs.items():
        key_norm = _normalize_lookup_text(str(key))
        if any(name in key_norm for name in normalized_names):
            return _stringify_asset_value(value)
    return ""


def _format_device_name(asset: dict[str, Any]) -> str:
    label = str(asset.get("label") or "").strip()
    object_key = str(asset.get("objectKey") or "").strip()
    object_type = str(asset.get("objectType") or "").strip()
    parts = [p for p in [label, object_key] if p]
    text = " - ".join(parts) if parts else "Nezname zariadenie"
    if object_type:
        text = f"{text} ({object_type})"
    return text


def _extract_extra_text(text: str) -> str:
    match = re.search(
        r"(?:doplnujuci\s+text|doplňujúci\s+text|poznamka|poznámka|text)\s*[:=-]\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _extract_person_after_pre(text: str) -> str | None:
    match = re.search(
        r"\b(?:pre|for)\s+([a-zA-Z0-9._%+\-@ ľščťžýáíéúäôňĽŠČŤŽÝÁÍÉÚÄÔŇ]{2,120})$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    candidate = match.group(1).strip(" .,:;!?()[]{}\"'")
    return candidate if len(candidate) >= 2 else None


def _extract_onboarding_recipient_from_history(text: str) -> str | None:
    normalized = _normalize_lookup_text(text)
    for pattern in [
        r"\bvolne zariadenia pre ([^.?\n]+)",
        r"\bzariadenia pre ([^.?\n]+)",
        r"\bpre ([a-z0-9._%+\-@ ]{2,120})\. ktore chces odovzdat",
        r"\bpre ([a-z0-9._%+\-@ ]{2,120})\. ktore sa odovzdava",
    ]:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" .,:;!?()[]{}\"'")
            if candidate:
                return candidate
    return None


def _recover_onboarding_pending_from_history(message: str, history: list[dict[str, str]] | None) -> ChatResponse | None:
    key_match = re.fullmatch(r"\s*([A-Z]{2,10}-\d+)\s*", message.upper())
    if not key_match or not _assets_enabled():
        return None
    asset_key = key_match.group(1)
    history_items = history or []
    for item in reversed(history_items[-12:]):
        if (item.get("role") or "").lower() not in {"assistant", "bot"}:
            continue
        content = item.get("content") or ""
        content_norm = _normalize_lookup_text(content)
        if not (
            "odovzdat" in content_norm
            or "odovzdava" in content_norm
            or "onboarding" in content_norm
            or "volne zariadenia" in content_norm
        ):
            continue
        recipient = _extract_onboarding_recipient_from_history(content)
        if not recipient:
            continue
        try:
            workspace_id = _require_assets_workspace()
            raw_asset = jira.get_asset_object(workspace_id=workspace_id, object_id_or_key=asset_key)
            asset = flatten_assets_object(raw_asset)
        except Exception:
            return None
        return _complete_onboarding_asset_selection(
            {
                "type": "onboarding_select_asset",
                "recipient": recipient,
                "extra_text": "",
                "assets": [asset],
            },
            asset_key,
        )
    return None


def _extract_offboarding_person(text: str, parsed: dict[str, Any] | None = None) -> str | None:
    email = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text)
    if email:
        return email.group(1)
    cleaned = re.sub(
        r"(?:doplnujuci\s+text|doplňujúci\s+text|poznamka|poznámka|text)\s*[:=-].+$",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    pre_match = re.search(r"\bpre\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if pre_match:
        cleaned = pre_match.group(1)
    cleaned = re.sub(
        r"\b(?:vyrob|vytvor|sprav|urob|mi|prosim|prosím|offboardingovat|offboardovat|offboarding|offboard|ofboarding|ofbord|offbord|offbordnigovat|ofbordnigovat|offbordnig|offboardni|offboarduj|ukoncenie|ukončenie|odovzdavaci|odovzdávací|preberaci|preberací|protokol|vratenie|vrátenie|zariadenia|zariadeni|zamestnanca|pouzivatela|používateľa|pre|for)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;!?()[]{}\"'")
    filler_words = {"niekoho", "someone", "tak", "ok", "ano", "áno", "jasne", "dobre", "prosim", "prosím"}
    if not cleaned or _normalize_lookup_text(cleaned) in filler_words:
        return None
    return cleaned if len(cleaned) >= 2 else None


def _extract_offboarding_checklist_person(text: str, parsed: dict[str, Any] | None = None) -> str | None:
    candidate = _extract_offboarding_person(text, parsed)
    if not candidate:
        candidate = _extract_person_after_pre(text)
    if not candidate:
        parsed_query = (parsed or {}).get("query")
        candidate = parsed_query if isinstance(parsed_query, str) else None
    if not candidate:
        return None
    candidate = re.split(
        r"\b(?:podla|podľa|podla\s+pristupov|podľa\s+prístupov|pristupov|prístupov|access|jira|ticket|tiket)\b",
        candidate,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    candidate = re.sub(
        r"\b(?:offboarding|offboard|checklist|zoznam|pristupov|prístupov|pristupy|prístupy|pre|for)\b",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;!?()[]{}\"'")
    return candidate if len(candidate) >= 2 else None


def _build_offboarding_document_context(
    user_identifier: str,
    extra_text: str | None,
    selected_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    matched_user = _resolve_user_for_assets(user_identifier)
    assets: list[dict[str, Any]] = []
    if selected_assets is not None:
        assets = selected_assets
    elif _assets_enabled():
        try:
            asset_user, user_assets = _assets_for_user(
                (matched_user or {}).get("displayName") or user_identifier,
                max_results=25,
                only_hw=True,
            )
            if asset_user:
                matched_user = asset_user
            assets = user_assets
        except Exception:
            assets = []

    employee_name = str((matched_user or {}).get("displayName") or user_identifier).strip()
    employee_email = str((matched_user or {}).get("emailAddress") or "").strip()
    device_lines = [_format_device_name(asset) for asset in assets]
    serial_lines = []
    for asset in assets:
        serial = _asset_attr_value(
            asset,
            [
                "Serial Number",
                "Serial",
                "Serial number",
                "S/N",
                "SN",
                "Seriove cislo",
                "Sériové číslo",
                "Seriove c.",
            ],
        )
        serial_lines.append(serial or f"{asset.get('objectKey') or asset.get('label')}: bez serioveho cisla")

    values = {
        "employee_name": employee_name,
        "device_name": "\n".join(device_lines) if device_lines else "Bez priradeneho HW assetu",
        "serial_number": "\n".join(serial_lines) if serial_lines else "Bez serioveho cisla",
        "extra_text": (extra_text or "").strip(),
    }
    return {
        "user": {
            "display_name": employee_name,
            "email": employee_email,
            "account_id": (matched_user or {}).get("accountId"),
        },
        "assets": assets,
        "values": values,
    }


def _generate_offboarding_document(
    *,
    user_identifier: str,
    extra_text: str | None = None,
    template_id: str | None = None,
    selected_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = _build_offboarding_document_context(user_identifier, extra_text, selected_assets=selected_assets)
    template = template_store.get(template_id) if template_id else template_store.active()
    if template_id and not template:
        raise HTTPException(status_code=404, detail="Offboarding template not found.")
    safe_user = re.sub(r"[^a-zA-Z0-9_-]+", "-", context["values"]["employee_name"]).strip("-") or "user"
    file_stem = f"offboarding-{safe_user}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    template_error = None
    try:
        result = render_offboarding_document(
            template_store=template_store,
            template=template,
            output_dir=GENERATED_DIR / "offboarding",
            values=context["values"],
            file_stem=file_stem,
        )
    except Exception as exc:
        if not template:
            raise
        template_error = str(exc)
        result = render_offboarding_document(
            template_store=template_store,
            template=None,
            output_dir=GENERATED_DIR / "offboarding",
            values=context["values"],
            file_stem=f"{file_stem}-fallback",
        )
    document_url = _signed_download_url("offboarding", result["file_name"])
    return {
        "document_url": document_url,
        "file_name": result["file_name"],
        "format": result["format"],
        "template": {"id": template.get("id"), "name": template.get("name")} if template else None,
        "template_error": template_error,
        **context,
    }


def _generate_onboarding_document(
    *,
    user_identifier: str,
    selected_assets: list[dict[str, Any]],
    extra_text: str | None = None,
    template_id: str | None = None,
) -> dict[str, Any]:
    context = _build_offboarding_document_context(user_identifier, extra_text, selected_assets=selected_assets)
    template = onboarding_template_store.get(template_id) if template_id else onboarding_template_store.active()
    if template_id and not template:
        raise HTTPException(status_code=404, detail="Onboarding template not found.")
    safe_user = re.sub(r"[^a-zA-Z0-9_-]+", "-", context["values"]["employee_name"]).strip("-") or "user"
    file_stem = f"onboarding-{safe_user}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    template_error = None
    try:
        result = render_offboarding_document(
            template_store=onboarding_template_store,
            template=template,
            output_dir=GENERATED_DIR / "onboarding",
            values=context["values"],
            file_stem=file_stem,
        )
    except Exception as exc:
        if not template:
            raise
        template_error = str(exc)
        result = render_offboarding_document(
            template_store=onboarding_template_store,
            template=None,
            output_dir=GENERATED_DIR / "onboarding",
            values=context["values"],
            file_stem=f"{file_stem}-fallback",
        )
    document_url = _signed_download_url("onboarding", result["file_name"])
    return {
        "document_url": document_url,
        "file_name": result["file_name"],
        "format": result["format"],
        "template": {"id": template.get("id"), "name": template.get("name")} if template else None,
        "template_error": template_error,
        **context,
    }


def _asset_identity(asset: dict[str, Any]) -> str:
    return str(asset.get("objectKey") or asset.get("id") or asset.get("label") or "").strip()


def _asset_selection_text(asset: dict[str, Any]) -> str:
    return _normalize_lookup_text(
        f"{asset.get('objectKey','')} {asset.get('label','')} {asset.get('objectType','')} {_format_device_name(asset)}"
    )


def _select_assets_from_message(message: str, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = message.strip()
    text_norm = _normalize_lookup_text(text)
    if not text_norm or not assets:
        return []
    if re.search(r"\b(vsetky|všetky|all|oba|obidva|vsetko|všetko)\b", text_norm):
        return assets

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    explicit_keys = {key.upper() for key in re.findall(r"\b[A-Z]{2,10}-\d+\b", text.upper())}
    if explicit_keys:
        for asset in assets:
            identity = _asset_identity(asset)
            if identity.upper() in explicit_keys and identity not in seen:
                selected.append(asset)
                seen.add(identity)
        return selected

    for number in re.findall(r"\b\d+\b", text_norm):
        index = int(number) - 1
        if 0 <= index < len(assets):
            identity = _asset_identity(assets[index])
            if identity not in seen:
                selected.append(assets[index])
                seen.add(identity)

    for asset in assets:
        identity = _asset_identity(asset)
        if (
            identity
            and re.search(rf"(?<![A-Za-z0-9]){re.escape(identity)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE)
            and identity not in seen
        ):
            selected.append(asset)
            seen.add(identity)
            continue
        asset_text = _asset_selection_text(asset)
        if len(text_norm) >= 3 and asset_text and (text_norm in asset_text or asset_text in text_norm) and identity not in seen:
            selected.append(asset)
            seen.add(identity)

    return selected


def _format_asset_choices(assets: list[dict[str, Any]]) -> str:
    lines = []
    for index, asset in enumerate(assets, start=1):
        serial = _asset_attr_value(
            asset,
            [
                "Serial Number",
                "Serial",
                "Serial number",
                "S/N",
                "SN",
                "Seriove cislo",
                "Sériové číslo",
                "Seriove c.",
            ],
        )
        suffixes = []
        if serial:
            suffixes.append(f"SN: {serial}")
        assigned = _asset_assigned_value(asset)
        if assigned:
            suffixes.append(f"priradene: {assigned}")
        suffix = f" ({', '.join(suffixes)})" if suffixes else ""
        lines.append(f"{index}) {_format_device_name(asset)}{suffix}")
    return "\n".join(lines)


def _offboarding_selection_prompt(user: dict[str, Any], assets: list[dict[str, Any]], extra_text: str = "") -> ChatResponse:
    display_name = user.get("displayName") or user.get("display_name") or "používateľ"
    message = (
        f"Našiel som tieto zariadenia pre {display_name}. Ktoré sa vracia firme?\n"
        f"{_format_asset_choices(assets)}\n\n"
        "Odpovedz číslom, Assets kľúčom (napr. CDX-4), názvom zariadenia alebo napíš \"všetky\"."
    )
    return ChatResponse(
        action="offboarding_select_asset",
        message=message,
        data=_pending_data(
            {
                "type": "offboarding_select_asset",
                "user_identifier": display_name,
                "extra_text": extra_text,
                "assets": assets,
            },
            total=len(assets),
            objects=assets,
        ),
    )


def _asset_assigned_value(asset: dict[str, Any]) -> str:
    return _asset_attr_value(
        asset,
        [
            "Assigned user",
            "Assigned to",
            "Assignee",
            "Owner",
            "User",
            "Pouzivatel",
            "Používateľ",
            "Drzitel",
            "Držiteľ",
        ],
    ).strip()


def _assets_available_for_onboarding(max_results: int = 25) -> list[dict[str, Any]]:
    objects = _assets_hw_inventory_for_onboarding(max_results=max_results)
    available = [obj for obj in objects if not _asset_assigned_value(obj)]
    return available[:max_results]


def _assets_hw_inventory_for_onboarding(max_results: int = 25) -> list[dict[str, Any]]:
    workspace_id = _require_assets_workspace()
    data = jira.assets_query(workspace_id=workspace_id, aql="objectId > 0", max_results=max(300, max_results * 50))
    objects_raw = data.get("objectEntries") or data.get("results", {}).get("objectEntries") or data.get("values") or []
    objects = [flatten_assets_object(o) for o in objects_raw]
    objects = _hydrate_assets_objects(workspace_id=workspace_id, objects=objects, limit=160)
    return [obj for obj in objects if _is_hw_like(obj)][:max_results]


def _extract_onboarding_recipient(text: str, parsed: dict[str, Any] | None = None) -> str | None:
    email = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text)
    if email:
        return email.group(1)
    for pattern in [
        r"\b(?:pre|for|na|dostane|pridel(?:it|iť)?|prirad(?:it|iť)?|zamestnancovi|pouzivatelovi|používateľovi)\b[:\s-]+(.+)$",
        r"\b(?:meno|recipient|user|pouzivatel|používateľ)\b[:\s-]+(.+)$",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" .,:;!?()[]{}\"'")
            candidate = re.sub(
                r"\b(?:notebook|laptop|pc|pocitac|počítač|zariadenie|odovzdavaci|odovzdávací|protokol|onboarding|vyrob|vytvor|sprav|urob|mi)\b",
                " ",
                candidate,
                flags=re.IGNORECASE,
            )
            candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;!?()[]{}\"'")
            if len(candidate) >= 2:
                return candidate
    parsed_query = (parsed or {}).get("query")
    if isinstance(parsed_query, str) and parsed_query.strip():
        return None
    return None


def _onboarding_selection_prompt(
    assets: list[dict[str, Any]],
    recipient: str | None,
    extra_text: str = "",
    *,
    only_available: bool = True,
) -> ChatResponse:
    who = f" pre {recipient}" if recipient else ""
    availability_text = "voľné zariadenia" if only_available else "zariadenia"
    message = (
        f"Našiel som tieto {availability_text}{who}. Ktoré chceš odovzdať?\n"
        f"{_format_asset_choices(assets)}\n\n"
        "Odpovedz číslom, Assets kľúčom alebo názvom zariadenia."
    )
    if not only_available:
        message = (
            "Nenašiel som žiadne úplne voľné HW zariadenie, preto ukazujem aj aktuálne priradené kusy. "
            "Vyber prepise priradenie v Assets.\n\n"
            + message
        )
    if not recipient:
        message += " Potom mi napíš aj meno človeka, ktorý ho dostane."
    return ChatResponse(
        action="onboarding_select_asset",
        message=message,
        data=_pending_data(
            {
                "type": "onboarding_select_asset",
                "recipient": recipient or "",
                "extra_text": extra_text,
                "assets": assets,
            },
            total=len(assets),
            objects=assets,
        ),
    )


ASSIGNMENT_ATTRIBUTE_NAMES = [
    "assigned user",
    "assigned to",
    "assignee",
    "owner",
    "user",
    "pouzivatel",
    "používateľ",
    "drzitel",
    "držiteľ",
]


def _assignment_attr_id(attr: dict[str, Any]) -> str:
    ota = attr.get("objectTypeAttribute") or attr
    return str(attr.get("objectTypeAttributeId") or ota.get("id") or attr.get("id") or "").strip()


def _assignment_attr_name(attr: dict[str, Any]) -> str:
    ota = attr.get("objectTypeAttribute") or attr
    return str(ota.get("name") or attr.get("name") or "").strip()


def _assignment_attr_default_type(attr: dict[str, Any]) -> str:
    ota = attr.get("objectTypeAttribute") or attr
    default_type = ota.get("defaultType") or {}
    return _normalize_lookup_text(str(default_type.get("name") or ota.get("typeValue") or ""))


def _wrap_schema_assignment_attr(attr: dict[str, Any]) -> dict[str, Any]:
    return {
        "objectTypeAttribute": attr,
        "objectTypeAttributeId": attr.get("id"),
        "objectAttributeValues": [],
    }


def _find_assignment_attribute(
    raw_asset: dict[str, Any],
    user_hint: str | None = None,
    schema_attributes: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    normalized_user = _normalize_lookup_text(user_hint or "")
    scored: list[tuple[int, dict[str, Any]]] = []
    candidates = list(raw_asset.get("attributes") or [])
    candidates.extend(_wrap_schema_assignment_attr(attr) for attr in schema_attributes or [])
    for attr in candidates:
        ota = attr.get("objectTypeAttribute") or {}
        if ota.get("editable") is False:
            continue
        if int(ota.get("minimumCardinality") or 0) > 0:
            continue
        name_norm = _normalize_lookup_text(str(ota.get("name") or ""))
        values_text = _normalize_lookup_text(json.dumps(attr.get("objectAttributeValues") or [], ensure_ascii=False))
        score = 0
        for index, preferred in enumerate(ASSIGNMENT_ATTRIBUTE_NAMES):
            if preferred in name_norm:
                score += 100 - index
        if normalized_user and normalized_user in values_text:
            score += 30
        if score > 0:
            scored.append((score, attr))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored else None


def _get_or_create_assignment_attribute(
    *,
    workspace_id: str,
    object_type_id: str,
    raw_asset: dict[str, Any],
    user_hint: str | None = None,
) -> dict[str, Any]:
    assignment_attr = _find_assignment_attribute(raw_asset, user_hint=user_hint)
    if assignment_attr:
        return assignment_attr

    schema_attrs = jira.list_object_type_attributes(workspace_id=workspace_id, object_type_id=object_type_id)
    assignment_attr = _find_assignment_attribute(raw_asset, user_hint=user_hint, schema_attributes=schema_attrs)
    if assignment_attr:
        return assignment_attr

    created = jira.create_object_type_attribute(
        workspace_id=workspace_id,
        object_type_id=object_type_id,
        name="Assigned user",
        type_id=0,
        default_type_id=0,
        minimum_cardinality=0,
        maximum_cardinality=1,
    )
    return _wrap_schema_assignment_attr(created)


def _assignment_value_for_user(attr: dict[str, Any], user: dict[str, Any]) -> str:
    if "user" in _assignment_attr_default_type(attr):
        value = str(user.get("accountId") or "").strip()
        if value:
            return value
    display_name = str(user.get("displayName") or "").strip()
    email = str(user.get("emailAddress") or "").strip()
    if display_name and email:
        return f"{display_name} <{email}>"
    return display_name or email or str(user.get("accountId") or "").strip()


def _unassign_asset_from_user(asset: dict[str, Any], user_hint: str | None = None) -> dict[str, Any]:
    workspace_id = _require_assets_workspace()
    object_id_or_key = _asset_identity(asset)
    if not object_id_or_key:
        raise RuntimeError("Assets object has no key/id.")
    raw_asset = jira.get_asset_object(workspace_id=workspace_id, object_id_or_key=object_id_or_key)
    object_type_id = str((raw_asset.get("objectType") or {}).get("id") or "")
    if not object_type_id:
        raise RuntimeError(f"Assets object {object_id_or_key} has no objectTypeId.")
    assignment_attr = _find_assignment_attribute(raw_asset, user_hint=user_hint)
    if not assignment_attr:
        raise RuntimeError(f"No editable optional assignment attribute found on {object_id_or_key}.")
    attr_id = _assignment_attr_id(assignment_attr)
    if not attr_id:
        raise RuntimeError(f"Assignment attribute on {object_id_or_key} has no id.")
    updated = jira.update_asset_object(
        workspace_id=workspace_id,
        object_id_or_key=str(raw_asset.get("id") or object_id_or_key),
        object_type_id=object_type_id,
        attributes=[
            {
                "objectTypeAttributeId": attr_id,
                "objectAttributeValues": [],
            }
        ],
    )
    return {
        "object_key": raw_asset.get("objectKey") or object_id_or_key,
        "label": raw_asset.get("label"),
        "cleared_attribute": _assignment_attr_name(assignment_attr) or attr_id,
        "updated": flatten_assets_object(updated),
    }


def _assign_asset_to_user(asset: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    workspace_id = _require_assets_workspace()
    object_id_or_key = _asset_identity(asset)
    if not object_id_or_key:
        raise RuntimeError("Assets object has no key/id.")
    raw_asset = jira.get_asset_object(workspace_id=workspace_id, object_id_or_key=object_id_or_key)
    object_type_id = str((raw_asset.get("objectType") or {}).get("id") or "")
    if not object_type_id:
        raise RuntimeError(f"Assets object {object_id_or_key} has no objectTypeId.")
    assignment_attr = _get_or_create_assignment_attribute(
        workspace_id=workspace_id,
        object_type_id=object_type_id,
        raw_asset=raw_asset,
    )
    attr_id = _assignment_attr_id(assignment_attr)
    if not attr_id:
        raise RuntimeError(f"Assignment attribute on {object_id_or_key} has no id.")
    value = _assignment_value_for_user(assignment_attr, user)
    if not value:
        raise RuntimeError("Recipient user has no usable display value.")
    updated = jira.update_asset_object(
        workspace_id=workspace_id,
        object_id_or_key=str(raw_asset.get("id") or object_id_or_key),
        object_type_id=object_type_id,
        attributes=[
            {
                "objectTypeAttributeId": attr_id,
                "objectAttributeValues": [{"value": value}],
            }
        ],
    )
    return {
        "object_key": raw_asset.get("objectKey") or object_id_or_key,
        "label": raw_asset.get("label"),
        "assigned_attribute": _assignment_attr_name(assignment_attr) or attr_id,
        "assigned_value": value,
        "updated": flatten_assets_object(updated),
    }


def _complete_offboarding_asset_selection(pending: dict[str, Any], message: str) -> ChatResponse:
    assets = pending.get("assets") if isinstance(pending.get("assets"), list) else []
    selected_assets = _select_assets_from_message(message, assets)
    if not selected_assets:
        return ChatResponse(
            action="offboarding_select_asset",
            message=(
                "Neviem jednoznacne vybrat zariadenie. "
                "Napis prosim cislo zo zoznamu, Assets kluc ako CDX-4, alebo \"vsetky\".\n"
                f"{_format_asset_choices(assets)}"
            ),
            data=_pending_data(pending, total=len(assets), objects=assets),
        )

    user_identifier = str(pending.get("user_identifier") or "").strip()
    extra_text = str(pending.get("extra_text") or "").strip()
    generated = _generate_offboarding_document(
        user_identifier=user_identifier,
        extra_text=extra_text,
        selected_assets=selected_assets,
    )
    unassign_results = []
    unassign_errors = []
    for asset in selected_assets:
        try:
            unassign_results.append(_unassign_asset_from_user(asset, user_hint=generated["user"]["display_name"]))
        except Exception as exc:  # noqa: BLE001
            unassign_errors.append({"asset": _format_device_name(asset), "error": str(exc)})
    generated["selected_assets"] = selected_assets
    generated["unassigned_assets"] = unassign_results
    generated["unassign_errors"] = unassign_errors
    suffix = ""
    if unassign_results:
        suffix += f" Odassignoval som {len(unassign_results)} zariadeni v Assets."
    if unassign_errors:
        suffix += f" Pozor: {len(unassign_errors)} zariadeni sa nepodarilo odassignovat."
    return ChatResponse(
        action="offboarding",
        message=f"Offboarding dokument je pripraveny pre {generated['user']['display_name']}.{suffix}",
        data=generated,
    )


def _complete_onboarding_asset_selection(pending: dict[str, Any], message: str) -> ChatResponse:
    assets = pending.get("assets") if isinstance(pending.get("assets"), list) else []
    selected_assets = pending.get("selected_assets") if isinstance(pending.get("selected_assets"), list) else []
    if not selected_assets:
        selected_assets = _select_assets_from_message(message, assets)
    recipient = str(pending.get("recipient") or "").strip() or _extract_onboarding_recipient(message)
    extra_text = str(pending.get("extra_text") or "").strip() or _extract_extra_text(message)

    if not selected_assets:
        return ChatResponse(
            action="onboarding_select_asset",
            message=(
                "Neviem jednoznacne vybrat zariadenie. "
                "Napis prosim cislo zo zoznamu alebo Assets kluc ako CDX-4.\n"
                f"{_format_asset_choices(assets)}"
            ),
            data=_pending_data(pending, total=len(assets), objects=assets),
        )
    if not recipient:
        next_pending = dict(pending)
        next_pending["type"] = "onboarding_select_recipient"
        next_pending["selected_assets"] = selected_assets
        return ChatResponse(
            action="onboarding_select_recipient",
            message="Komu sa ma zariadenie odovzdat? Napis meno alebo email pouzivatela.",
            data=_pending_data(next_pending, selected_assets=selected_assets),
        )

    user = _resolve_user_for_assets(recipient)
    if not user:
        return ChatResponse(
            action="onboarding_select_recipient",
            message=f"Pouzivatela '{recipient}' som nenasiel. Napis prosim presnejsie meno alebo email.",
            data=_pending_data(
                {
                    "type": "onboarding_select_recipient",
                    "selected_assets": selected_assets,
                    "extra_text": extra_text,
                },
                selected_assets=selected_assets,
            ),
        )

    generated = _generate_onboarding_document(
        user_identifier=user.get("displayName") or recipient,
        selected_assets=selected_assets,
        extra_text=extra_text,
    )
    assign_results = []
    assign_errors = []
    for asset in selected_assets:
        try:
            assign_results.append(_assign_asset_to_user(asset, user))
        except Exception as exc:  # noqa: BLE001
            assign_errors.append({"asset": _format_device_name(asset), "error": str(exc)})
    generated["selected_assets"] = selected_assets
    generated["assigned_assets"] = assign_results
    generated["assign_errors"] = assign_errors
    suffix = ""
    if assign_results:
        suffix += f" Priradil som {len(assign_results)} zariadeni v Assets."
    if assign_errors:
        suffix += f" Pozor: {len(assign_errors)} zariadeni sa nepodarilo priradit."
    return ChatResponse(
        action="onboarding",
        message=f"Onboarding dokument je pripraveny pre {generated['user']['display_name']}.{suffix}",
        data=generated,
    )


def _friendly_error_message(error: Exception | str) -> str:
    text = str(error)
    lowered = text.lower()
    if "access to assets api was denied" in lowered or ("status_code" in lowered and "403" in lowered and "assets" in lowered):
        return (
            "Jira API token funguje, ale ucet pouzity botom nema povoleny pristup do Jira Assets API. "
            "Treba mu v Atlassian/Jira Service Management pridat Assets prava na danu schemu, napriklad Object Schema User/Manager "
            "alebo Assets administrator podla toho, ci ma len citat alebo aj priradovat zariadenia."
        )
    if "jql" in lowered or "reserved word" in lowered or "vyhraden" in lowered:
        return (
            "Tomuto som nerozumel ako Jira vyhľadávaniu a nechcem ti vracať technickú chybu. "
            "Skús to prosím napísať prirodzenejšie, napríklad: „daj mi zoznam userov“, "
            "„aké máme tickety“ alebo „nájdi otvorené tickety o notebooku“."
        )
    if "no jira user found" in lowered or "pouzivatela" in lowered or "user found" in lowered:
        return "Používateľa som nenašiel. Skús prosím celé meno alebo email."
    if "assets" in lowered:
        return "V Assets sa niečo nepodarilo načítať alebo upraviť. Skús prosím presnejší názov zariadenia alebo používateľa."
    return "Niečo sa nepodarilo, ale nebudem ťa trápiť technickou chybou. Skús to prosím povedať ešte raz trochu konkrétnejšie."


def _extract_issue_key_from_history(history: list[dict[str, str]] | None) -> str | None:
    if not history:
        return None
    for item in reversed(history):
        key = _extract_issue_key(item.get("content") or "")
        if key:
            return key
    return None


def _resolve_assignee_query(message: str, parsed: dict[str, Any]) -> str | None:
    assignee = parsed.get("assignee")
    if isinstance(assignee, str) and assignee.strip():
        return assignee.strip()
    m = re.search(r"(?:to|komu|na)\s+([a-zA-Z0-9._%+\-@ ]{2,80})$", message.strip(), flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _assign_ticket(issue_key: str, assignee_query: str) -> AssignTicketResponse:
    candidates = jira.search_users(query=assignee_query, max_results=10)
    if not candidates:
        raise HTTPException(status_code=404, detail=f"No Jira user found for '{assignee_query}'.")

    selected = None
    q = assignee_query.lower()
    for user in candidates:
        dn = str(user.get("displayName") or "").lower()
        em = str(user.get("emailAddress") or "").lower()
        if q in dn or q in em:
            selected = user
            break
    if selected is None:
        selected = candidates[0]

    account_id = selected.get("accountId")
    if not account_id:
        raise HTTPException(status_code=400, detail="Selected user has no accountId.")
    jira.assign_issue(issue_key=issue_key, account_id=account_id)
    return AssignTicketResponse(
        issue_key=issue_key,
        assignee_account_id=account_id,
        assignee_display_name=selected.get("displayName") or "Unknown",
    )


def _resolve_assignee_user(assignee_query: str) -> dict[str, Any]:
    candidates = jira.search_users(query=assignee_query, max_results=10)
    if not candidates:
        raise HTTPException(status_code=404, detail=f"No Jira user found for '{assignee_query}'.")
    selected = None
    q = assignee_query.lower()
    for user in candidates:
        dn = str(user.get("displayName") or "").lower()
        em = str(user.get("emailAddress") or "").lower()
        if q in dn or q in em:
            selected = user
            break
    return selected or candidates[0]


def _assign_all_unassigned(assignee_query: str, max_results: int = 200) -> dict[str, Any]:
    user = _resolve_assignee_user(assignee_query)
    account_id = user.get("accountId")
    if not account_id:
        raise HTTPException(status_code=400, detail="Selected user has no accountId.")

    jql = f"project = {settings.jira_project_key} AND assignee IS EMPTY ORDER BY updated DESC"
    result = jira.search_with_fields(
        jql=jql,
        fields=["summary", "assignee"],
        max_results=max_results,
    )
    keys = [i.get("key") for i in result.get("issues", []) if i.get("key")]
    assigned_keys: list[str] = []
    for key in keys:
        jira.assign_issue(issue_key=key, account_id=account_id)
        assigned_keys.append(key)
    return {
        "assignee_display_name": user.get("displayName") or "Unknown",
        "assignee_account_id": account_id,
        "assigned_count": len(assigned_keys),
        "assigned_keys": assigned_keys,
    }


def _close_issue(issue_key: str) -> dict[str, Any]:
    issue = jira.get_issue(issue_key)
    fields = issue.get("fields", {})
    status = fields.get("status") or {}
    status_name = status.get("name")
    status_cat = (status.get("statusCategory") or {}).get("key")
    if status_cat == "done":
        return {"issue_key": issue_key, "status": status_name, "changed": False}

    transitions = jira.get_transitions(issue_key=issue_key)
    if not transitions:
        raise HTTPException(status_code=400, detail=f"No transitions available for {issue_key}.")

    preferred = None
    for t in transitions:
        to = t.get("to") or {}
        to_cat = (to.get("statusCategory") or {}).get("key")
        to_name = str(to.get("name") or "").lower()
        if to_cat == "done":
            preferred = t
            if to_name in {"done", "closed", "resolved"}:
                break
    if preferred is None:
        for t in transitions:
            name = str(t.get("name") or "").lower()
            if any(k in name for k in ["close", "resolve", "done", "uzav", "zavri"]):
                preferred = t
                break
    if preferred is None:
        available = [str(t.get("name") or t.get("id")) for t in transitions]
        raise HTTPException(status_code=400, detail=f"No close-like transition found. Available: {available}")

    transition_id = str(preferred.get("id"))
    jira.transition_issue(issue_key=issue_key, transition_id=transition_id)
    refreshed = jira.get_issue(issue_key)
    new_status = ((refreshed.get("fields") or {}).get("status") or {}).get("name")
    return {"issue_key": issue_key, "status": new_status, "changed": True}


def _load_service_catalog() -> list[dict[str, Any]]:
    catalog_path = BASE_DIR.parent / "service_catalog.json"
    if not catalog_path.exists():
        return []
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("name")]
    return []


@app.post("/tickets/create", response_model=CreateTicketResponse)
def create_ticket(payload: CreateTicketRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> CreateTicketResponse:
    try:
        created = jira.create_issue(
            project_key=payload.project_key or settings.jira_project_key,
            issue_type=payload.issue_type or settings.jira_default_issue_type,
            summary=payload.summary,
            description=payload.description,
        )
        return CreateTicketResponse(**created)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tickets/summarize", response_model=SummarizeTicketResponse)
def summarize_ticket(payload: SummarizeTicketRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> SummarizeTicketResponse:
    try:
        issue = jira.get_issue(payload.issue_key)
        comments = jira.get_comments(payload.issue_key, max_results=payload.max_comments)
        input_payload: dict[str, Any] = {
            "issue": issue,
            "comments": comments.get("comments", []),
        }
        summary = ai.summarize_issue(input_payload)
        return SummarizeTicketResponse(issue_key=payload.issue_key, summary=summary)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tickets/search", response_model=SearchTicketsResponse)
def search_tickets(payload: SearchTicketsRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> SearchTicketsResponse:
    try:
        return _search_logic(payload.query, payload.max_results)
    except JQLValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Generated JQL rejected: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tickets/assign", response_model=AssignTicketResponse)
def assign_ticket(payload: AssignTicketRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> AssignTicketResponse:
    try:
        return _assign_ticket(payload.issue_key, payload.assignee_query)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tickets/similar", response_model=SimilarTicketsResponse)
def similar_tickets(payload: SimilarTicketsRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> SimilarTicketsResponse:
    try:
        if not payload.issue_key and not payload.text:
            raise HTTPException(status_code=400, detail="Provide issue_key or text.")

        source_text = payload.text or ""
        source_label = "text"
        if payload.issue_key:
            issue = jira.get_issue(payload.issue_key)
            source_text = _issue_text(issue.get("fields", {}))
            source_label = payload.issue_key

        jql = f"project = {settings.jira_project_key} ORDER BY updated DESC"
        result = jira.search_with_fields(
            jql=jql,
            fields=["summary", "description", "status", "issuetype", "updated", "created"],
            max_results=payload.max_candidates,
        )
        rows: list[dict[str, Any]] = []
        for issue in result.get("issues", []):
            key = issue.get("key")
            if payload.issue_key and key == payload.issue_key:
                continue
            fields = issue.get("fields", {})
            text = _issue_text(fields)
            score = cosine_similarity(source_text, text)
            if score <= 0:
                continue
            rows.append(
                {
                    "key": key,
                    "summary": fields.get("summary"),
                    "status": (fields.get("status") or {}).get("name"),
                    "issue_type": (fields.get("issuetype") or {}).get("name"),
                    "score": round(score, 4),
                    "overlap_keywords": overlap_keywords(source_text, text),
                    "updated": fields.get("updated"),
                }
            )
        rows.sort(key=lambda r: r["score"], reverse=True)
        return SimilarTicketsResponse(source=source_label, top_k=payload.top_k, items=rows[: payload.top_k])
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/inc/classify-service", response_model=ClassifyIncidentResponse)
def classify_incident_service(payload: ClassifyIncidentRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> ClassifyIncidentResponse:
    try:
        if not payload.issue_key and not payload.text:
            raise HTTPException(status_code=400, detail="Provide issue_key or text.")
        catalog = _load_service_catalog()
        if not catalog:
            raise HTTPException(
                status_code=400,
                detail="service_catalog.json not found. Create it in project root (array of {name, keywords}).",
            )

        source_text = payload.text or ""
        if payload.issue_key:
            issue = jira.get_issue(payload.issue_key)
            source_text = _issue_text(issue.get("fields", {}))

        ranked: list[dict[str, Any]] = []
        for service in catalog:
            name = str(service.get("name", ""))
            keywords = service.get("keywords") or []
            keyword_text = " ".join(str(k) for k in keywords)
            score = cosine_similarity(source_text, f"{name} {keyword_text}")
            ranked.append({"service": name, "score": round(score, 4), "keywords": keywords[:8]})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        top = ranked[: payload.top_k]
        best = top[0] if top else {"service": "unknown", "score": 0.0}
        return ClassifyIncidentResponse(
            predicted_service=best["service"],
            confidence=best["score"],
            alternatives=top,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/inc/correlate-changes", response_model=CorrelateChangesResponse)
def correlate_changes(payload: CorrelateChangesRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> CorrelateChangesResponse:
    try:
        if not payload.incident_issue_key and not payload.incident_text:
            raise HTTPException(status_code=400, detail="Provide incident_issue_key or incident_text.")

        incident_text = payload.incident_text or ""
        source = "text"
        if payload.incident_issue_key:
            inc = jira.get_issue(payload.incident_issue_key)
            incident_text = _issue_text(inc.get("fields", {}))
            source = payload.incident_issue_key

        lookback = payload.lookback_days
        project = settings.jira_project_key
        jql = (
            f"project = {project} AND updated >= -{lookback}d "
            "AND (summary ~ \"deploy\" OR summary ~ \"patch\" OR description ~ \"deploy\" OR description ~ \"patch\") "
            "ORDER BY updated DESC"
        )
        result = jira.search_with_fields(
            jql=jql,
            fields=["summary", "description", "status", "issuetype", "updated", "created"],
            max_results=200,
        )
        links: list[dict[str, Any]] = []
        for issue in result.get("issues", []):
            fields = issue.get("fields", {})
            change_text = _issue_text(fields)
            score = cosine_similarity(incident_text, change_text)
            if score < 0.05:
                continue
            links.append(
                {
                    "key": issue.get("key"),
                    "summary": fields.get("summary"),
                    "issue_type": (fields.get("issuetype") or {}).get("name"),
                    "status": (fields.get("status") or {}).get("name"),
                    "updated": fields.get("updated"),
                    "similarity": round(score, 4),
                    "overlap_keywords": overlap_keywords(incident_text, change_text),
                }
            )
        links.sort(key=lambda x: x["similarity"], reverse=True)
        return CorrelateChangesResponse(
            incident_source=source,
            lookback_days=lookback,
            links=links[: payload.top_k],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/assets/search", response_model=AssetsQueryResponse)
def assets_search(payload: AssetsQueryRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> AssetsQueryResponse:
    try:
        return _assets_search_from_nl(payload.query, payload.max_results)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/offboarding/checklist", response_model=OffboardingChecklistResponse)
def offboarding_checklist(payload: OffboardingChecklistRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> OffboardingChecklistResponse:
    try:
        user_text = payload.user_identifier.replace('"', "")
        jql = (
            f"project = {settings.jira_project_key} "
            f"AND updated >= -{payload.lookback_days}d "
            f"AND text ~ \"{user_text}\" "
            "AND (text ~ \"access\" OR text ~ \"account\" OR text ~ \"permission\" OR text ~ \"vpn\" OR text ~ \"mail\") "
            "ORDER BY updated DESC"
        )
        result = jira.search_with_fields(
            jql=jql,
            fields=["summary", "status", "assignee", "updated", "created", "issuetype"],
            max_results=payload.max_results,
        )
        issues = []
        for issue in result.get("issues", []):
            fields = issue.get("fields", {})
            issues.append(
                {
                    "key": issue.get("key"),
                    "summary": fields.get("summary"),
                    "status": (fields.get("status") or {}).get("name"),
                    "assignee": (fields.get("assignee") or {}).get("displayName"),
                    "updated": fields.get("updated"),
                    "issue_type": (fields.get("issuetype") or {}).get("name"),
                }
            )
        checklist = ai.build_offboarding_checklist(
            user_identifier=payload.user_identifier,
            items_payload={"jql": jql, "tickets": issues},
        )
        return OffboardingChecklistResponse(
            user_identifier=payload.user_identifier,
            tickets_found=len(issues),
            checklist=checklist,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/offboarding/document")
def offboarding_document(payload: OffboardingDocumentRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> dict[str, Any]:
    try:
        return _generate_offboarding_document(
            user_identifier=payload.user_identifier,
            extra_text=payload.extra_text,
            template_id=payload.template_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/assets/print-protocol", response_model=AssetsPrintProtocolResponse)
def assets_print_protocol(payload: AssetsPrintProtocolRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> AssetsPrintProtocolResponse:
    try:
        workspace_id = _require_assets_workspace()
        key_match = re.search(r"\bCDX-\d+\b", payload.object_query.upper())
        obj = None
        matched_user = None
        user_assets: list[dict[str, Any]] = []
        if key_match:
            raw = jira.get_asset_object(workspace_id=workspace_id, object_id_or_key=key_match.group(0))
            obj = flatten_assets_object(raw)
        else:
            person_query = _extract_person_query(payload.object_query) or payload.object_query.strip()
            if person_query:
                matched_user = _resolve_user_for_assets(person_query)
            if matched_user:
                display_name = str(matched_user.get("displayName") or "")
                email = str(matched_user.get("emailAddress") or "")
                account_id = str(matched_user.get("accountId") or "")
                data = jira.assets_query(
                    workspace_id=workspace_id,
                    aql="objectId > 0",
                    max_results=max(300, payload.max_results * 50),
                )
                objects_raw = (
                    data.get("objectEntries")
                    or data.get("results", {}).get("objectEntries")
                    or data.get("values")
                    or []
                )
                objects = [flatten_assets_object(o) for o in objects_raw]
                detailed_objects: list[dict[str, Any]] = []
                for base_obj in objects[:120]:
                    object_id_or_key = str(base_obj.get("objectKey") or base_obj.get("id") or "").strip()
                    if not object_id_or_key:
                        continue
                    try:
                        raw_detail = jira.get_asset_object(workspace_id=workspace_id, object_id_or_key=object_id_or_key)
                        detailed_objects.append(flatten_assets_object(raw_detail))
                    except Exception:
                        detailed_objects.append(base_obj)
                objects = detailed_objects
                user_tokens = [t for t in [display_name, email, account_id, person_query] if t]
                for candidate in objects:
                    text = _assets_text(candidate)
                    if any(_normalize_lookup_text(token) in text for token in user_tokens):
                        user_assets.append(candidate)
                hw_assets = [a for a in user_assets if _is_hw_like(a)]
                if hw_assets:
                    user_assets = hw_assets
            if user_assets:
                lines = [
                    "# Odovzdavaci Protokol",
                    "",
                    f"Pouzivatel: {matched_user.get('displayName')}",
                ]
                if matched_user.get("emailAddress"):
                    lines.append(f"Email: {matched_user.get('emailAddress')}")
                lines.extend(["", "## Pridelene zariadenia"])
                for asset in user_assets[:25]:
                    lines.append(f"- {asset.get('objectKey')}: {asset.get('label')} ({asset.get('objectType')})")
                    attrs = asset.get("attributes") or {}
                    for k, v in attrs.items():
                        if str(k).lower() in {"key", "created", "updated"}:
                            continue
                        lines.append(f"  - {k}: {v}")
                lines.extend(
                    [
                        "",
                        "## Potvrdenie",
                        "- Datum odovzdania: __________",
                        "- Odovzdal: __________",
                        "- Prevzal: __________",
                        "- Poznamka: __________",
                    ]
                )
                return AssetsPrintProtocolResponse(object_query=payload.object_query, protocol="\n".join(lines))

            result = _assets_search_from_nl(
                nl_query=f"Find exact assets object for: {payload.object_query}",
                max_results=max(payload.max_results, 5),
            )
            if result.objects:
                obj = result.objects[0]
                object_id_or_key = str(obj.get("objectKey") or obj.get("id") or "").strip()
                if object_id_or_key:
                    try:
                        raw_detail = jira.get_asset_object(workspace_id=workspace_id, object_id_or_key=object_id_or_key)
                        obj = flatten_assets_object(raw_detail)
                    except Exception:
                        pass

        if not obj:
            raise HTTPException(status_code=404, detail="No Assets object found.")
        attrs = obj.get("attributes", {})
        lines = [
            f"# Odovzdavaci Protokol",
            f"",
            f"Object: {obj.get('label')}",
            f"Object Key: {obj.get('objectKey')}",
            f"Object Type: {obj.get('objectType')}",
            f"",
            f"## Attributes",
        ]
        for k, v in attrs.items():
            lines.append(f"- {k}: {v}")
        lines.extend(
            [
                "",
                "## Potvrdenie",
                "- Datum odovzdania: __________",
                "- Odovzdal: __________",
                "- Prevzal: __________",
                "- Poznamka: __________",
            ]
        )
        return AssetsPrintProtocolResponse(object_query=payload.object_query, protocol="\n".join(lines))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, api_access: dict[str, Any] = Depends(_require_api_access)) -> ChatResponse:
    try:
        history = payload.history or []
        history_tail = history[-12:]
        history_text = "\n".join(
            f"{(h.get('role') or 'unknown')}: {(h.get('content') or '')[:500]}"
            for h in history_tail
        ).strip()
        current_user = _current_user_from_payload(payload)
        current_user_label = str(
            (current_user or {}).get("displayName")
            or (current_user or {}).get("emailAddress")
            or (current_user or {}).get("accountId")
            or ""
        ).strip()
        user_context = f"Current Jira user: {current_user_label}\n" if current_user_label else ""
        model_input = (
            f"{user_context}{payload.message}"
            if not history_text
            else f"{user_context}Recent chat history:\n{history_text}\n\nUser: {payload.message}"
        )

        pending = _decode_pending_action(payload.pending_action)
        if pending.get("type") == "offboarding_select_asset":
            permission_error = _bot_permission_error(
                action="offboarding",
                current_user=current_user,
                api_access=api_access,
            )
            if permission_error:
                return permission_error
            return _complete_offboarding_asset_selection(pending, payload.message)
        if pending.get("type") in {"onboarding_select_asset", "onboarding_select_recipient"}:
            permission_error = _bot_permission_error(
                action="onboarding",
                current_user=current_user,
                api_access=api_access,
            )
            if permission_error:
                return permission_error
            return _complete_onboarding_asset_selection(pending, payload.message)

        lower_message = payload.message.lower()
        normalized_message = _normalize_lookup_text(payload.message)
        yes_all_hint = bool(re.search(r"\b(vsetky|všetky|all|ano|áno|ok)\b", lower_message))
        create_hint = bool(re.search(r"\b(vytvor|sprav|vyrob|create|make)\b", lower_message)) and "ticket" in lower_message
        search_hint = bool(re.search(r"\b(najdi|hladaj|search|find|list|vypis)\b", lower_message))
        summarize_hint = bool(re.search(r"\b(summary|summar|zhrn|sumariz|sprav summary)\b", lower_message))
        offboarding_checklist_hint = bool(
            re.search(r"\b(checklist|zoznam\s+pristup|zoznam\s+prístup|access\s+audit|audit\s+pristup|audit\s+prístup)\b", normalized_message)
            and re.search(r"\b(offboarding|offboard|ukoncenie|ukončenie|konci|contract|pristup|prístup|access|jira)\b", normalized_message)
        )
        offboarding_doc_hint = bool(
            re.search(
                r"\b(offboarding|offboard|offboardovat|ofboarding|ofbord|offbord|offbordnig|offbordnigovat|ofbordnigovat|ukoncenie|ukončenie)\b",
                lower_message,
            )
            or (
                re.search(r"\b(preberaci|preberací|vratenie|vrátenie)\b", lower_message)
                and re.search(r"\b(protokol|zariaden|pc|laptop|notebook|hardware)\b", lower_message)
            )
        )
        onboarding_doc_hint = bool(
            re.search(
                r"\b(onboarding|nastup|novy\s+zamestnanec|novému|novemu|dostane|odovzdavaci|odovzdávací|pridel|priraď|prirad|assign|assigni|odovzdaj|odovzdat|odovzdať)\b",
                lower_message,
            )
            and re.search(r"\b(protokol|zariaden|pc|pocitac|počítač|laptop|notebook|hardware)\b", lower_message)
        )
        protocol_for_person_hint = bool(
            re.search(r"\b(protokol|pdf|dokument|vytlac|vytla?|tlac|tla?|print)\b", lower_message)
            and _extract_person_after_pre(payload.message)
            and not _extract_issue_key(payload.message)
        )
        asset_key_print_hint = bool(re.search(r"\b[A-Z]{2,10}-\d+\b", payload.message.upper()))
        help_hint = bool(re.search(r"\b(help|pomoc|co vies|co dokazes|what can you do|capabilities)\b", lower_message))
        whoami_hint = bool(
            re.search(
                r"\b(kto som|kym som|ak[ýy] som user|aky som user|moj ucet|m[oô]j ucet|who am i|current user)\b",
                normalized_message,
            )
        )
        greeting_hint = bool(re.search(r"\b(ahoj|cau|čau|halo|hello|hi|hey)\b", lower_message.strip()))
        thanks_hint = bool(re.search(r"\b(dakujem|ďakujem|thanks|thank you|thx)\b", lower_message))
        assign_hint = bool(re.search(r"\b(assign|prirad|assigni|assigned|asignuj)\b", lower_message)) and (
            "ticket" in lower_message or "tiket" in lower_message
        )
        close_hint = bool(re.search(r"\b(zavri|uzavri|close|closed|resolve|resolved|hotovo|done)\b", lower_message)) and (
            "ticket" in lower_message or "tiket" in lower_message or _extract_issue_key(payload.message) is not None
        )
        list_users_hint = bool(
            re.search(r"\b(zoznam|vypis|list|kto su|ake mame|akych mame|daj mi|ukaz)\b", normalized_message)
            and re.search(
                r"\b(user|useri|userov|users|uzivatel|uzivatelia|uzivatelov|pouzivatel|pouzivatelia|pouzivatelov|admin|admini|adminov|admins)\b",
                normalized_message,
            )
        )
        list_tickets_hint = bool(
            re.search(r"\b(zoznam|vypis|list|ake mame|akych mame|daj mi|ukaz)\b", normalized_message)
            and re.search(r"\b(ticket|tickets|ticketov|tiket|tickety|tiketov|issue|issues)\b", normalized_message)
        )
        hw_person_hint = bool(re.search(r"\b(laptop|notebook|pc|computer|hardware|zariadenie|zariadenia)\b", lower_message)) and bool(
            re.search(r"\b(ma|má|mam|mám|moje|moj|môj|has)\b", lower_message)
        )
        assets_hint = "assets" in lower_message or "insight" in lower_message or "ci " in lower_message or "ci/" in lower_message
        create_count_match = re.search(r"\b(\d{1,2})\b", lower_message)
        create_count = int(create_count_match.group(1)) if create_count_match and create_hint and not search_hint else 1
        create_count = max(1, min(create_count, 10))

        parsed = ai.detect_chat_action(
            user_message=model_input,
            default_project=settings.jira_project_key,
            default_issue_type=settings.jira_default_issue_type,
        )
        action = str(parsed.get("action", "")).lower().strip()
        if whoami_hint:
            action = "whoami"
        elif list_users_hint:
            action = "list_users"
        elif list_tickets_hint:
            action = "list_tickets"
        elif offboarding_checklist_hint:
            action = "offboarding_checklist"
        elif onboarding_doc_hint:
            action = "onboarding"
        elif offboarding_doc_hint:
            action = "offboarding"
        elif protocol_for_person_hint:
            action = "offboarding"
        elif greeting_hint or thanks_hint:
            action = "chat"
        elif create_hint and not search_hint and not summarize_hint:
            action = "create"
        elif close_hint:
            action = "close"
        elif assign_hint:
            action = "assign"
        elif help_hint:
            action = "help"
        elif hw_person_hint:
            action = "assets_hw"
        elif action == "assets_print" and not asset_key_print_hint and _extract_person_after_pre(payload.message):
            action = "offboarding"
        elif assets_hint and action in {"search", ""}:
            action = "assets_search"

        if pending.get("type") == "assign_all_unassigned" and yes_all_hint:
            permission_error = _bot_permission_error(
                action="assign_bulk",
                current_user=current_user,
                api_access=api_access,
            )
            if permission_error:
                return permission_error
            assignee_query = str(pending.get("assignee_query") or "").strip()
            if not assignee_query:
                raise HTTPException(status_code=400, detail="Pending assign action is missing assignee_query.")
            bulk = _assign_all_unassigned(assignee_query, max_results=500)
            return ChatResponse(
                action="assign_bulk",
                message=f"Hotovo. Priradil som {bulk['assigned_count']} neassignovanych ticketov na {bulk['assignee_display_name']}.",
                data=bulk,
            )

        permission_error = _bot_permission_error(
            action=action or "search",
            current_user=current_user,
            api_access=api_access,
        )
        if permission_error:
            return permission_error

        if action == "create":
            summary = parsed.get("summary") or payload.message[:250]
            description = parsed.get("description")
            issue_type = parsed.get("issue_type") or settings.jira_default_issue_type
            project_key = parsed.get("project_key") or settings.jira_project_key
            created_items = []
            for i in range(create_count):
                item_summary = summary if create_count == 1 else f"{summary} #{i + 1}"
                created = jira.create_issue(
                    project_key=project_key,
                    issue_type=issue_type,
                    summary=item_summary,
                    description=description,
                )
                created_items.append(created)
            created = created_items[-1]
            return ChatResponse(
                action="create",
                message=f"Created {len(created_items)} ticket(s). Last: {created.get('key')}",
                data={"created": created_items},
            )

        if action == "summarize":
            issue_key = parsed.get("issue_key")
            if not issue_key:
                match = re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", payload.message)
                issue_key = match.group(0) if match else None
            if not issue_key:
                issue_key = payload.current_issue_key or _extract_issue_key_from_history(payload.history)
            if not issue_key:
                raise HTTPException(status_code=400, detail="Issue key not found. Example: KAN-1")
            issue = jira.get_issue(issue_key)
            comments = jira.get_comments(issue_key, max_results=payload.max_comments)
            summary = ai.summarize_issue({"issue": issue, "comments": comments.get("comments", [])})
            return ChatResponse(
                action="summarize",
                message=f"Zhrnutie ticketu {issue_key}:\n{summary}",
                data={"issue_key": issue_key, "summary": summary},
            )

        if action == "assign":
            issue_key = (
                parsed.get("issue_key")
                or _extract_issue_key(payload.message)
                or payload.current_issue_key
                or _extract_issue_key_from_history(payload.history)
            )
            assignee_query = _resolve_assignee_query(payload.message, parsed)
            if re.search(r"\b(mne|mna|mňa|sebe|me|myself)\b", normalized_message):
                assignee_query = current_user_label or assignee_query
            if not assignee_query:
                raise HTTPException(
                    status_code=400,
                    detail="Assignee missing. Example: 'prirad KAN-12 na imrich'.",
                )
            wants_all = bool(re.search(r"\b(vsetky|všetky|all|neassignovane|nepriradene)\b", lower_message))
            if wants_all and not issue_key:
                bulk = _assign_all_unassigned(assignee_query, max_results=500)
                return ChatResponse(
                    action="assign_bulk",
                    message=f"Hotovo. Priradil som {bulk['assigned_count']} neassignovanych ticketov na {bulk['assignee_display_name']}.",
                    data=bulk,
                )
            if not issue_key:
                user = _resolve_assignee_user(assignee_query)
                return ChatResponse(
                    action="chat",
                    message=(
                        f"Nasiel som pouzivatela {user.get('displayName')}. "
                        "Chces, aby som mu priradil vsetky neassignovane tickety? "
                        "Napis \"vsetky\" alebo \"ano\"."
                    ),
                    data=_pending_data({"type": "assign_all_unassigned", "assignee_query": assignee_query}),
                )
            assigned = _assign_ticket(issue_key, assignee_query)
            return ChatResponse(
                action="assign",
                message=f"Issue {assigned.issue_key} assigned to {assigned.assignee_display_name}",
                data=assigned.model_dump(),
            )

        if action == "close":
            issue_key = (
                parsed.get("issue_key")
                or _extract_issue_key(payload.message)
                or payload.current_issue_key
                or _extract_issue_key_from_history(payload.history)
            )
            if not issue_key:
                raise HTTPException(status_code=400, detail="Issue key missing. Example: zavri KAN-11")
            closed = _close_issue(issue_key)
            if closed.get("changed"):
                msg = f"Jasne, ticket {issue_key} som uzavrel. Novy status: {closed.get('status')}."
            else:
                msg = f"Ticket {issue_key} je uz uzavrety (status: {closed.get('status')})."
            return ChatResponse(action="close", message=msg, data=closed)

        if action == "whoami":
            if not current_user:
                return ChatResponse(
                    action="whoami",
                    message="V Jira paneli zatiaľ nevidím identitu aktuálneho používateľa. Skús po redeployi Forge appky.",
                    data=None,
                )
            return ChatResponse(
                action="whoami",
                message=f"Komunikuješ ako {current_user_label}.",
                data={
                    "current_user": {
                        "display_name": current_user.get("displayName"),
                        "email": current_user.get("emailAddress"),
                        "account_id": current_user.get("accountId"),
                        "active": current_user.get("active"),
                    }
                },
            )

        if action == "list_users":
            users = jira.list_assignable_users(project_key=settings.jira_project_key, max_results=min(payload.max_results, 100))
            mapped = [
                {
                    "display_name": u.get("displayName"),
                    "email": u.get("emailAddress"),
                    "account_id": u.get("accountId"),
                    "active": u.get("active"),
                }
                for u in users
            ]
            return ChatResponse(
                action="list_users",
                message=f"Našiel som {len(mapped)} používateľov.",
                data={"users": mapped},
            )

        if action == "list_tickets":
            result = jira.search_with_fields(
                jql=f"project = {settings.jira_project_key} ORDER BY updated DESC",
                fields=["summary", "status", "priority", "assignee", "created", "updated", "issuetype"],
                max_results=payload.max_results,
            )
            issues = []
            for issue in result.get("issues", []):
                fields = issue.get("fields", {})
                assignee = fields.get("assignee") or {}
                issues.append(
                    {
                        "key": issue.get("key"),
                        "summary": fields.get("summary"),
                        "status": (fields.get("status") or {}).get("name"),
                        "priority": (fields.get("priority") or {}).get("name"),
                        "assignee": assignee.get("displayName"),
                        "updated": fields.get("updated"),
                        "created": fields.get("created"),
                        "issue_type": (fields.get("issuetype") or {}).get("name"),
                    }
                )
            return ChatResponse(
                action="list_tickets",
                message=f"Našiel som {len(issues)} tiketov.",
                data={"jql": f"project = {settings.jira_project_key} ORDER BY updated DESC", "total": len(issues), "issues": issues},
            )

        if action == "help":
            lines = [
                "Viem pracovat s Jira ticketmi cez chat:",
                "1) Vytvorit ticket: \"vytvor ticket: ...\"",
                "2) Vytvorit viac ticketov: \"sprav 5 ticketov ...\"",
                "3) Najst tickety textom: \"najdi otvorene tickety o ...\"",
                "4) Spravit summary: \"sprav summary pre KAN-1\"",
                "5) Priradit ticket: \"prirad KAN-12 na imrich\"",
                "6) Uzavriet ticket: \"zavri KAN-11\"",
                "7) Zoznam ticketov: \"daj mi zoznam tiketov\"",
                "8) Zoznam userov: \"daj mi zoznam userov\"",
                "9) Offboarding checklist podla pristupov v Jira",
            ]
            if _assets_enabled():
                lines.extend(
                    [
                        "10) Assets lookup: owner, HW inventory, job/file, SLA, DORA relevance",
                        "11) Assets print protocol (odovzdavaci protokol)",
                    ]
                )
            lines.append("Tip: pis prirodzene, ja rozhodnem co mam urobit.")
            help_text = "\n".join(lines)
            return ChatResponse(action="help", message=help_text, data=None)

        if action == "chat":
            reply = ai.general_chat_reply(user_message=model_input, assets_enabled=_assets_enabled())
            return ChatResponse(action="chat", message=reply, data=None)

        if action in {"assets_search", "assets_owner", "assets_hw", "assets_job_file", "assets_dora", "assets_sla"}:
            if not _assets_enabled():
                return ChatResponse(
                    action=action,
                    message="Assets funkcie su docasne nedostupne, lebo nie je nastavene ASSETS_WORKSPACE_ID alebo chybaju prava.",
                    data=None,
            )
            query_text = parsed.get("query") or payload.message
            if action == "assets_hw":
                if current_user_label and re.search(r"\b(mam|mám|moje|moj|môj|mne|ja|my)\b", normalized_message):
                    query_text = current_user_label
                user, user_assets = _assets_for_user(query_text, payload.max_results, only_hw=True)
                if user and user_assets:
                    return ChatResponse(
                        action=action,
                        message=f"Nasiel som {len(user_assets)} HW assetov pre {user.get('displayName')}.",
                        data={"total": len(user_assets), "objects": user_assets},
                    )
                if user and not user_assets:
                    return ChatResponse(
                        action=action,
                        message=f"Pre {user.get('displayName')} som nenasiel ziadny priradeny HW asset.",
                        data={"total": 0, "objects": []},
                    )
                return ChatResponse(
                    action=action,
                    message="Pouzivatela sa nepodarilo jednoznacne najst. Skus meno alebo email presnejsie.",
                    data={"total": 0, "objects": []},
                )
            assets_result = _assets_search_from_nl(parsed.get("query") or payload.message, payload.max_results)
            return ChatResponse(
                action=action,
                message=f"Assets query returned {assets_result.total} object(s)",
                data=assets_result.model_dump(),
            )

        if action == "offboarding_checklist":
            user_identifier = _extract_offboarding_checklist_person(payload.message, parsed)
            if not user_identifier:
                return ChatResponse(
                    action="offboarding_checklist",
                    message="Jasne. Napíš prosím meno alebo email človeka, napríklad: offboarding checklist pre Imrich Koch.",
                    data=None,
                )
            checklist = offboarding_checklist(
                OffboardingChecklistRequest(user_identifier=user_identifier),
                api_access=api_access,
            )
            return ChatResponse(
                action="offboarding_checklist",
                message=f"Offboarding checklist pre {checklist.user_identifier}:\n{checklist.checklist}",
                data=checklist.model_dump(),
            )

        if action == "offboarding":
            user_identifier = _extract_offboarding_person(payload.message, parsed)
            if not user_identifier:
                return ChatResponse(
                    action="offboarding",
                    message="Jasné. Napíš prosím meno alebo email človeka, napríklad: offboarding Imrich Koch.",
                    data=None,
                )
            if _assets_enabled():
                matched_user, user_assets = _assets_for_user(user_identifier, max_results=25, only_hw=True)
                if matched_user and user_assets:
                    return _offboarding_selection_prompt(matched_user, user_assets, extra_text=_extract_extra_text(payload.message))
                if matched_user and not user_assets:
                    request_norm = _normalize_lookup_text(payload.message)
                    explicit_return = any(
                        word in request_norm
                        for word in ["preberaci", "vratenie", "offboarding", "offboard", "ukoncenie"]
                    )
                    if not explicit_return:
                        available_assets = _assets_available_for_onboarding(max_results=25)
                        if available_assets:
                            response = _onboarding_selection_prompt(
                                available_assets,
                                recipient=matched_user.get("displayName") or user_identifier,
                                extra_text=_extract_extra_text(payload.message),
                                only_available=True,
                            )
                            response.message = (
                                f"Pre {matched_user.get('displayName')} som nenašiel priradený HW na vrátenie. "
                                "Ak chceš pripraviť protokol na odovzdanie nového zariadenia, vyber jeden z voľných počítačov:\n"
                                + response.message.split("\n", 1)[1]
                            )
                            return response
                    return ChatResponse(
                        action="offboarding",
                        message=(
                            f"Našiel som používateľa {matched_user.get('displayName')}, "
                            "ale v Assets pri ňom nevidím žiadny priradený počítač. "
                            "Aby bol protokol presný, napíš prosím konkrétny asset kľúč, napríklad `CDX-4`, "
                            "alebo požiadaj o odovzdávací protokol na nový počítač."
                        ),
                        data={"user": matched_user, "total": 0, "objects": []},
                    )
            generated = _generate_offboarding_document(
                user_identifier=user_identifier,
                extra_text=_extract_extra_text(payload.message),
            )
            return ChatResponse(
                action="offboarding",
                message=f"Offboarding dokument je pripraveny pre {generated['user']['display_name']}.",
                data=generated,
            )

        if action == "onboarding":
            if not _assets_enabled():
                return ChatResponse(
                    action="onboarding",
                    message="Onboarding protokol je docasne nedostupny, lebo nie je nastavene ASSETS_WORKSPACE_ID alebo chybaju prava.",
                    data=None,
                )
            available_assets = _assets_available_for_onboarding(max_results=25)
            if not available_assets:
                all_hw_assets = _assets_hw_inventory_for_onboarding(max_results=25)
                if not all_hw_assets:
                    return ChatResponse(
                        action="onboarding",
                        message="Nenasiel som ziadne HW zariadenie v Assets.",
                        data={"total": 0, "objects": []},
                    )
                recipient = _extract_onboarding_recipient(payload.message, parsed)
                return _onboarding_selection_prompt(
                    all_hw_assets,
                    recipient=recipient,
                    extra_text=_extract_extra_text(payload.message),
                    only_available=False,
                )
            recipient = _extract_onboarding_recipient(payload.message, parsed)
            return _onboarding_selection_prompt(
                available_assets,
                recipient=recipient,
                extra_text=_extract_extra_text(payload.message),
                only_available=True,
            )

        if action == "assets_print":
            if not _assets_enabled():
                return ChatResponse(
                    action="assets_print",
                    message="Assets print protocol je docasne nedostupny, lebo nie je nastavene ASSETS_WORKSPACE_ID alebo chybaju prava.",
                    data=None,
                )
            protocol = assets_print_protocol(AssetsPrintProtocolRequest(object_query=parsed.get("query") or payload.message))
            protocol_data = protocol.model_dump()
            safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(protocol_data.get("object_query", "asset"))).strip("-")
            if not safe_name:
                safe_name = "asset"
            file_name = f"print-protocol-{safe_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
            protocol_dir = GENERATED_DIR / "protocols"
            protocol_dir.mkdir(parents=True, exist_ok=True)
            (protocol_dir / file_name).write_text(str(protocol_data.get("protocol", "")), encoding="utf-8")
            protocol_data["protocol_url"] = _signed_download_url("protocols", file_name)
            return ChatResponse(
                action="assets_print",
                message="Assets print protocol ready",
                data=protocol_data,
            )

        query = parsed.get("query") or payload.message
        search_result = _search_logic(query, payload.max_results)
        return ChatResponse(
            action="search",
            message=f"Našiel som {search_result.total} tiketov.",
            data=search_result.model_dump(),
        )
    except HTTPException as exc:
        return ChatResponse(
            action="error",
            message=_friendly_error_message(exc.detail),
            data={"status_code": exc.status_code},
        )
    except JQLValidationError as exc:
        return ChatResponse(action="error", message=_friendly_error_message(exc), data={"type": "jql_validation"})
    except RuntimeError as exc:
        return ChatResponse(action="error", message=_friendly_error_message(exc), data={"type": "runtime"})
    except Exception as exc:
        return ChatResponse(action="error", message=_friendly_error_message(exc), data={"type": "unexpected"})


@app.post("/chat/widget", response_model=ChatResponse)
def chat_widget(payload: ChatRequest, widget_access: dict[str, Any] = Depends(_require_widget_access)) -> ChatResponse:
    return chat(payload, api_access=widget_access)
