"""全局配置：所有可变项均可通过 .env 或环境变量覆盖，不在代码中固化业务规则。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 基本运行参数 ----------
    app_name: str = "高校学科竞赛辅助服务智能体"
    app_env: str = "development"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "*"

    # ---------- 数据库 ----------
    database_url: str = "sqlite:///./data/competition_agent.db"
    sql_echo: bool = False

    # ---------- 大模型 ----------
    llm_provider: str = "builtin"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    llm_timeout: int = 120

    # 通用模型问答：多家模型可同时配置，用户在前端自主选择
    deepseek_api_key: str = ""
    deepseek_model: str = ""
    qwen_api_key: str = ""
    qwen_model: str = ""
    doubao_api_key: str = ""
    doubao_model: str = ""
    llm_chat_max_messages: int = 20
    llm_chat_max_chars: int = 16000

    # ---------- 向量模型 ----------
    embedding_provider: str = "builtin"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_dim: int = 512

    # ---------- RAG 检索参数 ----------
    rag_chunk_size: int = 600
    rag_chunk_overlap: int = 100
    rag_top_k: int = 6
    rag_recall_k: int = 20
    rag_vector_weight: float = 0.6
    rag_keyword_weight: float = 0.4
    rag_min_score: float = 0.05

    # ---------- 数据目录 ----------
    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"
    export_dir: str = "./data/exports"
    knowledge_dir: str = "./data/knowledge"
    seed_dir: str = "./data/seed"
    rules_dir: str = "./data/rules"
    prompt_dir: str = "./prompts"

    # ---------- 业务默认值 ----------
    default_college: str = "计算与智能技术学院"
    default_currency: str = "CNY"

    # ================= 派生属性 =================
    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return (v or "*").strip()

    def _abs(self, raw: str) -> Path:
        p = Path(raw)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def data_path(self) -> Path:
        return self._abs(self.data_dir)

    @property
    def upload_path(self) -> Path:
        return self._abs(self.upload_dir)

    @property
    def export_path(self) -> Path:
        return self._abs(self.export_dir)

    @property
    def knowledge_path(self) -> Path:
        return self._abs(self.knowledge_dir)

    @property
    def seed_path(self) -> Path:
        return self._abs(self.seed_dir)

    @property
    def rules_path(self) -> Path:
        return self._abs(self.rules_dir)

    @property
    def prompt_path(self) -> Path:
        return self._abs(self.prompt_dir)

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # 预留的国产大模型 OpenAI 兼容端点，便于一键切换
    PROVIDER_PRESETS: dict[str, dict[str, str]] = {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "label": "DeepSeek 开放平台",
        },
        "qwen": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-plus",
            "label": "阿里云百炼 / 通义千问",
        },
        "doubao": {
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "doubao-1-5-pro-32k-250115",
            "label": "火山方舟 / 豆包",
        },
    }

    EMBEDDING_PRESETS: dict[str, dict[str, object]] = {
        "qwen": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "text-embedding-v3",
            "dim": 1024,
            "label": "通义千问 text-embedding-v3",
        },
        "doubao": {
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "doubao-embedding-text-240715",
            "dim": 2560,
            "label": "豆包 doubao-embedding",
        },
    }

    def resolved_llm(self) -> dict[str, str]:
        """把 provider 解析为实际使用的 base_url / model / label。"""
        provider = (self.llm_provider or "builtin").lower()
        preset = self.PROVIDER_PRESETS.get(provider, {})
        return {
            "provider": provider,
            "base_url": self.llm_base_url or preset.get("base_url", ""),
            "model": self.llm_model or preset.get("model", ""),
            "api_key": self.llm_api_key,
            "label": preset.get("label", "OpenAI 兼容端点" if provider == "openai_compatible" else "内置离线智能体"),
        }

    def resolved_embedding(self) -> dict[str, object]:
        provider = (self.embedding_provider or "builtin").lower()
        preset = self.EMBEDDING_PRESETS.get(provider, {})
        return {
            "provider": provider,
            "base_url": self.embedding_base_url or str(preset.get("base_url", "")),
            "model": self.embedding_model or str(preset.get("model", "")),
            "api_key": self.embedding_api_key or self.llm_api_key,
            "dim": int(preset.get("dim", self.embedding_dim)) if not self.embedding_model else self.embedding_dim,
            "label": str(preset.get("label", "离线哈希向量")),
        }

    def ensure_dirs(self) -> None:
        for p in (
            self.data_path,
            self.upload_path,
            self.export_path,
            self.knowledge_path,
            self.seed_path,
            self.rules_path,
            self.prompt_path,
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()