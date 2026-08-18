"""Environment-backed configuration for the Component Manager service."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    component_manager_model: str = "gemini-3.1-flash-lite"
    # The reachable hostname advertised in the Agent Card's RPC URL (NOT the
    # uvicorn bind address, which is always passed separately as --host
    # 0.0.0.0 on the command line/Dockerfile). Override to the Docker Compose
    # service name ("component-manager") when System A calls this service
    # from inside another container.
    advertised_host: str = "127.0.0.1"
    port: int = 8002
    rest_port: int = 8003
    database_path: Path = Path("component_manager/data/component_manager.sqlite")
    session_database_path: Path = Path("component_manager/data/sessions.sqlite")
    proposal_ttl_minutes: int = Field(default=15, ge=1)
    spending_limit: float = Field(default=200.0, gt=0)
    # Generate a long random value, for example: openssl rand -hex 32
    approval_token_secret: str = ""

    # DigiKey Product Information V4 (two-legged OAuth / client credentials).
    # The Account ID is optional for keyword search, but some pricing endpoints
    # and organization configurations require it.
    digikey_client_id: str = ""
    digikey_client_secret: str = ""
    digikey_account_id: str = ""
    digikey_sandbox: bool = True
    digikey_site: str = "US"
    digikey_language: str = "en"
    digikey_currency: str = "USD"
    digikey_timeout_seconds: float = Field(default=20.0, gt=0)

    # Separate sandbox Ordering application (three-legged OAuth).
    digikey_order_client_id: str = ""
    digikey_order_client_secret: str = ""
    digikey_order_redirect_uri: str = "https://localhost:8000/auth/digikey/callback"
    digikey_order_sandbox: bool = True
    digikey_token_encryption_key: str = ""
    oauth_key_path: Path = Path("component_manager/data/.oauth_key")


settings = Settings()
