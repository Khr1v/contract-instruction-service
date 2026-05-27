from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")

    yandex_cloud_folder: str = Field(default="b1gonfi2pbn8c80hh4qv", alias="YANDEX_CLOUD_FOLDER")
    yandex_cloud_api_key: str | None = Field(default=None, alias="YANDEX_CLOUD_API_KEY")
    yandex_cloud_model: str = Field(default="qwen3.6-35b-a3b/latest", alias="YANDEX_CLOUD_MODEL")
    yandex_generation_model: str | None = Field(default=None, alias="YANDEX_GENERATION_MODEL")
    yandex_generation_model_mode: str = Field(default="auto", alias="YANDEX_GENERATION_MODEL_MODE")
    yandex_reviewer_model: str | None = Field(default=None, alias="YANDEX_REVIEWER_MODEL")
    yandex_base_url: str = Field(default="https://ai.api.cloud.yandex.net/v1", alias="YANDEX_BASE_URL")
    yandex_data_logging_enabled: bool = Field(default=False, alias="YANDEX_DATA_LOGGING_ENABLED")

    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    data_dir: Path = Field(default=PROJECT_ROOT / "data", alias="DATA_DIR")
    uploads_dir: Path = Field(default=PROJECT_ROOT / "data" / "uploads", alias="UPLOADS_DIR")
    processed_dir: Path = Field(default=PROJECT_ROOT / "data" / "processed", alias="PROCESSED_DIR")
    vectorstore_dir: Path = Field(default=PROJECT_ROOT / "data" / "vectorstore", alias="VECTORSTORE_DIR")
    templates_dir: Path = Field(default=PROJECT_ROOT / "data" / "templates", alias="TEMPLATES_DIR")
    contracts_dir: Path = Field(default=PROJECT_ROOT / "sdogovory", alias="CONTRACTS_DIR")
    default_contract_file: Path = Field(
        default=PROJECT_ROOT / "sdogovory" / "D-okazaniya-TEU (1).docx",
        alias="DEFAULT_CONTRACT_FILE",
    )

    sqlite_db_path: Path = Field(default=PROJECT_ROOT / "data" / "app.db", alias="SQLITE_DB_PATH")

    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_max_output_tokens: int = Field(default=8000, alias="LLM_MAX_OUTPUT_TOKENS")
    enable_llm_instruction_validation: bool = Field(default=False, alias="ENABLE_LLM_INSTRUCTION_VALIDATION")
    ocr_provider: str = Field(default="stub", alias="OCR_PROVIDER")
    ocr_max_pages: int = Field(default=40, alias="OCR_MAX_PAGES")
    ocr_dpi: int = Field(default=150, alias="OCR_DPI")
    ocr_concurrency: int = Field(default=3, alias="OCR_CONCURRENCY")
    instruction_renderer_path: Path = Field(
        default=PROJECT_ROOT / "app" / "services" / "provided_renderer.py",
        alias="INSTRUCTION_RENDERER_PATH",
    )
    instruction_template_docx_path: Path = Field(
        default=PROJECT_ROOT / "shablon" / "_Шаблон_инструкции_по_работе_с_клиентом_1.docx",
        alias="INSTRUCTION_TEMPLATE_DOCX_PATH",
    )
    strict_template_renderer: bool = Field(default=True, alias="STRICT_TEMPLATE_RENDERER")

    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")

    admin_ids: str = Field(default="", alias="ADMIN_IDS")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    public_base_url: str | None = Field(default=None, alias="PUBLIC_BASE_URL")
    bitrix_webhook_url: str | None = Field(default=None, alias="BITRIX_WEBHOOK_URL")
    bitrix_bot_id: int | None = Field(default=None, alias="BITRIX_BOT_ID")
    bitrix_bot_code: str = Field(default="contract_instruction_bot", alias="BITRIX_BOT_CODE")
    bitrix_bot_name: str = Field(default="ИИ Инструкции", alias="BITRIX_BOT_NAME")
    bitrix_bot_token: str | None = Field(default=None, alias="BITRIX_BOT_TOKEN")
    bitrix_bot_type: str = Field(default="bot", alias="BITRIX_BOT_TYPE")
    bitrix_bot_event_url: str | None = Field(default=None, alias="BITRIX_BOT_EVENT_URL")
    bitrix_disk_storage_id: int | None = Field(default=None, alias="BITRIX_DISK_STORAGE_ID")
    bitrix_result_folder_id: int | None = Field(default=None, alias="BITRIX_RESULT_FOLDER_ID")

    @field_validator("bitrix_bot_id", "bitrix_disk_storage_id", "bitrix_result_folder_id", mode="before")
    @classmethod
    def empty_int_setting_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    def model_post_init(self, __context: object) -> None:
        for field_name in [
            "data_dir",
            "uploads_dir",
            "processed_dir",
            "vectorstore_dir",
            "templates_dir",
            "contracts_dir",
            "default_contract_file",
            "instruction_renderer_path",
            "instruction_template_docx_path",
            "sqlite_db_path",
        ]:
            path = getattr(self, field_name)
            if not path.is_absolute():
                setattr(self, field_name, PROJECT_ROOT / path)

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids.strip():
            return []
        return [int(item.strip()) for item in self.admin_ids.split(",") if item.strip()]

    def ensure_directories(self) -> None:
        for path in [
            self.data_dir,
            self.uploads_dir,
            self.processed_dir,
            self.vectorstore_dir,
            self.templates_dir,
            self.contracts_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def resolve_project_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return PROJECT_ROOT / candidate


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
