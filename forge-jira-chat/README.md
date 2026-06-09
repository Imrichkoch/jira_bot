# Jira AI Chat Directly In Jira (Forge)

This Forge app adds `Jira AI Chat` directly to Jira as an issue panel and as a global Jira page.
From the panel, users can also open a larger `Popout` modal chat window.

## Requirements

- Node.js 20+ or 22
- Forge CLI
- Atlassian account with permissions to install the app
- Running backend, your FastAPI bot, reachable from the internet over HTTPS

## 1) Install Dependencies

```bash
cd forge-jira-chat
npm install
cd static/chat-ui
npm install
npm run build
cd ../..
```

## 2) Login And Set Forge Variables

```bash
forge login
forge variables set BOT_BACKEND_URL "https://jira.raizenko.cloud"
forge variables set BOT_WIDGET_SECRET "CHANGE-ME-TO-A-STRONG-SECRET"
```

## 3) Deploy And Install

```bash
forge deploy
forge install
```

During `forge install`, choose:
- product: Jira
- site: your Atlassian site, for example `testrpchome.atlassian.net`
- environment: production or development

For non-interactive upgrades:

```bash
forge install --site testrpchome.atlassian.net --product jira --environment production --upgrade all --confirm-scopes --non-interactive
```

## 4) Backend Protection

In the backend env file, for example `/opt/jira-ai-ticket-bot/.env`, set:

```bash
WIDGET_SHARED_SECRET=CHANGE-ME-TO-A-STRONG-SECRET
```

Then restart:

```bash
systemctl restart jira-ai-ticket-bot.service
```

The Forge resolver calls `/chat/widget` with the `x-widget-secret` header.

## Note

The issue panel opens from the app icon in the issue detail view. Jira Product Discovery/Polaris views may not render `jira:issuePanel`, so the app also provides a global Jira page named `Jira AI Chat` under Jira apps.
