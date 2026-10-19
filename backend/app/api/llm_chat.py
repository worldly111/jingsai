"""通用大模型问答接口。

面向全部角色（llm.use），与业务知识问答分开：不检索知识库、不读取台账，
模型只能在服务端目录内选择，密钥不会返回给前端。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..llm.catalog import (
    DISCLAIMER,
    build_chat_llm,
    catalog_payload,
    default_model_id,
    get_chat_model,
)
from ..security import require

logger = logging.getLogger(__name__)

router = APIRouter(tags=["通用问答"], dependencies=[Depends(require("llm.use"))])

SYSTEM_PROMPT = """你是高校学科竞赛辅助服务系统中的通用模型问答助手，面向学生、教师和管理员，提供通用知识、写作、编程与学习方面的帮助。

必须遵守的边界：
1. 你不读取本系统的赛事台账、知识库原文、经费单据和统计数据，无法核实本校最新的竞赛通知、报名截止时间、费用标准、获奖结果或审批状态。
2. 遇到上述事实性问题时，明确说明你无法核实，并建议用户前往“竞赛知识问答”或对应的业务页面查询；不得编造日期、金额、名额、政策条款或统计数据。
3. 使用简体中文回答，结构清晰；对不确定的内容要直接说明。"""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=1.2)
    max_tokens: int | None = Field(default=None, ge=1, le=4096)


@router.get("/llm/models")
def list_models() -> dict[str, Any]:
    return catalog_payload()


@router.post("/llm/chat")
def chat(body: ChatRequest) -> dict[str, Any]:
    messages = [
        {"role": item.role, "content": item.content.strip()}
        for item in body.messages
        if item.content.strip()
    ]
    if not messages or messages[-1]["role"] != "user":
        raise HTTPException(400, "最后一条消息必须是用户提问")
    if len(messages) > settings.llm_chat_max_messages:
        raise HTTPException(
            400,
            f"对话轮次过多（上限 {settings.llm_chat_max_messages} 条），请清空对话后重试",
        )
    total_chars = sum(len(item["content"]) for item in messages)
    if total_chars > settings.llm_chat_max_chars:
        raise HTTPException(
            413,
            f"对话内容过长（{total_chars} 字符，上限 {settings.llm_chat_max_chars}），请清空对话或缩短输入",
        )

    model_id = (body.model or default_model_id() or "").strip()
    if not model_id:
        raise HTTPException(503, "尚未配置可用的大模型，请在 backend/.env 中配置 API Key 后重启服务")
    try:
        entry = get_chat_model(model_id)
    except KeyError:
        raise HTTPException(400, f"未知模型：{model_id}") from None
    if not entry.available:
        raise HTTPException(503, f"{entry.label} 当前不可用：{entry.reason}")

    max_tokens = min(body.max_tokens or settings.llm_max_tokens, settings.llm_max_tokens)
    llm = build_chat_llm(entry, temperature=body.temperature, max_tokens=max_tokens)
    try:
        response = llm.chat(
            [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            max_tokens=max_tokens,
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("通用问答调用失败：%s status=%s", entry.id, status)
        if status in (401, 403):
            detail = f"{entry.label} 鉴权失败，请管理员检查 API Key"
        elif status == 429:
            detail = f"{entry.label} 请求频率或额度受限，请稍后重试"
        else:
            detail = f"{entry.label} 调用失败（HTTP {status}）"
        raise HTTPException(502, detail) from exc
    except httpx.TimeoutException as exc:
        logger.warning("通用问答调用超时：%s", entry.id)
        raise HTTPException(504, f"{entry.label} 响应超时，请稍后重试或切换模型") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("通用问答调用异常：%s", entry.id)
        raise HTTPException(502, f"{entry.label} 调用失败，请稍后重试或切换模型") from exc

    if not response.content.strip():
        raise HTTPException(502, f"{entry.label} 返回为空，请稍后重试或切换模型")

    return {
        "answer": response.content,
        "model_id": entry.id,
        "model": response.model or entry.model,
        "provider": entry.provider,
        "provider_label": entry.label,
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        },
        "latency_ms": response.latency_ms,
        "disclaimer": DISCLAIMER,
    }
