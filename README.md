# Jira AI Ticket Bot (FastAPI)

Minimal backend bot, ktory vie:
- vytvorit ticket v Jira
- spravit AI summary z existujuceho ticketu
- vyhladavat podla prirodzeneho textu (AI prelozi text na JQL)

## 1) Setup

```powershell
cd D:\download\jira-ai-ticket-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Vypln `.env`:
- `JIRA_BASE_URL` napr. `https://imrichkoch.atlassian.net`
- `JIRA_EMAIL` tvoj Atlassian login email
- `JIRA_API_TOKEN` Atlassian API token
- `JIRA_PROJECT_KEY` napr. `KAN`
- `OPENAI_API_KEY` tvoj AI API kluc
- `OPENAI_BASE_URL` nechaj prazdne pre OpenAI, alebo nastav na `https://openrouter.ai/api/v1` pre OpenRouter
- `OPENROUTER_SITE_URL` a `OPENROUTER_APP_NAME` su volitelne, ale odporucane pri OpenRouter

## 2) Spustenie

```powershell
uvicorn app.main:app --reload --port 8080
```

Swagger UI:
- [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)

## 3) Endpointy

### Chat endpoint (all-in-one)

`POST /chat`

Priklady body:
```json
{
  "message": "Vytvor ticket: Login pada po deployi, users dostavaju 500",
  "max_results": 20,
  "max_comments": 20
}
```

```json
{
  "message": "Sprav summary pre KAN-1"
}
```

```json
{
  "message": "Najdi otvorene tickety o login probleme za posledne 2 tyzdne"
}
```

### Create ticket

`POST /tickets/create`

Priklad body:
```json
{
  "summary": "Padanie loginu po deployi",
  "description": "Po release 1.2.4 pada prihlasenie pre cast userov.",
  "issue_type": "Task"
}
```

### Summarize ticket

`POST /tickets/summarize`

Priklad body:
```json
{
  "issue_key": "KAN-1",
  "max_comments": 20
}
```

### Search by text

`POST /tickets/search`

Priklad body:
```json
{
  "query": "Najdi otvorene tickety o login probleme za posledne 2 tyzdne",
  "max_results": 20
}
```

Response vracia:
- AI vygenerovane JQL (`jql`)
- `total`
- zjednoduseny zoznam issue

## 4) Poznamky k bezpecnosti

- API tokeny drzat iba v `.env` (nikdy necommitovat).
- V produkcii pridaj autentifikaciu endpointov (napr. API key/JWT).
- Ak AI vrati divne JQL, `jql_guard.py` ho vie odmietnut.

## 5) Dalsie rozsireniа

- `/tickets/update` endpoint
- deduplikacia pri create (podla fingerprintu)
- Slack/Teams chat vrstva nad tymto API
