"""大模型 / 向量模型工厂：按配置返回实例，全局缓存单例。

切换模型只需修改 .env 中的 LLM_PROVIDER，无需改动任何业务代码。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..config import settings
from .base import BaseLLM, UnavailableLLM
from .embeddings import HashingEmbedder, build_embedder
from .providers import OpenAICompatLLM

_LLM_PRESET_LABELS = {
    "deepseek": "DeepSeek 开放平台",
    "qwen": "阿里云百炼 / 通义千问",
    "doubao": "火山方舟 / 豆包",
}


def _build_llm() -> BaseLLM:
    cfg = settings.resolved_llm()
    provider = cfg["provider"]

    if provider == "builtin":
        return UnavailableLLM()

    if not cfg["base_url"] or not cfg["model"]:
        # 端点信息不完整，回退到离线智能体，保证系统仍可运行
        return UnavailableLLM()

    if provider in _LLM_PRESET_LABELS and not cfg["api_key"]:
        # 需要密钥的云模型未配置密钥，同样回退
        return UnavailableLLM()

    return OpenAICompatLLM(
        base_url=cfg["base_url"],
        model=cfg["model"],
        api_key=cfg["api_key"],
        label=cfg["label"],
        provider=provider,
    )


@lru_cache(maxsize=1)
def get_llm() -> BaseLLM:
    return _build_llm()


@lru_cache(maxsize=1)
def get_embedder():
    return build_embedder(settings.resolved_embedding())


def reset_llm_cache() -> None:
    get_llm.cache_clear()
    get_embedder.cache_clear()


def runtime_info() -> dict[str, Any]:
    """向前端暴露当前运行模式，便于在界面上提示"离线/大模型"状态。"""
    llm = get_llm()
    emb = get_embedder()
    llm_info = llm.info()
    emb_info = emb.info() if hasattr(emb, "info") else {}
    return {
        "llm": llm_info,
        "embedding": emb_info,
        "mode": llm_info.get("mode", "offline"),
        "mode_label": (
            f"{llm_info.get('label')}（{llm_info.get('model')}）"
            if llm.is_available
            else "内置离线智能体（检索 + 规则 + 结构化数据驱动，未启用大模型）"
        ),
        "switch_hint": (
            "修改 backend/.env 中的 LLM_PROVIDER 为 deepseek / qwen / doubao 并填入 "
            "LLM_API_KEY，重启服务即可切换为国产大模型生成。"
        ),
    }


__all__ = [
    "HashingEmbedder",
    "get_llm",
    "get_embedder",
    "reset_llm_cache",
    "runtime_info",
]