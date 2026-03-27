# Multi-agent System
A production-ready multi-agent AI system built on the **A2A (Agent-to-Agent) protocol** and **MCP (Model Context Protocol)**. Agents collaborate dynamically to answer queries — fetching weather, news, generating reports, querying databases, answering legal questions, and sending messages via Gmail/Slack/Telegram/Discord.

## Architecture of system -

[Go to architecture file](Architecture.md)

## Flow 

 user query => `entry agent` (Blackboard at port 8010 )-> To read/write context
                |
            LLM  plans output required
                |
            creates task in InMemoryTaskStore
                |
            fires resolver
                | 
            => `Resolver Reads Registry`
                |
            checks which agents are eligible to run (requirements met, produces needed)
                |
            calls agents via JSON RPC2.0 POST/
                |
            => `Each Agent`
                |
            Reads context from Entry Agent via GET/tasks/{id}/context
                |
            entry agent reruns resolver
                |
            next eligible agent fires automatically 

## Agents & Ports

| Agent | Port | What it does |
|---|---|---|
| MCP Server | 8000 | Tool gateway — weather, news, composio, SQL, RAG |
| News Agent | 8001 | Fetches & summarizes news via NewsData.io |
| Weather Agent | 8002 | Fetches current weather via OpenWeatherMap |
| Report Agent | 8003 | Generates Markdown reports from context |
| SQL Agent | 8005 | Answers Chinook music database questions |
| RAG Agent | 8006 | Answers Indian law questions via FAISS |
| Composio Agent | 8008 | Sends content via Gmail/Slack/Telegram/Discord |
| Entry Agent | 8010 | Coordinator — task store, resolver, LLM planner |

## Get your API keys here:

Groq LLM: https://console.groq.com/keys

NewsData.io: https://newsdata.io/search-dashboard

OpenWeatherMap: https://home.openweathermap.org/api_keys

Composio: https://app.composio.dev

## To perform local setup :

Run : 

- uv sync --dev

- source .venv/bin/activate

## Terminal 1 — MCP Server (start first)
uv run python -m mcp_server.main

## Terminal 2 — Weather Agent
uv run python -m agents.weather_agent.main

## Terminal 3 — News Agent
uv run python -m agents.news_agent.main

## Terminal 4 — Report Agent
uv run python -m agents.report_agent.main

## Terminal 5 — SQL Agent
uv run python -m agents.sql_agent.main

## Terminal 6 — RAG Agent
uv run python -m agents.rag_agent.main

## Terminal 7 — Composio Agent
uv run python -m agents.composio_agent.main

## Terminal 8 — Entry Agent (start last)
uv run python -m agents.entry_agent.main

## Terminal 8 — Telegram Bot Service
uv run python -m telegram_bot

## UI 
Open index.html directly.

## Run using Docker

- docker compose build 
- docker compose up
- Open the index.html

## Dependencies for the system :

#### Core framework-
uv add fastapi "uvicorn[standard]" httpx pydantic pydantic-settings python-dotenv

#### LLM-
uv add groq

#### MCP-
uv add mcp

#### Utilities-
uv add tenacity structlog python-dateutil anyio

#### Email-
uv add aiosmtplib

## Example Test Queries

All queries below have been tested and verified working. Please type them directly in the UI chat box.

### Weather

what is the weather in delhi

---

### News

give latest news on donald trump

---
### Normal Chat Queries
hello, hi, what is your name, how can u help me, write a short story and email at your@gmail.com

### SQL Database (Chinook Music DB)

`how many artists are there in the music database` 
COUNT = 275 

`how many tables are there in database` 
COUNT = 11

`list the name of tables in database` 
Album, Artist, Customer, Employee, Genre... 

`list all columns of table Artist` 
ArtistId (INTEGER), Name (NVARCHAR) 

`list all artists in artists table` 
275 rows — AC/DC, Accept, Aerosmith... 

---

### Email via Gmail (Composio)

- Requires `COMPOSIO_API_KEY` configured and Gmail account connected via Composio OAuth.

`email me weather in delhi at your@gmail.com` 
Sent via GMAIL to 'your@gmail.com'. 

`make a report of tables in database and email me at your@gmail.com` 
Report generated + emailed 

`fetch the details of table from the database and make a report of it and email me at your@gmail.com` 
DB details report emailed 

`can you make a report of artists in artists table and email me at your@gmail.com` 
Artists report emailed 

---

### Report Agent Queries
1. give me a report for weather in delhi
2. fetch latest news about donald trump and make a report of it 
3. send a report on pollution to your@gmail.com

---

### WhatsApp Integration

You can send queries and receive full AI responses directly on WhatsApp

**Setup :**
1. Setup a Meta WhatsApp Developer App (https://developers.facebook.com).
2. Connect your WhatsApp Business account via Composio (https://app.composio.dev).
3. Set your internal config in `.env.local`:
   - `WHATSAPP_VERIFY_TOKEN`: Some secure string (e.g. `nexus_whatsapp_verify`)
   - `WHATSAPP_PHONE_NUMBER_ID`: Your Meta-assigned phone number ID
4. Start the Nexus MAS using Docker (`docker compose up`)
5. Expose the gateway: `ngrok http 8015`
6. In Meta Dashboard → Webhooks → Edit Subscription:
   - Callback URL: `https://<ngrok-url>/whatsapp/webhook`
   - Verify Token: The string you set above
   - Subscribe to `messages` field
7. Send a WhatsApp message to your business number!

Example WhatsApp queries:
- `what is the weather in delhi`
- `fetch the details of table from the database and make a report of it`

---

### Multi-Agent Chained Queries

These queries trigger **multiple agents** in sequence automatically:

`what is the weather in delhi? if it is more than 20 degrees then send me a report of artists in artists table at your@gmail.com` 
Weather → SQL → Report → Composio | Report emailed with weather + artists data 

`fetch the details of table from the database and make a report of it and email me at your@gmail.com` 
SQL → Report → Composio | Full DB report emailed |

---

