# Multi-agent System


Architecture of system -

[Go to architecture file](Architecture.md)

## Dependencies for the system :

#### Core framework
uv add fastapi "uvicorn[standard]" httpx pydantic pydantic-settings python-dotenv

#### LLM
uv add groq

#### MCP
uv add mcp

#### Utilities
uv add tenacity structlog python-dateutil anyio

#### Email
uv add aiosmtplib

#### UI
uv add gradio

#### Dev / test tools
uv add --dev pytest pytest-asyncio respx ruff
