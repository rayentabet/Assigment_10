"""Environment-backed application configuration."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supervisor_model: str = "openai/gpt-oss-120b"
    guardrail_model: str = "openai/gpt-oss-safeguard-20b"
    rag_model: str = "gemini-3.1-flash-lite"
    code_model: str = "qwen/qwen3.6-27b"
    visualization_model: str = "gemini-3.1-flash-lite"
    general_model: str = "qwen/qwen3.6-27b"
    max_agent_iterations: int = Field(default=6, ge=1, le=20)
    generated_directory: Path = Path("generated")
    openscad_executable: str = "openscad"
    rag_project_path: Path = Path("../Assignment_8")
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "arduino_rag"
    mcp_server_url: str = "http://127.0.0.1:8001/mcp"
    mcp_auth_token: str = ""
    chat_database_path: Path = Path("data/chat_history.sqlite")


settings = Settings()
