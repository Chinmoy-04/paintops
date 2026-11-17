"""Application settings loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_API_KEY = "paintops-dev-key"


class Settings(BaseSettings):
    """Runtime configuration for the PaintOps MVP."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    demo_mode: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    database_url: str = f"sqlite:///{ROOT_DIR / 'data' / 'paintops.db'}"
    checkpoint_db_path: str = str(ROOT_DIR / "data" / "checkpoints" / "langgraph.db")

    recurrence_window_minutes: int = 60
    recurrence_action_threshold: int = 3
    high_severity_action_required: bool = True

    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5:3b"
    ollama_base_url: str = "http://host.docker.internal:11434"
    llm_temperature: float = 0.0
    openai_api_key: str | None = None
    google_api_key: str | None = None

    sop_dir: str = str(ROOT_DIR / "data" / "sops")
    chroma_dir: str = str(ROOT_DIR / "data" / "chroma")
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    sop_top_k: int = 3

    paintops_api_base: str = "http://localhost:8000"

    # Shared secret for ingest and n8n-facing routes, sent as the X-PaintOps-Key header.
    # The default only exists so a fresh checkout runs; the API logs a warning while
    # it is in use. Set your own in .env.
    paintops_api_key: str = DEFAULT_API_KEY
    # Browser origins allowed to call the API (the Vite dev server from Phase 3).
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def database_path(self) -> Path:
        """Filesystem path for the business SQLite database when using a file URL."""
        url = self.database_url
        if url.startswith("sqlite:///"):
            return Path(url.removeprefix("sqlite:///"))
        return ROOT_DIR / "data" / "paintops.db"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
