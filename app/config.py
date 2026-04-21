from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_project_key: str
    jira_default_issue_type: str = "Task"
    openai_api_key: str
    openai_model: str = "gpt-5-mini"
    openai_base_url: str | None = None
    openrouter_site_url: str | None = None
    openrouter_app_name: str = "jira-ai-ticket-bot"
    assets_workspace_id: str | None = None
    widget_shared_secret: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
