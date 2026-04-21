# Jira AI Chat priamo v Jira (Forge)

Toto je Forge appka, ktora prida `Jira AI Chat` priamo do issue view ako panel.
Z panela vies otvorit aj `Popout` modal chat okno.

## Co treba mat

- Node.js 20+ alebo 22
- Forge CLI
- Atlassian account s pravami na instalaciu appky
- Beziaci backend (tvoj FastAPI bot) dostupny z internetu

## 1) Install dependencies

```bash
cd forge-jira-chat
npm install
cd static/chat-ui
npm install
npm run build
cd ../..
```

## 2) Login + set Forge vars

```bash
forge login
forge variables set BOT_BACKEND_URL "http://76.13.148.10:8080"
forge variables set BOT_WIDGET_SECRET "ZMEN-MA-NA-SILNY-SECRET"
```

## 3) Deploy + install

```bash
forge deploy
forge install
```

Pri `forge install` vyber:
- product: Jira
- site: `imrichkoch.atlassian.net`
- environment: production (alebo development)

## 4) Backend ochrana

V backend env (`/etc/jira-ai-ticket-bot.env`) nastav:

```bash
WIDGET_SHARED_SECRET=ZMEN-MA-NA-SILNY-SECRET
```

Potom restart:

```bash
systemctl restart jira-ai-ticket-bot
```

Forge resolver vola endpoint `/chat/widget` s hlavičkou `x-widget-secret`.

## Poznamka

Issue panel sa otvara klikom na ikonu appky v issue detaile. To je najblizsie natívne "vyskakovacie" spravanie v Jira.
