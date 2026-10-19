"""OpenAI 兼容大模型客户端。

DeepSeek、通义千问（百炼兼容模式）、豆包（火山方舟）、Ollama、vLLM 等
均提供 OpenAI 兼容的 /chat/completions 接口，因此共用一份实现，
通过 .env 中的 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY 切换。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx

from ..config import settings
from .base import BaseLLM, LLMResponse, LLMUsage, Message


class OpenAICompatLLM(BaseLLM):
    provider = "openai_compatible"
    label = "OpenAI 兼容端点"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        label: str | None = None,
        provider: str | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key or ""
        self.timeout = timeout or settings.llm_timeout
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.max_tokens = max_tokens or settings.llm_max_tokens
        if label:
            self.label = label
        if provider:
            self.provider = provider
        self.is_available = bool(self.base_url and self.model)

    # ---------- 内部 ----------
    @property
    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _payload(
        self,
        messages: list[Message],
        temperature: float | None,
        max_tokens: int | None,
        json_mode: bool,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": stream,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    # ---------- 对外 ----------
    def chat(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        started = time.time()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=self._payload(messages, temperature, max_tokens, json_mode, False),
            )
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        usage_raw = data.get("usage") or {}
        return LLMResponse(
            content=content,
            provider=self.provider,
            model=data.get("model", self.model),
            usage=LLMUsage(
                prompt_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
                total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
            ),
            latency_ms=int((time.time() - started) * 1000),
            raw=data,
        )

    def stream(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        payload = self._payload(messages, temperature, max_tokens, False, True)
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream(
                "POST", f"{self.base_url}/chat/completions", headers=self._headers, json=payload
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta

    def health(self) -> dict[str, Any]:
        """轻量连通性探测（用于前端"模型连通性测试"。）"""
        try:
            self.chat([{"role": "user", "content": "ping"}], max_tokens=4)
            return {"ok": True, "message": f"{self.label} 连接正常"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"{self.label} 连接失败：{exc}"}


class OpenAICompatEmbedder:
    """OpenAI 兼容向量模型客户端（通义 text-embedding-v3 / 豆包 embedding 等）。"""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        dim: int = 1024,
        label: str = "OpenAI 兼容向量模型",
        timeout: int = 60,
        batch_size: int = 10,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key or ""
        self.dim = dim
        self.label = label
        self.timeout = timeout
        self.batch_size = batch_size

    @property
    def is_available(self) -> bool:
        return bool(self.base_url and self.model)

    def info(self) -> dict[str, Any]:
        return {
            "provider": "openai_compatible",
            "label": self.label,
            "model": self.model,
            "dim": self.dim,
            "available": self.is_available,
        }

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as client:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                resp = client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json={"model": self.model, "input": batch, "encoding_format": "float"},
                )
                resp.raise_for_status()
                items = resp.json().get("data") or []
                items.sort(key=lambda x: x.get("index", 0))
                vectors.extend([it.get("embedding") or [] for it in items])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        out = self.embed_documents([text])
        return out[0] if out else []