from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    gemini_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    elevenlabs_api_key: str = ""
    pinecone_api_key: str = ""
    pinecone_host: str = ""
    pinecone_index: str = "sahayak-judgments"
    database_url: str = "postgresql://postgres:postgres@localhost/sahayak"
    redis_url: str = "redis://localhost:6379"
    data_retention_days: int = 30
    environment: str = "development"
    allowed_origins: str = "*"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
