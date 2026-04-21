from typing import Any

from pydantic import BaseModel, Field


class CreateTicketRequest(BaseModel):
    summary: str = Field(min_length=3, max_length=255)
    description: str | None = None
    issue_type: str | None = None
    project_key: str | None = None


class CreateTicketResponse(BaseModel):
    id: str
    key: str
    self: str


class SummarizeTicketRequest(BaseModel):
    issue_key: str
    max_comments: int = Field(default=20, ge=0, le=100)


class SummarizeTicketResponse(BaseModel):
    issue_key: str
    summary: str


class SearchTicketsRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    max_results: int = Field(default=20, ge=1, le=50)


class SearchTicketsResponse(BaseModel):
    jql: str
    total: int
    issues: list[dict[str, Any]]


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    max_results: int = Field(default=20, ge=1, le=50)
    max_comments: int = Field(default=20, ge=0, le=100)


class ChatResponse(BaseModel):
    action: str
    message: str
    data: dict[str, Any] | None = None


class SimilarTicketsRequest(BaseModel):
    issue_key: str | None = None
    text: str | None = None
    max_candidates: int = Field(default=100, ge=10, le=300)
    top_k: int = Field(default=10, ge=1, le=30)


class SimilarTicketsResponse(BaseModel):
    source: str
    top_k: int
    items: list[dict[str, Any]]


class ClassifyIncidentRequest(BaseModel):
    issue_key: str | None = None
    text: str | None = None
    top_k: int = Field(default=3, ge=1, le=10)


class ClassifyIncidentResponse(BaseModel):
    predicted_service: str
    confidence: float
    alternatives: list[dict[str, Any]]


class CorrelateChangesRequest(BaseModel):
    incident_issue_key: str | None = None
    incident_text: str | None = None
    lookback_days: int = Field(default=14, ge=1, le=90)
    top_k: int = Field(default=10, ge=1, le=30)


class CorrelateChangesResponse(BaseModel):
    incident_source: str
    lookback_days: int
    links: list[dict[str, Any]]
