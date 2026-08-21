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
    wiring_model: str = "qwen/qwen3.6-27b"
    visualization_model: str = "gemini-3.1-flash-lite"
    title_model: str = "openai/gpt-oss-20b"
    judge_model: str = "openai/gpt-oss-safeguard-20b"

    # OpenRouter fallback, tried only when a role's primary model call raises.
    # Left blank, no fallback is attached at all and a primary failure (rate
    # limit, outage) fails the request outright; see app/models.py.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    fallback_model: str = "nvidia/nemotron-3-ultra-550b-a55b"

    max_agent_iterations: int = Field(default=6, ge=1, le=20)
    generated_directory: Path = Path("generated")
    rag_project_path: Path = (
        Path(__file__).resolve().parents[2] / "mcp-server" / "rag"
    )
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "arduino_rag"
    mcp_server_url: str = "http://127.0.0.1:8001/mcp"
    mcp_auth_token: str = ""
    chat_database_path: Path = Path("data/chat_history.sqlite")
    app_environment: str = "development"
    payment_provider: str = "sandbox"
    lithic_api_key: str = ""
    lithic_base_url: str = "https://sandbox.lithic.com/v1"
    lithic_timeout_seconds: float = Field(default=20.0, gt=0)

    # Component Manager (System B) A2A endpoint. 15s proved too short for a
    # real turn where System B's model makes 2-3 sequential tool calls plus
    # its own generation latency; confirmed against a live run.
    component_manager_a2a_url: str = "http://127.0.0.1:8002"
    a2a_timeout_seconds: float = Field(default=60.0, gt=0)
    a2a_max_retries: int = Field(default=2, ge=0, le=5)

    # System B's REST API (component_manager/rest_api.py), used only for the
    # DigiKey OAuth proxy endpoints below — everything else talks to System B
    # over A2A. Same 127.0.0.1 vs. service-name split as the A2A URL above.
    component_manager_rest_url: str = "http://127.0.0.1:8003"

    # React frontend (services/frontend/) dev server origin(s), JSON array in .env
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Local speech-to-text (faster-whisper). int8 keeps the "small" model's
    # working set well under an 8GB machine; no external ffmpeg binary or
    # network call is needed once the weights are cached locally.
    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"


settings = Settings()
