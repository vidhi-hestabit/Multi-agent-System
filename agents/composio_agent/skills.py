from common.a2a_types import AgentSkill


SKILLS = [
   AgentSkill(
       id="send_message",
       name="Send Message",
       description="Send messages via Gmail, Slack, Telegram, or Discord using Composio.",
       input_modes=["text", "data"],
       output_modes=["text"],
       tags=["send", "email", "slack", "telegram", "discord", "message"],
       examples=[
           "Send this via Gmail",
           "Share via Slack",
           "Send to Telegram",
           "Forward via Discord",
       ],
   ),
]


