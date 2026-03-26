import logging
import httpx
from fastapi import FastAPI, Request, BackgroundTasks, Form
from fastapi.responses import Response
from twilio.rest import Client
import uvicorn

from common.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="WhatsApp Bot Service")

ENTRY_AGENT_URL = "http://localhost:8010/query"

# Initialize Twilio Client
if settings.twilio_account_sid and settings.twilio_auth_token:
    twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
else:
    twilio_client = None
    logger.warning("Twilio credentials (SID/Auth Token) are missing. Bot will not be able to send replies.")


async def _process_and_reply(user_query: str, sender: str):
    """Call the Entry Agent and send the output back to the user via Twilio."""
    logger.info(f"Starting background task for {sender}: '{user_query}'")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(ENTRY_AGENT_URL, json={"query": user_query})
            resp.raise_for_status()
            data = resp.json()

            result = data.get("result")
            error = data.get("error")
            status = data.get("status")

            if result:
                reply_text = str(result)
            elif error:
                reply_text = f"Error: {error}"
            else:
                reply_text = f"Task finished with status '{status}' but no result was returned."

    except httpx.RequestError as e:
        reply_text = f"Failed to reach the Entry Agent. Is it running on port 8010?\nError: {e}"
        logger.error(f"Entry Agent connection error: {e}")
    except Exception as e:
        reply_text = f"An error occurred while processing your request: {e}"
        logger.error(f"Unexpected error calling Entry Agent: {e}")

    # Send asynchronous reply via Twilio REST API
    if twilio_client:
        try:
            twilio_client.messages.create(
                body=reply_text,
                from_=settings.twilio_whatsapp_from,
                to=sender
            )
            logger.info(f"Successfully sent reply to {sender}")
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message via Twilio: {e}")
    else:
        logger.error("No Twilio client initialized. Cannot send reply.")


@app.post("/webhook")
async def twilio_webhook(
    background_tasks: BackgroundTasks,
    Body: str = Form(default=""),
    From: str = Form(default="")
):
    """
    Twilio webhook endpoint for incoming WhatsApp messages.
    Sends an immediate TwiML acknowledgement, then processes the query in the background.
    """
    logger.info(f"Received WhatsApp message from {From}: {Body}")

    if Body.strip():
        background_tasks.add_task(_process_and_reply, Body, From)
        xml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>Thinking...</Message>
</Response>"""
        return Response(content=xml_response, media_type="application/xml")
    else:
        xml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>I received your message, but it was empty or contained unsupported media.</Message>
</Response>"""
        return Response(content=xml_response, media_type="application/xml")


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "whatsapp-bot-server"}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    )
    logger.info("Starting WhatsApp bot server on port 8030")
    uvicorn.run(app, host="0.0.0.0", port=8030)
