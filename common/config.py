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
    
    # Email
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str

    # Ports
    mcp_server_port: int
    news_agent_port: int
    weather_agent_port: int
    report_agent_port: int
    orchestrator_port: int
    ui_port: int

    # Hosts
    mcp_server_host: str
    news_agent_host: str
    weather_agent_host: str
    report_agent_host: str
    orchestrator_host: str

    # System
    mcp_transport: str
    log_level: str
    log_format: str
    otel_enabled: bool
    otel_endpoint: str
    app_env: str
    request_timeout: int
    max_retries: int

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

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    return settings