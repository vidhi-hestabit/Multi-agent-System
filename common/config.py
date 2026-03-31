from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    groq_api_key: str
    groq_model: str

    # APIs
    news_api_key: str
    openweather_api_key: str

    #Composio
    composio_api_key:str
    composio_base_url:str

    # Ports
    mcp_server_port: int
    news_agent_port: int
    weather_agent_port: int
    report_agent_port: int
    orchestrator_port: int
    ui_port: int
    sql_agent_port: int
    rag_agent_port: int
    chat_agent_port: int 
    composio_agent_port: int
    entry_agent_port: int = 8010
    email_agent_port: int = 8014
    whatsapp_gateway_port: int = 8015

    # Hosts
    mcp_server_host: str
    news_agent_host: str
    weather_agent_host: str
    report_agent_host: str
    orchestrator_host: str
    sql_agent_host: str
    rag_agent_host: str
    entry_agent_host: str = "localhost"
    chat_agent_host: str = "localhost"
    chinook_db_path: str
    faiss_index_path: str
    faiss_chunks_path: str
    composio_agent_host: str
    whatsapp_gateway_host: str = "localhost"

    # WhatsApp / Meta Webhook
    whatsapp_verify_token: str = "nexus_whatsapp_verify"
    whatsapp_phone_number_id: str = ""
    whatsapp_composio_entity_id: str = ""

    # System
    mcp_transport: str
    log_level: str
    log_format: str
    otel_enabled: bool
    otel_endpoint: str
    app_env: str
    request_timeout: int
    max_retries: int

    # MongoDB & Auth
    mongodb_url: str = ""
    mongodb_db: str = "multi-agent-system"
    jwt_secret: str = "change-me-in-production"

    # Telegram native bot
    telegram_bot_token: str = ""

    # Twilio WhatsApp Bot
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"  # Twilio sandbox default

    # Green API (Baileys-based WhatsApp)
    green_api_instance_id: str = ""
    green_api_token: str = ""
    green_api_gateway_port: int = 8031


    @property
    def mcp_server_url(self) -> str:
        return f"http://{self.mcp_server_host}:{self.mcp_server_port}"

    @property
    def news_agent_url(self) -> str:
        return f"http://{self.news_agent_host}:{self.news_agent_port}"

    @property
    def weather_agent_url(self) -> str:
        return f"http://{self.weather_agent_host}:{self.weather_agent_port}"

    @property
    def report_agent_url(self) -> str:
        return f"http://{self.report_agent_host}:{self.report_agent_port}"

    @property
    def orchestrator_url(self) -> str:
        return f"http://{self.orchestrator_host}:{self.orchestrator_port}"

    @property
    def sql_agent_url(self) -> str:
        return f"http://{self.sql_agent_host}:{self.sql_agent_port}"

    @property
    def rag_agent_url(self) -> str:
        return f"http://{self.rag_agent_host}:{self.rag_agent_port}"

    @property
    def chat_agent_url(self) -> str:
         return f"http://{self.chat_agent_host}:{self.chat_agent_port}"
    @property
    def composio_agent_url(self) -> str:
        return f"http://{self.composio_agent_host}:{self.composio_agent_port}"

    @property
    def entry_agent_url(self) -> str:
        return f"http://{self.entry_agent_host}:{self.entry_agent_port}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
