import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINRAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("model_validate", "model_dump", "settings_"),
    )
    data_dir: Path = Path("data")
    allowed_pdf_dir: Path = Path("data/inbox")
    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_device: str = "cpu"
    embedding_disable_xet: bool = False
    embedding_local_files_only: bool = False
    chunk_tokens: int = Field(default=384, ge=64, le=480)
    marker_python: str | None = None
    model_cache_dir: Path | None = None
    marker_device: str = "cpu"
    marker_timeout_seconds: int = Field(default=1800, ge=10)
    max_pdf_mb: int = Field(default=200, ge=1)
    max_pending_jobs: int = Field(default=8, ge=1, le=100)

    def prepare(self) -> None:
        self.data_dir = self.data_dir.expanduser().resolve()
        self.allowed_pdf_dir = self.allowed_pdf_dir.expanduser().resolve()
        for path in (self.data_dir, self.allowed_pdf_dir, self.data_dir / "documents"):
            path.mkdir(parents=True, exist_ok=True)
        if self.model_cache_dir is not None:
            self.model_cache_dir = self.model_cache_dir.expanduser().resolve()
            for name in ("marker", "huggingface", "xet", "tmp"):
                (self.model_cache_dir / name).mkdir(parents=True, exist_ok=True)


def load_settings(**overrides) -> Settings:
    """Allow MCP clients to locate .env independently of their working directory."""
    return Settings(_env_file=os.environ.get("FINRAG_ENV_FILE", ".env"), **overrides)
