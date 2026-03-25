
import os
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv(".env.local")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ENTRY_AGENT_URL = "http://localhost:8010/query"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text("Hello! I am your Multi-Agent System Bot. Send me a query and I'll route it to the agents.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward the user's message to the Entry Agent and return the response."""
    user_query = update.message.text
    status_msg = await update.message.reply_text("Thinking...")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                ENTRY_AGENT_URL,
                json={"query": user_query}
            )
            response.raise_for_status()
            data = response.json()
            
            result = data.get("result")
            error = data.get("error")
            status = data.get("status")
            
            if result:
                reply_text = result
            elif error:
                reply_text = f"Error: {error}"
            else:
                reply_text = f"Task finished with status '{status}' but no result was returned."
                
        # Edit the status message with the final result
        await status_msg.edit_text(reply_text)
    except httpx.RequestError as e:
        await status_msg.edit_text(f"Failed to reach the Entry Agent. Is it running on port 8010?\nError: {e}")
    except Exception as e:
        await status_msg.edit_text(f"An error occurred: {e}")

def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.startswith("8732386572:AAFfZ"):
        pass

    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is not set in .env.local")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Starting Telegram Bot... Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
