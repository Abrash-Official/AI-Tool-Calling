# AI Tool-Calling Agent

A FastAPI-based AI agent that uses **Groq** for tool-calling and can:

- Create tasks in a **Notion** database
- Draft emails and save them to your **Gmail Drafts** folder (or send via SMTP)

Send natural-language requests to one endpoint; the agent picks the right tool automatically.

---

## Requirements

- Python 3.10+
- Accounts/API keys for Groq, Notion, and Gmail (for email features)

---

## Installation

```bash
git clone <your-repo-url>
cd AI-Tool-Calling

pip install -r requirements.txt
```

---

## Environment variables (`.env`)

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

**Never commit `.env` to Git.** It is listed in `.gitignore`.

### `.env` structure

```env
# Groq — powers the AI agent
GROQ_API_KEY=your_groq_api_key_here

# Notion — creates tasks in your database
NOTION_API_KEY=your_notion_integration_token_here
NOTION_DB_ID=your_notion_database_id_here

# Email mode: "draft" or "send"
EMAIL_MODE=draft

# Gmail — used for drafts (IMAP) and sending (SMTP)
SMTP_EMAIL=your.email@gmail.com
SMTP_PASSWORD=your_16_char_app_password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | API key from Groq Console |
| `NOTION_API_KEY` | Yes (for tasks) | Notion integration secret token |
| `NOTION_DB_ID` | Yes (for tasks) | ID of your Notion Tasks database |
| `EMAIL_MODE` | No | `draft` (default) saves to Gmail Drafts; `send` sends immediately |
| `SMTP_EMAIL` | For email | Your Gmail address |
| `SMTP_PASSWORD` | For email | Gmail App Password (not your login password) |
| `SMTP_HOST` | No | Default: `smtp.gmail.com` |
| `SMTP_PORT` | No | Default: `587` |

---

## How to run

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Then open:

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8000/docs | Swagger UI — test the API in your browser |
| http://127.0.0.1:8000/redoc | Alternative API documentation |

---

## API endpoint

### `POST /api/agent`

Send a natural-language request. The agent routes it to the correct tool.

**Request body:**

```json
{
  "text": "Your request in plain English"
}
```

**Example — create a Notion task:**

```json
{
  "text": "Create a task called Review API docs, due 2026-07-15, High priority, assign to John."
}
```

**Example — draft an email:**

```json
{
  "text": "Draft an email to someone@example.com with subject Deadline Update. Tell them the deadline is July 15, 2026."
}
```

**Example response (Notion task):**

```json
{
  "tools_used": ["create_task"],
  "task_result": {
    "status": "Successfully created in Notion!",
    "url": "https://www.notion.so/..."
  },
  "email_result": null
}
```

**Example response (email draft):**

```json
{
  "tools_used": ["email_draft"],
  "task_result": null,
  "email_result": {
    "status": "Draft saved to Gmail Drafts folder",
    "from": "your.email@gmail.com",
    "recipient": "someone@example.com",
    "subject": "Deadline Update",
    "body": "The deadline is July 15, 2026."
  }
}
```

### Test with curl

```bash
curl -X POST "http://127.0.0.1:8000/api/agent" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"Draft an email to test@example.com with subject Hello and body This is a test.\"}"
```

### Test with PowerShell

```powershell
$body = '{"text": "Create a task called Tool calling, due 2026-07-09, Low priority, assign to me."}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/agent" -Method POST -ContentType "application/json" -Body $body
```

---

## Setting up external services

### 1. Groq API

1. Go to [Groq Console](https://console.groq.com/)
2. Sign up or log in
3. Open **API Keys** → **Create API Key**
4. Copy the key into `.env` as `GROQ_API_KEY`

**Docs:** https://console.groq.com/docs

**Model used:** `llama-3.3-70b-versatile`

---

### 2. Notion API

1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Click **New integration** → name it (e.g. `Ai Tool Calling`)
3. Copy the **Internal Integration Secret** → `NOTION_API_KEY` in `.env`
4. Open your **Tasks Tracker** database in Notion
5. Click **⋯** → **Connections** → add your integration
6. Copy the database ID from the URL:

   ```
   https://www.notion.so/workspace/39699097dbf380c689b3c918bc2d0212?v=...
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                 This is NOTION_DB_ID
   ```

**Required database columns:**

| Column | Type |
|--------|------|
| Task name | Title |
| Status | Status |
| Due date | Date |
| Priority | Select (High, Medium, Low) |
| Description | Text |

**Docs:** https://developers.notion.com/

---

### 3. Gmail (SMTP + IMAP for drafts)

Used when `EMAIL_MODE=draft` (saves to Gmail Drafts) or `EMAIL_MODE=send` (sends email).

#### Step 1 — Enable 2-Step Verification

1. [Google Account → Security](https://myaccount.google.com/security)
2. Turn on **2-Step Verification**

#### Step 2 — Create an App Password

1. In Security, open **App passwords**
2. App name: `AI Tool Calling`
3. Copy the 16-character password → `SMTP_PASSWORD` in `.env`

> Use the **App Password**, not your normal Gmail password.

#### Step 3 — Enable IMAP (for draft mode)

1. Gmail → **Settings** → **See all settings**
2. **Forwarding and POP/IMAP** → **Enable IMAP**
3. Save

#### Step 4 — Add to `.env`

```env
EMAIL_MODE=draft
SMTP_EMAIL=your.email@gmail.com
SMTP_PASSWORD=your_16_char_app_password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

| Mode | Behavior |
|------|----------|
| `EMAIL_MODE=draft` | Saves draft to Gmail **Drafts** folder (no send) |
| `EMAIL_MODE=send` | Sends email immediately via SMTP |

**Gmail SMTP:** `smtp.gmail.com:587` (TLS)  
**Gmail IMAP:** `imap.gmail.com:993` (SSL, used internally for drafts)

---

## Available tools

| Tool | Trigger examples | Result field |
|------|------------------|--------------|
| `create_task` | "Create a task...", "Add to Notion..." | `task_result` |
| `email_draft` | "Draft an email...", "Write an email to..." | `email_result` |

---

## Security notes

- Keep all secrets in `.env` only
- `.env` is gitignored — do not remove it from `.gitignore`
- Share `.env.example` (placeholders only), never your real `.env`
- Use Gmail **App Passwords**, not your account password

---

## Project structure

```
AI-Tool-Calling/
├── main.py              # FastAPI app and agent logic
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── .env                 # Your secrets (local only, not committed)
├── .gitignore
└── README.md
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `model_decommissioned` from Groq | Update model in `main.py` to a current Groq model |
| Notion 404 | Share database with your integration; verify `NOTION_DB_ID` |
| Email login failed | Use Gmail App Password, not normal password |
| Draft not in Gmail | Enable IMAP in Gmail settings; check `SMTP_EMAIL` matches the account you're viewing |
| Email sent when you wanted draft | Set `EMAIL_MODE=draft` in `.env` and restart the server |

---

## License

MIT (or your preferred license)
