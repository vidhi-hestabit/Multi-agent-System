from __future__ import annotations
from common.errors import MCPError
from mcp_server.app import mcp
from mcp_server.tools.composio_tool import handle as composio_handle

TOOL_NAME        = "send_message"
TOOL_DESCRIPTION = "Send a message via GMAIL, SLACK, TELEGRAM, or DISCORD."

_ACTIONS = {
    "GMAIL":    "GMAIL_SEND_EMAIL",
    "SLACK":    "SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL",
    "TELEGRAM": "TELEGRAM_SEND_MESSAGE",
    "DISCORD":  "DISCORD_SEND_MESSAGE",
}


@mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
async def handle(app: str, user_id: str, to: str, body: str, subject: str = "") -> dict:
    app_upper = app.strip().upper()
    action    = _ACTIONS.get(app_upper)

    if not action:
        raise MCPError(f"{app_upper} not supported. Use: {list(_ACTIONS)}", tool=TOOL_NAME)
    if not to.strip():
        raise MCPError("Recipient 'to' is required.", tool=TOOL_NAME)
    if not body.strip():
        raise MCPError("Message body is required.", tool=TOOL_NAME)

    if app_upper == "GMAIL":
        params = {"recipient_email": to, "subject": subject or "Message from AI Agent", "body": body}
    elif app_upper == "SLACK":
        params = {"channel": to, "text": body}
    elif app_upper == "TELEGRAM":
        params = {"chat_id": to, "text": body}
    else:
        params = {"channel_id": to, "content": body}

    result = await composio_handle(action=action, user_id=user_id, params=params)

    if result.get("success"):
        return {"success": True, "app": app_upper, "to": to,
                "message": f"Message sent via {app_upper} to {to}."}

    raise MCPError(f"Failed sending via {app_upper}: {result.get('error','unknown')}", tool=TOOL_NAME)