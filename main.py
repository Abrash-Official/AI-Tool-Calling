import os
import json
import logging
import smtplib
import imaplib
import time
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv

# 1. Load environment variables securely
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("groq-agent")

app = FastAPI(title="Free AI Tool-Calling Agent")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ==========================================
# 2. Live Notion Tool Execution
# ==========================================
def execute_create_task(task_name: str, due_date: str, priority: str, description: str, assignee: str) -> dict:
    """Sends a formatted HTTP POST request to the Notion API to create a row in the Tasks Tracker."""
    
    notion_api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DB_ID")
    
    if not notion_api_key or not database_id:
        return {"error": "Notion credentials are missing in the .env file."}

    url = "https://api.notion.com/v1/pages"
    
    headers = {
        "Authorization": f"Bearer {notion_api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    # Format the description to include the assignee since Notion's native 
    # Person property requires complex UUID lookups.
    full_description = f"Assignee: {assignee}\n\n{description}"

    # Map directly to your database column names and property types
    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            "Task name": {
                "title": [{"text": {"content": task_name}}]
            },
            "Status": {
                "status": {"name": "Not started"} # Defaulting to Not started
            },
            "Due date": {
                "date": {"start": due_date} # Must be YYYY-MM-DD
            },
            "Priority": {
                "select": {"name": priority} # High, Medium, or Low
            },
            "Description": {
                "rich_text": [{"text": {"content": full_description}}]
            }
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return {"status": "Successfully created in Notion!", "url": response.json().get("url")}
    except requests.exceptions.RequestException as e:
        logger.error(f"Notion API Error: {response.text}")
        notion_error = None
        try:
            notion_error = response.json().get("message")
        except Exception:
            pass
        return {
            "error": "Failed to create task in Notion",
            "details": notion_error or str(e),
            "hint": "Share your Notion database with the 'Ai Tool Calling' integration and verify NOTION_DB_ID in .env.",
        }


# Placeholder functions for your other tools
def execute_calculator(expression: str) -> float:
    return float(eval(expression))

def execute_document_search(query: str) -> str:
    return "Mock search result."

def save_gmail_draft(from_email: str, app_password: str, recipient: str, subject: str, body: str) -> None:
    """Save a draft to the Gmail Drafts folder via IMAP."""
    message = MIMEText(body, "plain", "utf-8")
    message["From"] = from_email
    message["To"] = recipient
    message["Subject"] = subject

    imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
    password = app_password.replace(" ", "")

    with imaplib.IMAP4_SSL(imap_host) as mail:
        mail.login(from_email, password)
        mail.append(
            "[Gmail]/Drafts",
            "\\Draft",
            imaplib.Time2Internaldate(time.time()),
            message.as_bytes(),
        )


def execute_email_draft(recipient: str, subject: str, body: str) -> dict:
    draft = {"recipient": recipient, "subject": subject, "body": body}
    email_mode = os.getenv("EMAIL_MODE", "draft").lower()
    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if "@" not in recipient:
        return {
            "error": "Invalid recipient",
            "hint": "Provide a full email address, e.g. you@gmail.com",
            "draft": draft,
        }

    if email_mode != "send":
        if not smtp_email or not smtp_password:
            return {
                "error": "Gmail credentials missing for draft saving",
                "hint": "Add SMTP_EMAIL and SMTP_PASSWORD (Gmail App Password) to .env.",
                "draft": draft,
            }
        try:
            save_gmail_draft(smtp_email, smtp_password, recipient, subject, body)
            return {
                "status": "Draft saved to Gmail Drafts folder",
                "from": smtp_email,
                **draft,
            }
        except imaplib.IMAP4.error as e:
            logger.error(f"Gmail IMAP error: {e}")
            return {
                "error": "Failed to save draft to Gmail",
                "details": str(e),
                "hint": "Enable IMAP in Gmail: Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP.",
                "draft": draft,
            }
        except Exception as e:
            logger.error(f"Gmail draft error: {e}")
            return {"error": "Failed to save draft to Gmail", "details": str(e), "draft": draft}

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not smtp_email or not smtp_password:
        return {
            "error": "Email sending is not configured",
            "hint": "Add SMTP_EMAIL and SMTP_PASSWORD to .env, or keep EMAIL_MODE=draft for draft-only.",
            "draft": draft,
        }

    message = MIMEMultipart()
    message["From"] = smtp_email
    message["To"] = recipient
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_email, smtp_password.replace(" ", ""))
            server.sendmail(smtp_email, recipient, message.as_string())

        return {"status": "Email sent successfully", "from": smtp_email, **draft}
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed")
        return {
            "error": "Email login failed",
            "hint": "Use a Gmail App Password (not your normal password).",
            "draft": draft,
        }
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return {"error": "Failed to send email", "details": str(e), "draft": draft}


# ==========================================
# 3. Updated Groq Tool Schemas
# ==========================================
groq_tools = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Creates an assignment in the Notion Tasks Tracker database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "A short title for the task."},
                    "due_date": {"type": "string", "description": "The deadline, strictly formatted as YYYY-MM-DD."},
                    "priority": {"type": "string", "enum": ["High", "Medium", "Low"], "description": "Task priority level."},
                    "description": {"type": "string", "description": "Detailed breakdown of the task requirements."},
                    "assignee": {"type": "string", "description": "The name of the person responsible for the task."}
                },
                "required": ["task_name", "due_date", "priority", "description", "assignee"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_draft",
            "description": "Drafts an email without sending it. Use when the user wants to write, compose, or draft an email message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "The recipient email address or name."},
                    "subject": {"type": "string", "description": "The email subject line."},
                    "body": {"type": "string", "description": "The full email body text."},
                },
                "required": ["recipient", "subject", "body"],
            },
        },
    },
]

class UserRequest(BaseModel):
    text: str

# ==========================================
# 4. Core Endpoint Route
# ==========================================
@app.post("/api/agent")
async def run_agent(request: UserRequest):
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a precise routing agent. Use create_task for Notion task/todo requests (always format dates as YYYY-MM-DD). Use email_draft when the user wants to write, compose, or draft an email (draft only, do not mention sending). Always use a full email address for the recipient."},
                {"role": "user", "content": request.text}
            ],
            tools=groq_tools,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        tool_calls = message.tool_calls
        
        output = {"tools_used": [], "task_result": None, "email_result": None}
        
        if not tool_calls:
            return {"status": "No tools required", "response": message.content}
            
        for tool_call in tool_calls:
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            output["tools_used"].append(func_name)
            
            if func_name == "create_task":
                output["task_result"] = execute_create_task(
                    task_name=args["task_name"],
                    due_date=args["due_date"],
                    priority=args["priority"],
                    description=args["description"],
                    assignee=args["assignee"]
                )
            elif func_name == "email_draft":
                output["email_result"] = execute_email_draft(
                    recipient=args["recipient"],
                    subject=args["subject"],
                    body=args["body"],
                )

        return output

    except Exception as e:
        logger.error(f"Execution error: {str(e)}")
        raise HTTPException(status_code=500, detail="Agent failure.")