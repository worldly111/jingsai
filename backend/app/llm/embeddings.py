"""向量模型：为知识库分块生成语义向量。

两套实现：
  - HashingEmbedder       离线可用（字符 n-gram + 分词 哈希到固定维度，带符号、L2 归一化），
                          无需外网与密钥，是零配置状态下的默认向量方案；
  - OpenAICompatEmbedder  接入通义 text-embedding-v3 / 豆包 embedding 等真实语义向量模型。

两者输出统一为 list[float]，向量库与检索层无需感知差异。
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any

from ..nlp import char_ngrams, tokenize
from .providers import OpenAICompatEmbedder


class HashingEmbedder:
    """离线哈希向量（一种 hashing vectorizer）。

    做法：把分词结果与字符 n-gram 通过稳定的 md5 哈希映射到固定维度，
    取哈希值的奇偶作为符号，词频做次线性缩放（1+log tf），最后 L2 归一化。
    该方案不需要训练，跨进程稳定，能在无外网环境下提供可用的语义近似能力。
    """

    provider = "builtin"
    label = "离线哈希向量"

    def __init__(self, dim: int = 512) -> None:
        self.dim = max(64, int(dim))
        self.model = f"builtin-hashing-{self.dim}"

    @property
    def is_available(self) -> bool:
        return True

    def info(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "label": self.label,
            "model": self.model,
            "dim": self.dim,
            "available": True,
        }

    # ---------- 内部 ----------
    def _features(self, text: str) -> Counter:
        feats: Counter = Counter()
        for tok in tokenize(text):
            feats[f"w:{tok}"] += 1.0
        for tok in tokenize(text, keep_stopwords=True):
            feats[f"c:{tok}"] += 0.35
        for gram in char_ngrams(text, 2):
            feats[f"g2:{gram}"] += 0.6
        for gram in char_ngrams(text, 3):
            feats[f"g3:{gram}"] += 0.3
        return feats

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.md5(feature.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % self.dim
        sign = 1.0 if digest[4] & 1 else -1.0
        return idx, sign

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feature, tf in self._features(text).items():
            idx, sign = self._bucket(feature)
            vec[idx] += sign * (1.0 + math.log(tf))
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 1e-9:
            vec = [v / norm for v in vec]
        return vec

    # ---------- 对外 ----------
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def build_embedder(cfg: dict[str, Any]) -> HashingEmbedder | OpenAICompatEmbedder:
    """根据配置构造向量模型；配置不完整时回退到离线实现。"""
    provider = str(cfg.get("provider", "builtin")).lower()
    if provider == "builtin":
        return HashingEmbedder(dim=int(cfg.get("dim", 512) or 512))

    base_url = str(cfg.get("base_url") or "")
    model = str(cfg.get("model") or "")
    if not (base_url and model):
        return HashingEmbedder(dim=int(cfg.get("dim", 512) or 512))

    return OpenAICompatEmbedder(
        base_url=base_url,
        model=model,
        api_key=str(cfg.get("api_key") or ""),
        dim=int(cfg.get("dim", 1024) or 1024),
        label=str(cfg.get("label") or "OpenAI 兼容向量模型"),
    )