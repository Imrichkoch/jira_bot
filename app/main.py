import re
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.ai_client import AIClient
from app.analysis import cosine_similarity, extract_adf_text, flatten_assets_object, overlap_keywords
from app.config import get_settings
from app.jira_client import JiraClient
from app.jql_guard import JQLValidationError, validate_jql
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
jira = JiraClient(settings)
ai = AIClient(settings)
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def chat_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


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
def create_ticket(payload: CreateTicketRequest) -> CreateTicketResponse:
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
def summarize_ticket(payload: SummarizeTicketRequest) -> SummarizeTicketResponse:
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
def search_tickets(payload: SearchTicketsRequest) -> SearchTicketsResponse:
    try:
        return _search_logic(payload.query, payload.max_results)
    except JQLValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Generated JQL rejected: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tickets/assign", response_model=AssignTicketResponse)
def assign_ticket(payload: AssignTicketRequest) -> AssignTicketResponse:
    try:
        return _assign_ticket(payload.issue_key, payload.assignee_query)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tickets/similar", response_model=SimilarTicketsResponse)
def similar_tickets(payload: SimilarTicketsRequest) -> SimilarTicketsResponse:
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
def classify_incident_service(payload: ClassifyIncidentRequest) -> ClassifyIncidentResponse:
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
def correlate_changes(payload: CorrelateChangesRequest) -> CorrelateChangesResponse:
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
def assets_search(payload: AssetsQueryRequest) -> AssetsQueryResponse:
    try:
        return _assets_search_from_nl(payload.query, payload.max_results)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/offboarding/checklist", response_model=OffboardingChecklistResponse)
def offboarding_checklist(payload: OffboardingChecklistRequest) -> OffboardingChecklistResponse:
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


@app.post("/assets/print-protocol", response_model=AssetsPrintProtocolResponse)
def assets_print_protocol(payload: AssetsPrintProtocolRequest) -> AssetsPrintProtocolResponse:
    try:
        workspace_id = _require_assets_workspace()
        key_match = re.search(r"\bCDX-\d+\b", payload.object_query.upper())
        obj = None
        if key_match:
            raw = jira.get_asset_object(workspace_id=workspace_id, object_id_or_key=key_match.group(0))
            obj = flatten_assets_object(raw)
        else:
            result = _assets_search_from_nl(
                nl_query=f"Find exact assets object for: {payload.object_query}",
                max_results=max(payload.max_results, 5),
            )
            if result.objects:
                obj = result.objects[0]

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
def chat(payload: ChatRequest) -> ChatResponse:
    try:
        history = payload.history or []
        history_tail = history[-12:]
        history_text = "\n".join(
            f"{(h.get('role') or 'unknown')}: {(h.get('content') or '')[:500]}"
            for h in history_tail
        ).strip()
        model_input = payload.message if not history_text else f"Recent chat history:\n{history_text}\n\nUser: {payload.message}"

        lower_message = payload.message.lower()
        yes_all_hint = bool(re.search(r"\b(vsetky|všetky|all|ano|áno|ok)\b", lower_message))
        create_hint = bool(re.search(r"\b(vytvor|sprav|vyrob|create|make)\b", lower_message)) and "ticket" in lower_message
        search_hint = bool(re.search(r"\b(najdi|hladaj|search|find|list|vypis)\b", lower_message))
        summarize_hint = bool(re.search(r"\b(summary|summar|zhrn|sumariz|sprav summary)\b", lower_message))
        help_hint = bool(re.search(r"\b(help|pomoc|co vies|co dokazes|what can you do|capabilities)\b", lower_message))
        greeting_hint = bool(re.search(r"\b(ahoj|cau|čau|halo|hello|hi|hey)\b", lower_message.strip()))
        thanks_hint = bool(re.search(r"\b(dakujem|ďakujem|thanks|thank you|thx)\b", lower_message))
        assign_hint = bool(re.search(r"\b(assign|prirad|assigni|assigned|asignuj)\b", lower_message)) and (
            "ticket" in lower_message or "tiket" in lower_message
        )
        close_hint = bool(re.search(r"\b(zavri|uzavri|close|closed|resolve|resolved|hotovo|done)\b", lower_message)) and (
            "ticket" in lower_message or "tiket" in lower_message or _extract_issue_key(payload.message) is not None
        )
        list_users_hint = bool(re.search(r"\b(zoznam|vypis|list|kto su|kto sú)\b", lower_message)) and bool(
            re.search(r"\b(user|userov|users|pouzivatel|pouzivatelov|admin|adminov|admins)\b", lower_message)
        )
        list_tickets_hint = bool(
            re.search(r"\b(zoznam|vypis|list|ake mame|aké máme)\b", lower_message)
            and re.search(r"\b(ticket|tiket|tickety|tiketov|issues)\b", lower_message)
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
        if list_users_hint:
            action = "list_users"
        elif list_tickets_hint:
            action = "list_tickets"
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
        elif assets_hint and action in {"search", ""}:
            action = "assets_search"

        pending = payload.pending_action or {}
        if pending.get("type") == "assign_all_unassigned" and yes_all_hint:
            assignee_query = str(pending.get("assignee_query") or "").strip()
            if not assignee_query:
                raise HTTPException(status_code=400, detail="Pending assign action is missing assignee_query.")
            bulk = _assign_all_unassigned(assignee_query, max_results=500)
            return ChatResponse(
                action="assign_bulk",
                message=f"Hotovo. Priradil som {bulk['assigned_count']} neassignovanych ticketov na {bulk['assignee_display_name']}.",
                data=bulk,
            )

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
                message=f"Summary ready for {issue_key}",
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
                    data={"pending_action": {"type": "assign_all_unassigned", "assignee_query": assignee_query}},
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
                message=f"Found {len(mapped)} user(s)",
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
                message=f"Found {len(issues)} ticket(s)",
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
            assets_result = _assets_search_from_nl(parsed.get("query") or payload.message, payload.max_results)
            return ChatResponse(
                action=action,
                message=f"Assets query returned {assets_result.total} object(s)",
                data=assets_result.model_dump(),
            )

        if action == "offboarding":
            m = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", payload.message)
            user_identifier = m.group(1) if m else (parsed.get("query") or payload.message[:120])
            checklist = offboarding_checklist(
                OffboardingChecklistRequest(
                    user_identifier=user_identifier,
                    lookback_days=365,
                    max_results=100,
                )
            )
            return ChatResponse(
                action="offboarding",
                message=f"Offboarding checklist ready for {user_identifier}",
                data=checklist.model_dump(),
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
            protocol_dir = STATIC_DIR / "protocols"
            protocol_dir.mkdir(parents=True, exist_ok=True)
            (protocol_dir / file_name).write_text(str(protocol_data.get("protocol", "")), encoding="utf-8")
            protocol_data["protocol_url"] = f"/static/protocols/{file_name}"
            return ChatResponse(
                action="assets_print",
                message="Assets print protocol ready",
                data=protocol_data,
            )

        query = parsed.get("query") or payload.message
        search_result = _search_logic(query, payload.max_results)
        return ChatResponse(
            action="search",
            message=f"Found {search_result.total} issue(s)",
            data=search_result.model_dump(),
        )
    except HTTPException:
        raise
    except JQLValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Generated JQL rejected: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
