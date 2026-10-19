"""通用问答的可选模型目录。

目录只包含服务端预置的供应商。客户端提交模型 id，不能提交 base_url，
因此无法把接口变成任意地址代理，也不会拿到密钥。每个供应商可使用
独立的 API Key 与模型名；未配置密钥的模型会带原因返回，由前端禁用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import settings
from .providers import OpenAICompatLLM

_PRESET_META = {
    "deepseek": {
        "label": "DeepSeek 开放平台",
        "description": "通用推理、代码与文本生成",
    },
    "qwen": {
        "label": "阿里云百炼 / 通义千问",
        "description": "中文理解、写作与知识问答",
    },
    "doubao": {
        "label": "火山方舟 / 豆包",
        "description": "中文对话与长文本处理",
    },
}

SETUP_HINT = (
    "在 backend/.env 中配置所需供应商的密钥后重启服务："
    "DEEPSEEK_API_KEY / QWEN_API_KEY / DOUBAO_API_KEY；"
    "本地或自建端点使用 LLM_PROVIDER=openai_compatible 并填写 "
    "LLM_BASE_URL、LLM_MODEL（密钥可选）。"
)

DISCLAIMER = (
    "本页回答由所选大模型直接生成，不检索本系统知识库与结构化台账，"
    "不作为竞赛政策、报名时间、费用标准或统计数据的依据。"
)

_ENV_NAMES = {"deepseek": "DEEPSEEK_API_KEY", "qwen": "QWEN_API_KEY", "doubao": "DOUBAO_API_KEY"}


@dataclass(frozen=True)
class ChatModel:
    id: str
    provider: str
    label: str
    model: str
    base_url: str
    api_key: str
    description: str
    available: bool
    reason: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "provider_label": self.label,
            "model": self.model,
            "description": self.description,
            "available": self.available,
            "reason": self.reason,
        }


def _primary_provider() -> str:
    return (settings.llm_provider or "builtin").strip().lower()


def _provider_key(provider: str) -> str:
    specific = str(getattr(settings, f"{provider}_api_key", "") or "").strip()
    if specific:
        return specific
    # 仅当前主通道允许复用 LLM_API_KEY，避免把一家的密钥发给另一家端点
    if _primary_provider() == provider:
        return (settings.llm_api_key or "").strip()
    return ""


def _preset_entry(provider: str) -> ChatModel:
    preset = settings.PROVIDER_PRESETS[provider]
    meta = _PRESET_META[provider]
    is_primary = _primary_provider() == provider
    base_url = preset["base_url"]
    model = str(getattr(settings, f"{provider}_model", "") or "").strip()
    if is_primary:
        base_url = (settings.llm_base_url or base_url).strip()
        model = model or (settings.llm_model or "").strip()
    model = model or preset["model"]
    key = _provider_key(provider)
    reason = "" if key else f"未配置 {_ENV_NAMES[provider]}"
    return ChatModel(
        id=provider,
        provider=provider,
        label=meta["label"],
        model=model,
        base_url=base_url,
        api_key=key,
        description=meta["description"],
        available=bool(base_url and model and key),
        reason=reason,
    )


def _custom_entry() -> ChatModel | None:
    if _primary_provider() != "openai_compatible":
        return None
    base_url = (settings.llm_base_url or "").strip()
    model = (settings.llm_model or "").strip()
    if not base_url or not model:
        return None
    # 本地 Ollama/vLLM 等端点通常不校验密钥，因此密钥可选
    return ChatModel(
        id="openai_compatible",
        provider="openai_compatible",
        label="自定义 OpenAI 兼容端点",
        model=model,
        base_url=base_url,
        api_key=(settings.llm_api_key or "").strip(),
        description="学院自建或本地部署的兼容端点",
        available=True,
    )


def list_chat_models() -> list[ChatModel]:
    entries = [_preset_entry(provider) for provider in ("deepseek", "qwen", "doubao")]
    custom = _custom_entry()
    if custom:
        entries.append(custom)
    return entries


def get_chat_model(model_id: str) -> ChatModel:
    for entry in list_chat_models():
        if entry.id == model_id:
            return entry
    raise KeyError(model_id)


def default_model_id() -> str | None:
    entries = list_chat_models()
    for entry in entries:
        if entry.available:
            return entry.id
    return None


def build_chat_llm(
    entry: ChatModel,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> OpenAICompatLLM:
    return OpenAICompatLLM(
        base_url=entry.base_url,
        model=entry.model,
        api_key=entry.api_key,
        label=entry.label,
        provider=entry.provider,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def catalog_payload() -> dict[str, Any]:
    entries = list_chat_models()
    available = [entry for entry in entries if entry.available]
    return {
        "items": [entry.public() for entry in entries],
        "default": available[0].id if available else None,
        "available_count": len(available),
        "setup_hint": SETUP_HINT,
        "disclaimer": DISCLAIMER,
        "limits": {
            "max_messages": settings.llm_chat_max_messages,
            "max_chars": settings.llm_chat_max_chars,
            "max_tokens": settings.llm_max_tokens,
        },
    }


__all__ = [
    "DISCLAIMER",
    "SETUP_HINT",
    "catalog_payload",
    "build_chat_llm",
    "default_model_id",
    "get_chat_model",
    "list_chat_models",
]
