"""应用级角色权限。

角色由 X-User-Role 请求头传入。当前未接入统一身份认证，因此该请求头
由前端演示身份选择器提供；正式部署时应改为从 CAS/OAuth2 会话中注入，
并移除客户端自选角色的入口。所有权限判断集中在本模块，便于替换身份源。
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

ROLE_HEADER = "X-User-Role"
ROLES = ("学生", "教师", "管理员")
ROLE_ALIASES = {
    "student": "学生",
    "teacher": "教师",
    "admin": "管理员",
    "学生": "学生",
    "教师": "教师",
    "管理员": "管理员",
}

_READER = frozenset({
    "dashboard.view",
    "qa.use",
    "recommend.use",
    "prep.use",
    "review.use",
    "llm.use",
    "stats.view",
    "competitions.read",
    "export.result",
})

_STAFF = _READER | frozenset({
    "ledger.read",
    "finance.use",
    "knowledge.read",
    "export.use",
    "logs.view",
})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "学生": _READER,
    "教师": _STAFF,
    "管理员": _STAFF | frozenset({
        "competitions.write",
        "finance.approve",
        "knowledge.write",
        "workflows.use",
    }),
}

AGENT_PERMISSIONS = {
    "qa": "qa.use",
    "recommend": "recommend.use",
    "prep": "prep.use",
    "review": "review.use",
    "stats": "stats.view",
    "budget": "finance.use",
    "loan": "finance.use",
    "reimbursement": "finance.use",
}


def current_role(
    x_user_role: str | None = Header(default="student", alias=ROLE_HEADER),
) -> str:
    raw = (x_user_role or "student").strip()
    role = ROLE_ALIASES.get(raw)
    if not role:
        raise HTTPException(400, f"未知身份：{raw}，可选：student / teacher / admin")
    return role


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def require(*permissions: str):
    def dependency(role: str = Depends(current_role)) -> str:
        missing = [p for p in permissions if not has_permission(role, p)]
        if missing:
            raise HTTPException(403, f"当前身份（{role}）无权执行该操作")
        return role

    return dependency


def ensure_agent_access(agent: str, role: str) -> None:
    # 默认拒绝：新增智能体必须在 AGENT_PERMISSIONS 中显式授权
    permission = AGENT_PERMISSIONS.get(agent)
    if not permission or not has_permission(role, permission):
        raise HTTPException(403, f"当前身份（{role}）无权使用该智能体")


def ensure_session_access(session_role: str, role: str) -> None:
    if role != "管理员" and session_role != role:
        raise HTTPException(403, "无权访问其他身份的问答会话")
