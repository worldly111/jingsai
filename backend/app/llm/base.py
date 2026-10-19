"""大模型抽象层：统一的接口定义。

系统不绑定任何一家模型。可用的 provider：
  - builtin            内置离线智能体（检索 + 规则 + 结构化数据合成，无需密钥）
  - deepseek           DeepSeek 开放平台
  - qwen               阿里云百炼 / 通义千问
  - doubao             火山方舟 / 豆包
  - openai_compatible  任意 OpenAI 兼容端点（含本地 Ollama / vLLM）
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

Message = dict[str, str]


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    content: str
    provider: str = ""
    model: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class BaseLLM(ABC):
    """大模型统一接口。"""

    provider: str = "base"
    label: str = "大模型"
    is_available: bool = False

    def info(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "label": self.label,
            "available": self.is_available,
            "model": getattr(self, "model", ""),
            "mode": "llm" if self.is_available else "offline",
        }

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """一次性生成。"""

    def stream(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """流式生成，默认退化为一次性生成后切片输出。"""
        resp = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        yield from _slice_text(resp.content)


def _slice_text(text: str, size: int = 24) -> Iterator[str]:
    for i in range(0, len(text), size):
        yield text[i : i + size]


class UnavailableLLM(BaseLLM):
    """未配置任何大模型时的占位实现。

    各智能体会检测 `is_available`，自动切换到内置离线合成路径，
    因此系统在零配置状态下依然可以完整运行。
    """

    provider = "builtin"
    label = "内置离线智能体"
    is_available = False

    def chat(self, messages, *, temperature=None, max_tokens=None, json_mode=False) -> LLMResponse:  # noqa: D102
        return LLMResponse(
            content="",
            provider=self.provider,
            model="builtin-offline",
            latency_ms=0,
        )


def now_ms() -> int:
    return int(time.time() * 1000)