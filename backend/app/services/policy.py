"""政策参数加载器。

经费标准、审批阈值、报销时限、校验开关等"规则参数"全部放在
`data/rules/*.yaml`，由本模块统一读取并可热加载。调整学院制度只需改 YAML，
无需修改任何业务代码。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..config import settings

DEFAULT_FINANCE_POLICY: dict[str, Any] = {
    "currency": "CNY",
    "approval": {
        "auto_approve_below": 5000,
        "register_threshold": 30000,
        "leader_threshold": 50000,
        "register_office": "教务处",
        "leader_role": "分管校领导",
    },
    "reimbursement": {
        "deadline_days_after_event": 30,
        "invoice_required": True,
        "invoice_required_above": 100,
        "require_budget_approved": True,
        "require_event_notice": True,
        "require_achievement_proof": False,
        "require_trip_approval": True,
        "max_over_budget_ratio": 0.0,
        "forbidden_keywords": ["接待", "礼品", "烟酒", "旅游", "景点门票", "娱乐", "罚款"],
        "forbidden_for_levels": [
            {
                "levels": ["校级"],
                "categories": ["住宿费", "交通费", "伙食补助", "市内交通"],
                "message": "校内比赛不得列支住宿费与差旅类费用",
            }
        ],
    },
    "loan": {
        "require_approved_budget": True,
        "single_borrow_limit": 20000,
        "must_clear_previous": True,
        "repay_within_days": 60,
        "allowed_roles": ["在编教师"],
    },
    "budget": {
        "max_mentor_share": 0.4,
        "require_achievement_basis": True,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


@lru_cache(maxsize=1)
def finance_policy() -> dict[str, Any]:
    raw = _load_yaml(settings.rules_path / "finance_policy.yaml")
    return _deep_merge(DEFAULT_FINANCE_POLICY, raw)


@lru_cache(maxsize=1)
def expense_standards_seed() -> list[dict[str, Any]]:
    data = _load_yaml(settings.rules_path / "expense_standards.yaml")
    items = data.get("standards") or []
    return [i for i in items if isinstance(i, dict)]


@lru_cache(maxsize=1)
def award_point_rules_seed() -> list[dict[str, Any]]:
    data = _load_yaml(settings.rules_path / "award_point_rules.yaml")
    return [i for i in (data.get("rules") or []) if isinstance(i, dict)]


@lru_cache(maxsize=1)
def competition_category_rules_seed() -> list[dict[str, Any]]:
    data = _load_yaml(settings.rules_path / "competition_category_rules.yaml")
    return [i for i in (data.get("rules") or []) if isinstance(i, dict)]


@lru_cache(maxsize=1)
def review_rubrics() -> dict[str, Any]:
    return _load_yaml(settings.rules_path / "review_rubrics.yaml")


@lru_cache(maxsize=1)
def recommend_weights() -> dict[str, Any]:
    return _load_yaml(settings.rules_path / "recommend_weights.yaml")


def reload_policy() -> None:
    finance_policy.cache_clear()
    expense_standards_seed.cache_clear()
    award_point_rules_seed.cache_clear()
    competition_category_rules_seed.cache_clear()
    review_rubrics.cache_clear()
    recommend_weights.cache_clear()