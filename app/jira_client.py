from __future__ import annotations

from typing import Any

import requests

from app.config import Settings


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.jira_base_url.rstrip("/")
        self._session = requests.Session()
        self._session.auth = (settings.jira_email, settings.jira_api_token)
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._session.request(
            method=method,
            url=f"{self._base_url}{path}",
            params=params,
            json=json,
            timeout=30,
        )
        if response.status_code >= 400:
            detail = {
                "status_code": response.status_code,
                "url": response.url,
                "body": response.text,
            }
            raise RuntimeError(f"Jira API error: {detail}")

        if response.text:
            return response.json()
        return {}

    def create_issue(
        self,
        *,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "fields": {
                "project": {"key": project_key},
                "issuetype": {"name": issue_type},
                "summary": summary,
            }
        }
        if description:
            payload["fields"]["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            }

        return self._request("POST", "/rest/api/3/issue", json=payload)

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            params={
                "fields": "summary,description,status,priority,assignee,reporter,created,updated,issuetype,labels",
            },
        )

    def get_comments(self, issue_key: str, max_results: int = 20) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}/comment",
            params={"maxResults": max_results},
        )

    def search(self, *, jql: str, max_results: int = 20) -> dict[str, Any]:
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status", "priority", "assignee", "created", "updated", "issuetype"],
        }
        return self._request("POST", "/rest/api/3/search/jql", json=payload)

    def search_with_fields(self, *, jql: str, fields: list[str], max_results: int = 50) -> dict[str, Any]:
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields,
        }
        return self._request("POST", "/rest/api/3/search/jql", json=payload)

    def assets_query(self, *, workspace_id: str, aql: str, max_results: int = 50) -> dict[str, Any]:
        payload = {
            "qlQuery": aql,
            "page": 1,
            "resultPerPage": max_results,
            "includeAttributes": True,
        }
        # Keep two endpoint variants for compatibility across Cloud rollouts.
        candidates = [
            f"/jsm/assets/workspace/{workspace_id}/v1/object/aql",
            f"/gateway/api/jsm/assets/workspace/{workspace_id}/v1/object/aql",
        ]
        last_error: Exception | None = None
        for path in candidates:
            try:
                return self._request("POST", path, json=payload)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error:
            raise RuntimeError(str(last_error))
        raise RuntimeError("Assets query failed with unknown error.")
