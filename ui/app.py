from __future__ import annotations
import asyncio
import concurrent.futures
import gradio as gr

from common.config import get_settings
from common.logging import setup_logging, get_logger
from ui.api_client import OrchestratorClient, AgentDirectClient
from ui.components.news_card import format_news_section
from ui.components.weather_card import format_weather_card
from ui.components.report_viewer import format_report

setup_logging()
_settings = get_settings()
logger    = get_logger("ui")

_orch_client = OrchestratorClient()


# Async bridge
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# Response parsing helpers
def _extract_panels(results: list[dict]) -> tuple[str, str, str]:
    news_html = weather_html = report_html = ""

    for r in results:
        if not r.get("success"):
            continue
        agent      = r.get("agent", "")
        data       = r.get("data") or {}
        structured = data.get("structured") or {}

        if agent == "news_agent" and structured:
            articles = structured.get("articles", [])
            if articles:
                news_html = format_news_section(articles)

        elif agent == "weather_agent" and structured:
            w = structured.get("weather") or structured
            if w:
                weather_html = format_weather_card(w)

        elif agent == "report_agent" and structured:
            md = structured.get("markdown", "")
            if md:
                report_html = format_report(md)

    return news_html, weather_html, report_html


def _find_input_required(results: list[dict]) -> tuple[bool, str, str, str]:
    for r in results:
        data  = r.get("data") or {}
        state = data.get("state", "")
        if state == "input-required":
            return True, data.get("text", ""), r.get("agent", ""), data.get("task_id", "")
    return False, "", "", ""


# Query handlers
async def _do_fresh_query(query: str) -> dict:
    try:
        resp = await _orch_client.query(query)
    except Exception as exc:
        return {
            "summary": f"Could not reach the orchestrator: {exc}\n\nMake sure all services are running.",
            "news_html": "",
            "weather_html": "",
            "report_html": "",
            "input_required": False,
            "pending_agent": "",
            "pending_task_id": "",
        }
    results = resp.get("results", [])
    summary = resp.get("summary", "")
    news_html, weather_html, report_html = _extract_panels(results)
    found, question, agent, task_id      = _find_input_required(results)

    return {
        "summary":         question if found else summary,
        "news_html":       news_html,
        "weather_html":    weather_html,
        "report_html":     report_html,
        "input_required":  found,
        "pending_agent":   agent,
        "pending_task_id": task_id,
    }


async def _do_resume(agent_name: str, task_id: str, reply: str) -> dict:
    client = AgentDirectClient(agent_name)
    try:
        data = await client.resume(task_id=task_id, reply=reply)
    except Exception as exc:
        return {
            "summary":         f"Error communicating with agent: {exc}",
            "news_html":       "",
            "weather_html":    "",
            "report_html":     "",
            "input_required":  False,
            "pending_agent":   "",
            "pending_task_id": "",
        }
    status = data.get("status", {})
    state = status.get("state", "")
    parts = (status.get("message") or {}).get("parts", [])
    agent_text = parts[0].get("text", "") if parts else ""
    still_waiting = state == "input-required"

    report_html = ""
    for artifact in data.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("type") == "data":
                md = (part.get("data") or {}).get("markdown", "")
                if md:
                    report_html = format_report(md)

    return {
        "summary":         agent_text,
        "news_html":       "",
        "weather_html":    "",
        "report_html":     report_html,
        "input_required":  still_waiting,
        "pending_agent":   agent_name if still_waiting else "",
        "pending_task_id": task_id    if still_waiting else "",
    }

# Gradio event handlers
def submit_message(user_text: str, history: list, session: dict):
    user_text = (user_text or "").strip()
    if not user_text:
        return history, session, "", "", "", ""
    history = list(history or [])
    session = dict(session or {})
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": "Processing your request..."})
    if session.get("input_required") and session.get("pending_task_id"):
        result = _run(_do_resume(
            agent_name=session["pending_agent"],
            task_id=session["pending_task_id"],
            reply=user_text,
        ))
    else:
        result = _run(_do_fresh_query(user_text))
    session["input_required"]  = result.get("input_required", False)
    session["pending_agent"]   = result.get("pending_agent", "")
    session["pending_task_id"] = result.get("pending_task_id", "")
    agent_reply = result.get("summary", "")
    if result.get("input_required"):
        bot_text = f"Action required:\n\n{agent_reply}"
    else:
        bot_text = agent_reply or "Done."
    history[-1] = {"role": "assistant", "content": bot_text}
    return (
        history,
        session,
        result.get("news_html",    ""),
        result.get("weather_html", ""),
        result.get("report_html",  ""),
        "",   # clear input box
    )

def clear_all(_session: dict):
    return [], {}, "", "", "", ""

# Layout
EXAMPLES = [
    "What is the weather in London?",
    "Latest news about artificial intelligence",
    "Weather in Tokyo and related news",
    "Generate a report about climate change",
    "Send a report about AI trends via Gmail",
    "Send the latest tech news report via Slack",
]

CUSTOM_CSS = """
body, .gradio-container {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    background: #ffffff;
    color: #111827;
}

/* Header */
.main-header {
    text-align: center;
    padding: 28px 0 12px;
    border-bottom: 1px solid #e5e7eb;
    margin-bottom: 16px;
}
.main-header h1 {
    font-size: 1.8rem;
    font-weight: 800;
    color: #111827;
    margin: 0 0 6px 0;
}
.main-header p {
    font-size: 0.875rem;
    color: #6b7280;
}

/* badges */
.badge {
    display: inline-block;
    background: #f3f4f6;
    color: #374151;
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 0.75rem;
    font-weight: 500;
    margin: 0 3px;
}

/* side panel labels */
.panel-label {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6b7280;
    margin-bottom: 8px;
}

/* CHATBOT FIX */
#chatbot {
    background: #ffffff;
}

/* user message */
#chatbot .message.user {
    background: #e8f0ff !important;
    color: #111827 !important;
    border-radius: 12px;
}

/* assistant message */
#chatbot .message.bot {
    background: #f3f4f6 !important;
    color: #111827 !important;
    border-radius: 12px;
}

/* force text visibility */
#chatbot .message * {
    color: #111827 !important;
}

/* textbox */
textarea, input {
    color: #111827 !important;
    background: #ffffff !important;
}

/* remove footer */
footer {
    display: none !important;
}
"""


with gr.Blocks(css=CUSTOM_CSS, title="Multi-Agent AI System") as demo:

    gr.HTML("""
    <div class="main-header">
      <h1>Multi-Agent AI System</h1>
      <p>
        <span class="badge">Groq LLM</span>
        <span class="badge">LangGraph</span>
        <span class="badge">MCP Tools</span>
        <span class="badge">A2A Protocol</span>
        <span class="badge">Composio</span>
      </p>
    </div>
    """)

    session_state = gr.State({})

    with gr.Row():
        with gr.Column(scale=5):
            chatbot = gr.Chatbot(label="Conversation", elem_id="chatbot", height=500)

            with gr.Row():
                msg_box = gr.Textbox(
                    placeholder="Ask anything — weather, news, reports, or reply to agent prompts...",
                    show_label=False,
                    lines=1,
                    scale=8,
                    container=False,
                )
                send_btn  = gr.Button("Send",  variant="primary",   scale=1, min_width=80)
                clear_btn = gr.Button("Clear", variant="secondary", scale=1, min_width=80)

            gr.Examples(
                examples=EXAMPLES,
                inputs=msg_box,
                label="Quick examples",
                examples_per_page=6,
            )

        with gr.Column(scale=3):
            gr.HTML('<div class="panel-label">Weather</div>')
            weather_panel = gr.HTML(value="", label="Weather")

            gr.HTML('<div class="panel-label">News</div>')
            news_panel = gr.HTML(value="", label="News")

            gr.HTML('<div class="panel-label">Report</div>')
            report_panel  = gr.HTML(value="", label="Report")

    _inputs  = [msg_box, chatbot, session_state]
    _outputs = [chatbot, session_state, news_panel, weather_panel, report_panel, msg_box]

    send_btn.click(fn=submit_message, inputs=_inputs, outputs=_outputs)
    msg_box.submit(fn=submit_message, inputs=_inputs, outputs=_outputs)
    clear_btn.click(
        fn=clear_all,
        inputs=[session_state],
        outputs=[chatbot, session_state, news_panel, weather_panel, report_panel, msg_box],
    )

def main():
    settings = get_settings()
    logger.info("ui_starting", port=settings.ui_port)
    demo.launch(server_name="0.0.0.0", server_port=settings.ui_port, show_error=True, share=False)

if __name__ == "__main__":
    main()