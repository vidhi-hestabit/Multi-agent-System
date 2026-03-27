# Multi-Agent System — A2A + MCP Protocol Architecture

![alt text](architecture.jpg)

**Protocol: A2A + MCP | Architecture Layering**

## 1. Top-Level Workflow: Request Lifecycle

The architecture is partitioned geographically into four primary regions: User Interfaces, the A2A Agent Network, the MCP Tool Gateway, and the Shared Common Module.

When a query enters the system:
1. **Ingestion (Gateways & Interfaces):** 
   A client (Web UI `index.html`, WhatsApp Webhook, or Telegram Bot) issues an HTTP REST Query. This request lands cleanly into the **Entry Agent** (Port 8010).
2. **Analysis & Planning (`Entry Agent`):**
   The Entry Agent's `_plan_outputs()` routine kicks in, querying the Groq LLM planner. The LLM determines the required output keys to fulfill the user's request. Context hints are injected, and a Directed Acyclic Graph (DAG) of prerequisites is generated.
3. **Task Storage (`InMemoryTaskStore`):**
   The DAG structure is captured in `task_store.py`. Tasks are tracked natively via `create(query, required_outputs)`, maintaining execution schemas (`task_id`, `status: pending/running/completed`).
4. **Agent Resolution (`resolver.py`):**
   A continuous resolution loop awakens. The topological `Resolver` checks pending tasks (`requires` vs. `produces`). It queries the `AgentRegistry` (`agent_registry.py`), a structural map of all available micro-agents. When it matches capabilities, it dispatches the task down the pipeline via **JSON-RPC 2.0**.
5. **Worker Execution (A2A Network):**
   The invoked specialized execution agent (e.g., Weather Agent) queries `GET /tasks/{id}/context` to pull down the blackboard state. Upon processing logic, the Agent constructs an execution payload targeted squarely at the MCP Tool Gateway.
6. **Tool Invocation (MCP Server):**
   The gateway validates the tool request and redirects it to physical registered endpoints (e.g., `fetch_weather()`, `query_sql()`). Once the tool answers via JSON schemas, the data traverses the MCP Server back to the Execution Agent.
7. **DAG Resolution & Finalization:**
   The agent acknowledges success back to the Entry Agent (`PATCH /tasks/{id}/context` and marks `agent_uid` status). The Resolver awakens the next agent down the graph until the terminal state is reached.

---

## 2. Component Deep Dive

### 2.1 A2A Agent Network (Orchestration & Execution)
- **`Entry Agent` (Port 8010):** The primary brain. Holds the Task Store, handles the API portal, operates the LLM planner, and orchestrates the resolver loop.
- **Specialized Execution Agents (`base.py` `BaseAgent ABC`):**
  These agents are strictly stateless processing nodes. They expose `/run` endpoints for HTTP triggers. 
  - **`Weather Agent` (8002)**
  - **`News Agent` (8001)**
  - **`Report Agent` (8003)**: Summarizes ingested contexts into Markdown.
  - **`SQL Agent` (8005)**: Translates NL to SQL against the Chinook Database.
  - **`RAG Agent` (8006)**: Leverages FAISS indexing (all-MiniLM-L6-v2) for Indian Law contexts.
  - **`Chat Agent` (8007)**: Fallback conversational entity providing direct inference replies via Groq.
  *(Note: The `Composio Agent` (8008) operates slightly downstream, taking outputs from Weather/SQL/News to construct messages, ultimately executing the `composio_tool` + `send_message`).*

### 2.2 MCP Tool Gateway (Port 8000)
The absolute perimeter for physical world interaction. `server.py` implements Model Context Protocol logic:
- A `POST /tools/call` dispatcher acts as a proxy to mapped toolings.
- Exposes `GET /tools` to declare capability listings.
- **Registered Tools:**
  - `fetch_weather` (`tools/fetch_weather.py`): Maps cities and units to OpenWeatherMap HTTP API.
  - `fetch_news` (`tools/fetch_news.py`): Executes structured queries against NewsData.io REST API.
  - `query_sql` (`tools/query_sql.py`): Direct SQLite database interface with agent synthesis.
  - `query_rag` (`tools/query_rag.py`): Performs Top-K semantic search against data chunks.
  - `composio_tool` (`tools/composio_tool.py`): Complex webhook and OAuth redirect implementation mapping to Composio Platform configurations, Slack, Discord, Green API (WhatsApp), and standard email bindings.

### 2.3 Shared Common Module
Distributed architecture requires highly rigid shared standards. This code block is imported by *all components* at runtime:
- **`config.py` (`pydantic.BaseSettings`)**: Responsible for fetching `.env.local`, enforcing API keys, parsing Groq/Composio parameters, and assigning ports/URLs statically.
- **`models.py` + `a2a_types.py` (`pydantic` schemas)**: The structural typing definitions mapping `WeatherData`, `NewsArticle`, `ExecutionPlan`, `AgentCard`, and schema cycle detection schemas.
- **`prompts/` (System Prompts)**: Centralizes inference instructions (`PLANNER_SYSTEM`, `ALL_OUTPUT_KEYS` mappings, agent-specific tuning).
- **`errors.py` + `utils.py`**: A unified `MCPError` and `AgentTimeoutError` hierarchy with retry decorators (`retry_async`).
- **`logging.py` + `tracing.py`**: Distributed runtime observability. Combines `structlog` for application logs with OpenTelemetry tracing spanning cross-port HTTP lifecycles.
- **`agents/base.py` (`BaseAgent API`)**: Standardizes the FastAPI factory application instantiation. Embeds generic `POST /` bindings and the `.discover()` auto-registration dictionary method.

### 2.4 External Services & Infrastructure
The persistent foundation holding up the logic gate:
- **External Services/APIs:** OpenWeather API, NewsData.io, Composio Platform (OAuth bridging), and Groq LLM API.
- **MongoDB + Auth Server:** Sessions holding logic (`users`, `bcrypt + JWT schemas`), persisting state where required outside the DAG cache.
- **Gateway Services (`Ports 8015, 8030`)**: WhatsApp Meta Cloud, Green API Gateway, and Telegram polling infrastructure for client routing.
- **Docker Compose:** Houses 8 containerized services wrapped over a shared `agent-net` bridge network ensuring deterministic environment parity.