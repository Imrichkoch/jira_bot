# JiraBot - notes for presentation

## 1. JiraBot
JiraBot is an AI assistant that turns Jira, Assets and IT paperwork into one natural-language conversation.

## 2. Why this project
The daily IT workflow is fragmented: tickets, comments, users, devices and handover documents live in different places. JiraBot connects those tasks.

## 3. What it can do
Highlight ticket search and summaries, ticket actions, Asset lookup, generated documents, current-user awareness and administrator configuration.

## 4. Demo
Open a ticket and use: "Zhrn tiket KAN-4". Then show that the result contains a summary, key facts, risks and next steps. Mention that bulk actions require confirmation.

## 5. Onboarding and offboarding
The bot first works with the Asset record, then prepares the handover document. The selected device is assigned or unassigned only as part of the controlled flow.

## 6. Architecture
Forge is the Jira UI integration. FastAPI is the backend and integration layer. Jira REST, Assets REST and the AI provider are external services. SQLite and the template store keep administration data.

## 7. Security
Permissions are controlled by JiraBot groups. Forge and backend use a shared secret. Pending actions are HMAC-signed. Downloads use short-lived signed URLs.

## 8. Testing
Explain that the project was tested with Slovak phrasing, typos, vague requests, negative cases, Assets flows and DOCX/PDF template uploads and renders.

## 9. Next steps
For production, add stronger monitoring and audit logs, routine token rotation and backups, an improved template editor, and expand to more Jira projects.

## 10. Close
The main value is reducing context switching. JiraBot does not replace Jira; it makes Jira operations easier to perform correctly.
