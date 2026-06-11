"""Runtime settings, loaded from environment / .env. No secrets in code."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from app.paths import DATA_DIR, PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    model_provider: str
    anthropic_api_key: str | None
    anthropic_model: str
    ollama_host: str
    ollama_model: str
    db_path: str


def load_settings() -> Settings:
    return Settings(
        model_provider=os.getenv("MODEL_PROVIDER", "anthropic").lower(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        db_path=os.getenv("DB_PATH", str(DATA_DIR / "orchestrator.db")),
    )
