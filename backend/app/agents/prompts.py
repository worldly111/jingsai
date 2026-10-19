"""Prompt 与工作流节点配置加载器。

每个智能体的 Prompt、节点说明、边关系、回答规则都放在 `backend/prompts/<agent>.yaml`。
修改 Prompt 或调整节点参数不需要改动 Python 代码；节点 id 与代码中的图结构一一对应，
`validate_registry()` 会在启动时做一致性校验，避免配置漂移。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..config import settings


@lru_cache(maxsize=32)
def load_agent_config(agent: str) -> dict[str, Any]:
    path: Path = settings.prompt_path / f"{agent}.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Prompt 配置解析失败：{path}：{exc}") from exc
    return data if isinstance(data, dict) else {}


def reload_prompts() -> None:
    load_agent_config.cache_clear()


def node_config(agent: str, node_id: str) -> dict[str, Any]:
    cfg = load_agent_config(agent)
    for node in cfg.get("nodes", []):
        if str(node.get("id")) == node_id:
            return node
    return {}


def node_title(agent: str, node_id: str) -> str:
    return str(node_config(agent, node_id).get("title") or node_id)


def render(template: str, values: dict[str, Any]) -> str:
    """极简模板渲染：只做 {key} 替换，缺失的值替换为空串，避免 str.format 抛异常。"""
    if not template:
        return ""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", "" if value is None else str(value))
    # 清理未被替换的占位符
    import re

    return re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", "", out)


def build_prompt(agent: str, node_id: str, values: dict[str, Any]) -> tuple[str, str]:
    cfg = node_config(agent, node_id)
    system = render(str(cfg.get("system") or ""), values)
    user = render(str(cfg.get("user") or ""), values)
    if not system:
        base = load_agent_config(agent)
        system = render(str(base.get("system") or ""), values)
    return system, user


def answer_rules(agent: str) -> list[str]:
    cfg = load_agent_config(agent)
    rules = cfg.get("answer_rules") or []
    return [str(r) for r in rules]


def list_agents() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(settings.prompt_path.glob("*.yaml")):
        cfg = load_agent_config(path.stem)
        if not cfg:
            continue
        out.append(
            {
                "agent": path.stem,
                "name": cfg.get("name", path.stem),
                "description": cfg.get("description", ""),
                "nodes": [
                    {"id": n.get("id"), "title": n.get("title"), "desc": n.get("desc", "")}
                    for n in cfg.get("nodes", [])
                ],
                "edges": cfg.get("edges", []),
                "answer_rules": cfg.get("answer_rules", []),
            }
        )
    return out


def validate_registry(graph_specs: dict[str, dict[str, Any]]) -> list[str]:
    """校验 YAML 中声明的节点与代码中的图结构是否一致，返回不一致项。"""
    problems: list[str] = []
    for agent, spec in graph_specs.items():
        cfg = load_agent_config(agent)
        if not cfg:
            problems.append(f"{agent}：缺少 prompts/{agent}.yaml")
            continue
        yaml_nodes = {str(n.get("id")) for n in cfg.get("nodes", [])}
        code_nodes = set(spec.get("nodes", []))
        if yaml_nodes != code_nodes:
            missing = code_nodes - yaml_nodes
            extra = yaml_nodes - code_nodes
            if missing:
                problems.append(f"{agent}：YAML 缺少节点 {sorted(missing)}")
            if extra:
                problems.append(f"{agent}：YAML 多出节点 {sorted(extra)}")
    return problems