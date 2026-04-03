# Nexus Multi-Agent System

A production-ready Multi-Agent AI system built on the **A2A (Agent-to-Agent) protocol** and **MCP (Model Context Protocol)**. 
Nexus agents collaborate dynamically to execute complex multi-step queries: fetching weather, summarizing news, writing reports, running SQL database queries, performing semantic searches for legal queries (RAG), and sending external messages via Gmail, Slack, and WhatsApp.

---

##  System Architecture

The project is built on three main execution pillars:
1. **Persistent Storage & Context**: MongoDB-backed session metadata and chat history, paired with Pinecone for dense vector semantic history retrieval.
2. **Intelligent Orchestration**: An **Entry Agent** (the planner) that creates an implicit DAG of task dependencies based on the user's intent.
3. **Context-Aware Workers**: Specialized micro-service agents that resolve ambiguous queries using Blackboard memory injection.

---

##  Agents & Ports

| Component | Port | What it does |
|---|---|---|
| **MCP Server** | 8000 | Centralized Tool gateway expose file operations, specific integrations, etc. |
| **News Agent** | 8001 | Fetches & summarizes news via NewsData.io |
| **Weather Agent** | 8002 | Fetches multi-city current weather via OpenWeatherMap |
| **Report Agent** | 8003 | Generates structured Markdown reports from the Blackboard context |
| **SQL Agent** | 8005 | Natural-language query converter for the Chinook Music SQL database |
| **RAG Agent** | 8006 | Legal document semantic search agent (via local FAISS index) |
| **Chat Agent** | 8009 | Context-aware general conversational agent |
| **Composio Agent**| 8008 | Omnichannel messaging pipeline (Gmail, Slack, Telegram, WhatsApp) |
| **Entry Agent** | 8010 | The master coordinator — houses the Task Store, Resolver, and Planner |
| **Auth Server** | 8020 | Manages JWTs, frontend sessions, and persists context onto MongoDB & Pinecone |
| **Baileys Node** | 8080 | Headless Baileys native WhatsApp driver mimicking the Evolution API |

---

##  Setup & Execution

### Prerequisites
1. Install Python `uv` package manager. 
2. Ensure you have MongoDB running locally (`mongodb://localhost:27017` or Atlas).
3. Populate `.env.local` with your API keys (Groq, Composio, Pinecone, OpenWeatherMap, NewsData.io).

### Development (Local Run)
Install dependencies using `uv`:
```bash
uv sync --dev
source .venv/bin/activate
```
Instead of Docker, you can run individual microservices in separate terminals:
```bash
#  Tool Gateway
uv run python -m mcp_server.main

#  Workers (run individually)
uv run python -m agents.weather_agent.main
uv run python -m agents.news_agent.main
uv run python -m agents.report_agent.main
uv run python -m agents.sql_agent.main
uv run python -m agents.rag_agent.main
uv run python -m agents.chat_agent.main
uv run python -m agents.composio_agent.main

#  Master Orchestrator
uv run python -m agents.entry_agent.main

# Auth Service
uv run python -m auth_server
```

### Production (Docker)
```bash
docker compose build 
docker compose up
```

**Accessing the System:** 
Opening the local `index.html` file in any modern browser connects directly to the Auth Server (`:8020`) and Entry Agent (`:8010`).

---

##  WhatsApp Integration (Native Baileys)

Nexus now features a self-hosted, multi-tenant WhatsApp implementation using **Baileys**. Each user logged into Nexus receives their own isolated WhatsApp instance.

### How to use WhatsApp Integration:
1. **Start the Baileys Driver**:
   ```bash
   cd whatsapp_baileys
   npm install
   node index.js
   ```
   *(Runs the Evolution API proxy on port `8080`)*
2. **Start the Onboarding Gateway**:
   ```bash
   uv run python -m whatsapp_green.main
   ```
   *(Runs the QR onboarding service on port `8031`)*
3. **Link your Account**:
   - In the frontend UI, click to connect WhatsApp, OR manually visit: `http://localhost:8031/connect/{your_nexus_user_id}`
   - Scan the QR code with your WhatsApp app.
4. **Interact**: 
   - You can send text messages *to* the linked WhatsApp number, and the Nexus system will answer them.
   - You can chat in the Web UI: *"send the weather report for Delhi to Vidhi HestaBit on WhatsApp"* to trigger outbound messages.

---

## Example Queries

Here are simple, tested queries demonstrating each primary capability:

**Weather**
- `What is the weather in Delhi?`
- `Generate a report for weather in New York`

**News**
- `Give me the latest news on Artificial Intelligence.`
- `What is the latest news related to finance`

**Database (SQL)**
- `How many artists are in the database?`
- `List the names of all the tables in the database.`

**Legal QA (RAG)**
- `What are the fundamental rights in the Indian Constitution?`
- `Explain the Right to Information Act.`

**Report Generation**
- `Write a formal report on the weather in Tokyo.`
- `Summarize the latest sports news into a report.`

**Messaging**
- `Send an email with the weather report of Delhi to your@gmail.com`
- `Send the latest news about stocks to 9999999999 on WhatsApp`

**Multi-Agent Chains**
- `Fetch the latest news on Apple, write a report on it, and email it to user@gmail.com`
- `What is the weather in Dubai? Send the result to 9999999999 on WhatsApp.`

---

##  External API Keys needed
- **Groq LLM**: https://console.groq.com/keys
- **NewsData.io**: https://newsdata.io/search-dashboard
- **OpenWeatherMap**: https://home.openweathermap.org/api_keys
- **Composio**: https://app.composio.dev
- **Pinecone**: https://app.pinecone.io/

