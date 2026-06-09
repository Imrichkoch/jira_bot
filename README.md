# Jira AI Ticket Bot (FastAPI)

A minimal backend bot that can:
- create Jira tickets
- generate AI summaries for existing tickets
- search Jira from natural-language text by converting it to JQL
- manage admin users, AI model selection, system prompts, and `skills.md`
- work with Jira Assets and generate handover/offboarding documents

## 1) Setup

```powershell
cd D:\download\jira-ai-ticket-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill in `.env`:
- `JIRA_BASE_URL`, for example `https://your-site.atlassian.net`
- `JIRA_EMAIL`, your Atlassian login email
- `JIRA_API_TOKEN`, your Atlassian API token
- `JIRA_PROJECT_KEY`, for example `KAN`
- `OPENAI_API_KEY`, your AI API key
- `OPENAI_BASE_URL`, leave empty for direct OpenAI calls or set to `https://openrouter.ai/api/v1` for OpenRouter models
- `OPENROUTER_SITE_URL` and `OPENROUTER_APP_NAME`, optional but recommended for OpenRouter
- `ASSETS_WORKSPACE_ID`, the Jira Assets workspace ID required for Assets endpoints
- `WIDGET_SHARED_SECRET`, a long random secret that must match `BOT_WIDGET_SECRET` in Forge
- `APP_DATA_DIR`, optional location for the admin database and runtime settings
- `ADMIN_BOOTSTRAP_USERNAME` and `ADMIN_BOOTSTRAP_PASSWORD`, optional bootstrap values for creating the first admin

## 2) Run Locally

```powershell
uvicorn app.main:app --reload --port 8080
```

Swagger UI:
- [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)

## 3) Endpoints

All endpoints that read or modify Jira/Assets data require authentication:
- admin bearer token from `/admin/api/login`: `Authorization: Bearer <token>`
- or Forge/widget secret: `X-Widget-Secret: <WIDGET_SHARED_SECRET>`

`/chat/widget` always requires `WIDGET_SHARED_SECRET`. The public web chat `/` works after admin login on the same domain.

### Chat Endpoint (All-In-One)

`POST /chat`

Example bodies:
```json
{
  "message": "Create ticket: Login fails after deploy, users get 500",
  "max_results": 20,
  "max_comments": 20
}
```

```json
{
  "message": "Summarize KAN-1"
}
```

```json
{
  "message": "Find open tickets about login problems from the last 2 weeks"
}
```

### Create Ticket

`POST /tickets/create`

Example body:
```json
{
  "summary": "Login failure after deploy",
  "description": "After release 1.2.4, login fails for some users.",
  "issue_type": "Task"
}
```

### Assign Ticket

`POST /tickets/assign`

Example body:
```json
{
  "issue_key": "KAN-12",
  "assignee_query": "imrich"
}
```

### Summarize Ticket

`POST /tickets/summarize`

Example body:
```json
{
  "issue_key": "KAN-1",
  "max_comments": 20
}
```

### Search By Text

`POST /tickets/search`

Example body:
```json
{
  "query": "Find open tickets about login problems from the last 2 weeks",
  "max_results": 20
}
```

The response returns:
- AI-generated JQL (`jql`)
- `total`
- simplified issue list

### Similar/Identical Tickets

`POST /tickets/similar`

Example:
```json
{
  "issue_key": "KAN-1",
  "top_k": 5
}
```

or:
```json
{
  "text": "login fails after deploy with 500",
  "top_k": 5
}
```

### Assigning Services To Incidents

`POST /inc/classify-service`

Example:
```json
{
  "issue_key": "KAN-4",
  "top_k": 3
}
```

Service mapping is read from `service_catalog.json` (`name` + `keywords`).

### Correlations Between Incidents / Patches / Deploys

`POST /inc/correlate-changes`

Example:
```json
{
  "incident_issue_key": "KAN-4",
  "lookback_days": 14,
  "top_k": 10
}
```

### Assets Natural-Language Search (Owner/HW/Job-File/DORA/SLA)

`POST /assets/search`

Example:
```json
{
  "query": "who owns the payroll-api service",
  "max_results": 20
}
```

Note: the endpoint converts natural language to AQL and queries Jira Assets.

### End Of Contract - Access Checklist From Jira Tickets

`POST /offboarding/checklist`

Example:
```json
{
  "user_identifier": "john.doe@company.com",
  "lookback_days": 365,
  "max_results": 100
}
```

### Offboarding Document From Template

`POST /offboarding/document`

Example:
```json
{
  "user_identifier": "imrich koch",
  "extra_text": "Return the laptop, charger, and docking station."
}
```

Returns a short-lived signed download URL under `/download/offboarding/...`. If an active DOCX/PDF template is configured in the admin UI, it is used. If no template is configured, the bot creates a simple fallback PDF document.

In the chat UI, offboarding/return protocol is a two-step flow:
- the bot first finds the Jira user and their assigned hardware Assets objects
- it asks which device is being returned
- after selection by number, Assets key, or text, it generates a document from the active template
- after document generation, it tries to clear the optional editable assignment attribute in Assets, for example `Assigned user`

Onboarding / handover protocol works similarly:
- the bot first offers available hardware devices from Assets
- if no free device is found, it also shows currently assigned devices with a warning that selecting one will overwrite the assignment
- the user selects a device and provides the name/email of the recipient
- the bot generates a document from the active onboarding template
- after document generation, it tries to write the user into an editable assignment attribute in Assets, for example `Assigned user`

### Print Protocol In Jira Assets

`POST /assets/print-protocol`

Example:
```json
{
  "object_query": "notebook imrich koch"
}
```

Returns a markdown protocol with object attributes.

## 4) Admin UI

Admin UI is available at:
- `/admin`

Admins can:
- create additional admins
- choose the AI model for future bot responses from a larger provider catalog
- use OpenAI models directly or OpenRouter model IDs for Anthropic, Google, DeepSeek, Meta/Llama, Mistral, Qwen, xAI, and others
- use OpenAI-compatible Chat Completions via OpenRouter/custom `OPENAI_BASE_URL`
- edit the system prompt
- edit `skills.md`, which is included in AI instructions
- upload onboarding/offboarding templates in DOCX/PDF format
- configure DOCX placeholders and PDF positions for employee name, PC/device, serial number, and extra text

The first admin can be bootstrapped through environment variables:
- `ADMIN_BOOTSTRAP_USERNAME`
- `ADMIN_BOOTSTRAP_PASSWORD`

After creating the first admin, remove the bootstrap values from the env file and restart the service. The existing admin remains stored in the SQLite database.

Runtime data is stored in `data/` or in the path configured via `APP_DATA_DIR`:
- `admin.sqlite3` contains admin accounts, hashed passwords, and session tokens
- `bot_settings.json` contains the current model and system prompt
- `skills.md` contains editable bot instructions/capabilities
- `offboarding_templates/` contains metadata and uploaded offboarding templates

`data/` is in `.gitignore` to keep passwords, tokens, sessions, and production settings out of GitHub.

Note about `skills.md`: it acts as a practical instruction layer for the Jira bot. Admins can change bot behavior without redeploying, for example response style, Jira ticket rules, or how chat requests should be interpreted.

## 5) Security Notes

- Keep API tokens only in `.env`; never commit them.
- Admin passwords are stored as hashes, not plaintext.
- The admin session token is stored in browser `localStorage`, so use the admin UI only over HTTPS.
- Public API endpoints require either an admin session/bearer token or the Forge widget secret.
- If AI returns invalid JQL, `jql_guard.py` can reject it.

## 6) Future Extensions

- `/tickets/update` endpoint
- create deduplication by fingerprint
- Slack/Teams chat layer on top of this API

## 7) Jira Chat Widget (Forge)

Endpoint for the Forge widget:
- `POST /chat/widget`
- uses the same logic as `/chat`
- requires the `x-widget-secret` header when `WIDGET_SHARED_SECRET` is configured

Forge app skeleton is in:
- `forge-jira-chat`

Deployment is described in:
- `forge-jira-chat/README.md`
