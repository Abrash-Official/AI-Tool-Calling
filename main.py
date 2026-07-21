import os
import json
import logging
import smtplib
import imaplib
import time
import requests
import traceback
from datetime import datetime
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
# Health Check Endpoint for Render
# ==========================================
@app.get("/")
@app.get("/healthz")
def health_check():
    """Render will ping this endpoint to check if the deployment was successful."""
    return {"status": "Agent is live and running!"}


# ==========================================
# 2. Live Notion Tool Execution
# ==========================================
def execute_create_notion_task(task_name: str, due_date: str, priority: str, description: str, assignee: str) -> dict:
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


# ==========================================
# 3. Live Todoist Tool Execution
# ==========================================
def execute_create_todoist_task(task_name: str, priority: int = 1, description: str = "", due_string: str = "") -> dict:
    """Creates a task in the user's Todoist Inbox."""
    api_key = os.getenv("TODOIST_API_KEY")
    if not api_key:
        return {"error": "Todoist API Key is missing in .env"}

    url = "https://api.todoist.com/api/v1/tasks"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Safely handle the priority in case the AI passes a text string like "High" instead of an int
    safe_priority = 1
    try:
        if isinstance(priority, str) and not priority.isdigit():
            p_lower = priority.lower()
            if "highest" in p_lower or "4" in p_lower:
                safe_priority = 4
            elif "high" in p_lower or "3" in p_lower:
                safe_priority = 3
            elif "medium" in p_lower or "2" in p_lower:
                safe_priority = 2
            else:
                safe_priority = 1 # Default Normal
        else:
            safe_priority = int(priority)
    except (ValueError, TypeError):
        safe_priority = 1 # Fallback to normal priority if conversion fails entirely

    # Ensure payload is clean and priority is safely an integer
    payload = {
        "content": task_name,
        "description": description,
        "priority": safe_priority
    }
    
    if due_string:
        payload["due_string"] = due_string

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        
        task_data = response.json()
        return {
            "status": "Successfully added to Todoist!", 
            "task_id": task_data.get("id"),
            "url": task_data.get("url")
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Todoist API Error: {response.text if 'response' in locals() else str(e)}")
        return {
            "error": "Failed to create task in Todoist", 
            "details": response.text if 'response' in locals() else str(e)
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
# 4. Updated Groq Tool Schemas
# ==========================================
groq_tools = [
    {
        "type": "function",
        "function": {
            "name": "create_notion_task",
            "description": "Creates a collaborative assignment in the Notion Tasks database. ONLY use this tool if the user explicitly asks to add the task TO Notion. If the user explicitly asks NOT to put it in Notion, do not use this tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "A short title for the task."},
                    "due_date": {"type": "string", "description": "The deadline, strictly formatted as YYYY-MM-DD. Calculate this based on the current date context provided."},
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
            "name": "create_todoist_task",
            "description": "Creates a task in Todoist. This is the DEFAULT tool for adding, creating, or making any tasks. Use this for ALL task requests unless the user explicitly asks to put it in Notion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "A short title for the task."},
                    "priority": {"type": "integer", "enum": [1, 2, 3, 4], "description": "Strictly an integer priority level: 4 (Highest/Red), 3 (High/Orange), 2 (Medium/Blue), 1 (Normal/Grey). NEVER supply a string."},
                    "description": {"type": "string", "description": "Detailed notes or breakdown of the task."},
                    "due_string": {"type": "string", "description": "Natural language due date, e.g. 'tomorrow at 5pm' or 'next monday' or 'morning'."}
                },
                "required": ["task_name"],
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
# 5. Core Endpoint Route
# ==========================================
@app.post("/api/agent")
async def run_agent(request: UserRequest):
    try:
        # Dynamically calculate current date and time for the AI's context
        current_datetime = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are a precise routing and data formatting agent.\n"
                        f"CURRENT DATE AND TIME: {current_datetime}\n\n"
                        "ROUTING RULES:\n"
                        "- By default, if the user asks to add a task, ALWAYS use the `create_todoist_task` tool.\n"
                        "- ONLY use the `create_notion_task` tool if the user explicitly requests the task be added TO Notion.\n"
                        "- If the user says something like 'don't add to Notion' or 'not Notion', you MUST respect that negative constraint and default back to `create_todoist_task`.\n"
                        "- Use `email_draft` when the user wants to draft an email. Always use a full email address for the recipient.\n\n"
                        "DATA TYPE RULES:\n"
                        "- BEFORE calling a tool, analyze the required data types for its parameters.\n"
                        "- If a parameter requires an integer (like Todoist priority), output ONLY a pure integer (e.g., 3), NEVER a string (e.g., '3' or 'High').\n"
                        "- If a parameter requires a specific date format (e.g., YYYY-MM-DD for Notion), calculate it accurately based on the CURRENT DATE AND TIME provided above (e.g., if user says 'tomorrow morning', convert it to the correct YYYY-MM-DD).\n"
                        "- For Todoist, you can safely pass natural language times like 'tomorrow morning' directly to the due_string parameter."
                    )
                },
                {"role": "user", "content": request.text}
            ],
            tools=groq_tools,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        tool_calls = message.tool_calls
        
        output = {"tools_used": [], "task_result": None, "todoist_result": None, "email_result": None}
        
        if not tool_calls:
            return {"status": "No tools required", "response": message.content}
            
        for tool_call in tool_calls:
            func_name = tool_call.function.name
            
            # Catch parsing errors specifically if the AI outputs badly formatted JSON
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as decode_error:
                raise ValueError(f"AI produced invalid arguments format: {decode_error}")
                
            output["tools_used"].append(func_name)
            
            if func_name == "create_notion_task":
                output["task_result"] = execute_create_notion_task(
                    task_name=args.get("task_name", "Untitled Task"),
                    due_date=args.get("due_date", ""),
                    priority=args.get("priority", "Medium"),
                    description=args.get("description", ""),
                    assignee=args.get("assignee", "Unassigned")
                )
            elif func_name == "create_todoist_task":
                output["todoist_result"] = execute_create_todoist_task(
                    task_name=args.get("task_name", "Untitled Task"),
                    priority=args.get("priority", 1),
                    description=args.get("description", ""),
                    due_string=args.get("due_string", "")
                )
            elif func_name == "email_draft":
                output["email_result"] = execute_email_draft(
                    recipient=args.get("recipient", ""),
                    subject=args.get("subject", ""),
                    body=args.get("body", ""),
                )

        return output

    except Exception as e:
        # Instead of hiding the error, capture the full traceback for debugging!
        error_details = str(e)
        full_traceback = traceback.format_exc()
        
        logger.error(f"Agent crashed! Error: {error_details}\nTraceback:\n{full_traceback}")
        
        # Return a 500 error but with the EXACT reason why it failed to the user
        raise HTTPException(
            status_code=500, 
            detail={
                "message": "Agent execution failed due to an internal error.",
                "error": error_details,
                "traceback": full_traceback.split("\n") # Splits into list for readable JSON format
            }
        )