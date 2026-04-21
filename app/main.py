import re
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.ai_client import AIClient
from app.analysis import cosine_similarity, extract_adf_text, overlap_keywords
from app.config import get_settings
from app.jira_client import JiraClient
from app.jql_guard import JQLValidationError, validate_jql
from app.schemas import (
    CreateTicketRequest,
    CreateTicketResponse,
    ClassifyIncidentRequest,
    ClassifyIncidentResponse,
    ChatRequest,
    ChatResponse,
    CorrelateChangesRequest,
    CorrelateChangesResponse,
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
    safe_jql = validate_jql(raw_jql)
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


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    try:
        lower_message = payload.message.lower()
        create_hint = bool(re.search(r"\b(vytvor|sprav|vyrob|create|make)\b", lower_message)) and "ticket" in lower_message
        search_hint = bool(re.search(r"\b(najdi|hladaj|search|find|list|vypis)\b", lower_message))
        summarize_hint = bool(re.search(r"\b(summary|summar|zhrn|sumariz|sprav summary)\b", lower_message))
        help_hint = bool(re.search(r"\b(help|pomoc|co vies|co dokazes|what can you do|capabilities)\b", lower_message))
        create_count_match = re.search(r"\b(\d{1,2})\b", lower_message)
        create_count = int(create_count_match.group(1)) if create_count_match and create_hint and not search_hint else 1
        create_count = max(1, min(create_count, 10))

        parsed = ai.detect_chat_action(
            user_message=payload.message,
            default_project=settings.jira_project_key,
            default_issue_type=settings.jira_default_issue_type,
        )
        action = str(parsed.get("action", "")).lower().strip()
        if create_hint and not search_hint and not summarize_hint:
            action = "create"
        elif help_hint:
            action = "help"

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
                raise HTTPException(status_code=400, detail="Issue key not found. Example: KAN-1")
            issue = jira.get_issue(issue_key)
            comments = jira.get_comments(issue_key, max_results=payload.max_comments)
            summary = ai.summarize_issue({"issue": issue, "comments": comments.get("comments", [])})
            return ChatResponse(
                action="summarize",
                message=f"Summary ready for {issue_key}",
                data={"issue_key": issue_key, "summary": summary},
            )

        if action == "help":
            help_text = (
                "Viem pracovat s Jira ticketmi cez chat:\n"
                "1) Vytvorit ticket: \"vytvor ticket: ...\"\n"
                "2) Vytvorit viac ticketov: \"sprav 5 ticketov ...\"\n"
                "3) Najst tickety textom: \"najdi otvorene tickety o ...\"\n"
                "4) Spravit summary: \"sprav summary pre KAN-1\"\n"
                "5) Vratim aj pouzite JQL pri vyhladavani.\n"
                "Tip: pis prirodzene, ja rozhodnem ci mam create/search/summarize."
            )
            return ChatResponse(action="help", message=help_text, data=None)

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
