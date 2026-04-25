# Jira AI Ticket Bot (FastAPI)

Minimal backend bot, ktory vie:
- vytvorit ticket v Jira
- spravit AI summary z existujuceho ticketu
- vyhladavat podla prirodzeneho textu (AI prelozi text na JQL)
- admin rozhranie pre spravu adminov, AI modelu, system promptu a `skills.md`

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
- `OPENAI_BASE_URL` nechaj prazdne pre priame OpenAI volania, alebo nastav na `https://openrouter.ai/api/v1` pre OpenRouter modely
- `OPENROUTER_SITE_URL` a `OPENROUTER_APP_NAME` su volitelne, ale odporucane pri OpenRouter
- `ASSETS_WORKSPACE_ID` workspace ID pre Jira Assets (nutne pre Assets endpointy)
- `APP_DATA_DIR` volitelne miesto pre admin databazu a runtime nastavenia
- `ADMIN_BOOTSTRAP_USERNAME` a `ADMIN_BOOTSTRAP_PASSWORD` volitelne pre vytvorenie prveho admina

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

### Assign ticket

`POST /tickets/assign`

Priklad body:
```json
{
  "issue_key": "KAN-12",
  "assignee_query": "imrich"
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

### Similar/identical tickets

`POST /tickets/similar`

Priklad:
```json
{
  "issue_key": "KAN-1",
  "top_k": 5
}
```

alebo:
```json
{
  "text": "login fails after deploy with 500",
  "top_k": 5
}
```

### Assigning services to INC

`POST /inc/classify-service`

Priklad:
```json
{
  "issue_key": "KAN-4",
  "top_k": 3
}
```

Service mapping sa cita zo suboru `service_catalog.json` (name + keywords).

### Correlations between INC / Patch / Deploy

`POST /inc/correlate-changes`

Priklad:
```json
{
  "incident_issue_key": "KAN-4",
  "lookback_days": 14,
  "top_k": 10
}
```

### Assets natural-language search (owner/HW/job-file/DORA/SLA)

`POST /assets/search`

Priklad:
```json
{
  "query": "kto je owner service payroll-api",
  "max_results": 20
}
```

Poznamka: endpoint AI preklada text na AQL a robi query v Assets.

### End of Contract - access checklist from Jira tickets

`POST /offboarding/checklist`

Priklad:
```json
{
  "user_identifier": "john.doe@company.com",
  "lookback_days": 365,
  "max_results": 100
}
```

### Offboarding document from template

`POST /offboarding/document`

Priklad:
```json
{
  "user_identifier": "imrich koch",
  "extra_text": "Vratit notebook, nabijacku a dokovaciu stanicu."
}
```

Vrati URL na vygenerovany subor v `/static/offboarding/...`. Ak je v admin rozhrani aktivna DOCX/PDF sablona, pouzije ju. Ak sablona nie je nastavena, vytvori jednoduchy PDF dokument.

V chat rozhrani je offboarding/protokol dvojkrokovy:
- bot najprv najde Jira pouzivatela a jeho priradene HW Assets objekty
- opyta sa, ktore zariadenie sa odovzdava
- po vybere cislom, Assets klucom alebo textom vygeneruje dokument z aktivnej sablony
- po vygenerovani dokumentu sa pokusi vycistit volitelny editable assignment atribut v Assets, napr. `Assigned user`

### Print protocol in Jira Assets (odovzdavaci protokol)

`POST /assets/print-protocol`

Priklad:
```json
{
  "object_query": "notebook imrich koch"
}
```

Vrati markdown protokol s atributmi objektu.

## 4) Admin rozhranie

Admin UI bezi na:
- `/admin`

Admin vie:
- vytvarat dalsich adminov
- vybrat AI model pre dalsie odpovede bota z vacsieho katalogu providerov
- pouzit OpenAI modely priamo alebo OpenRouter model ID pre Anthropic, Google, DeepSeek, Meta/Llama, Mistral, Qwen, xAI a dalsie
- pri OpenRouter/custom `OPENAI_BASE_URL` backend pouziva OpenAI-compatible Chat Completions API
- menit system prompt
- menit `skills.md`, ktory sa priklada k AI instrukciam
- pridavat offboarding sablony vo formate DOCX/PDF
- nastavit DOCX placeholdery a PDF pozicie pre meno, PC, seriove cislo a doplnujuci text

Prvy admin sa da bootstrapnut cez env premenne:
- `ADMIN_BOOTSTRAP_USERNAME`
- `ADMIN_BOOTSTRAP_PASSWORD`

Po vytvoreni prveho admina je vhodne bootstrap hodnoty z env suboru odstranit a restartovat sluzbu. Existujuci admin zostane ulozeny v SQLite databaze.

Runtime data sa ukladaju do `data/` alebo do cesty z `APP_DATA_DIR`:
- `admin.sqlite3` obsahuje admin ucty, zahashovane hesla a session tokeny
- `bot_settings.json` obsahuje aktualny model a system prompt
- `skills.md` obsahuje editable instrukcie/schopnosti bota
- `offboarding_templates/` obsahuje metadata a nahrate offboarding sablony

`data/` je v `.gitignore`, aby sa do GitHubu nedostali hesla, tokeny, session ani produkcne nastavenia.

Poznamka k `skills.md`: sluzi ako prakticka vrstva instrukcii pre Jira bota. Admin moze menit spravanie bota bez deployu, napriklad styl odpovedi, pravidla pre Jira tickety alebo sposob, ako ma interpretovat poziadavky v chate.

## 5) Poznamky k bezpecnosti

- API tokeny drzat iba v `.env` (nikdy necommitovat).
- Admin hesla su ukladane hashovane, nie ako plaintext.
- Admin session token sa uklada v browseri do `localStorage`, preto admin rozhranie pouzivaj iba cez HTTPS.
- Verejne API endpointy maju stale rovnake spravanie ako doteraz; ak ich budes chciet uzamknut, doplnime API key/JWT aj pre `/chat` a Jira endpointy.
- Ak AI vrati divne JQL, `jql_guard.py` ho vie odmietnut.

## 6) Dalsie rozsirenia

- `/tickets/update` endpoint
- deduplikacia pri create (podla fingerprintu)
- Slack/Teams chat vrstva nad tymto API

## 7) Chat widget v Jira (Forge)

Endpoint pre Forge widget:
- `POST /chat/widget`
- pouziva rovnaku logiku ako `/chat`
- ak je nastavene `WIDGET_SHARED_SECRET`, vyzaduje hlavicku `x-widget-secret`

Forge app skeleton je v:
- `forge-jira-chat`

Nasadenie je popisane v:
- `forge-jira-chat/README.md`
