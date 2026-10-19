"""结构化业务数据模型。

设计原则：
1. 竞赛台账（赛事、届次、赛道、参赛、获奖）与经费单据、知识库分表存放，统计一律以本文件
   定义的结构化数据为准，不由大模型生成。
2. 费用标准、获奖积分、专业适配度等"规则"全部落表（expense_standards /
   award_point_rules / major_competition_fit），新增赛事或调整政策只需增删数据行，
   无需改动代码。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# ============================================================
#  一、基础主数据
# ============================================================
class Major(Base, TimestampMixin):
    """专业。"""

    __tablename__ = "majors"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    college: Mapped[str] = mapped_column(String(128), default="")
    discipline: Mapped[str] = mapped_column(String(64), default="")  # 学科门类，如 工学/计算机类
    description: Mapped[str] = mapped_column(Text, default="")

    students: Mapped[list["Student"]] = relationship(back_populates="major")


class Student(Base, TimestampMixin):
    """学生。"""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    gender: Mapped[str] = mapped_column(String(8), default="")
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id", ondelete="SET NULL"))
    major_name: Mapped[str] = mapped_column(String(128), default="", index=True)  # 冗余便于统计
    grade: Mapped[str] = mapped_column(String(32), default="", index=True)  # 入学年级，如 2023级
    class_name: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    # 技术方向标签，如 ["算法竞赛","前端开发","机器学习"]，用于竞赛推荐
    tech_tags: Mapped[list] = mapped_column(JSON, default=list)
    skill_level: Mapped[str] = mapped_column(String(32), default="")  # 入门/熟练/精通
    remark: Mapped[str] = mapped_column(Text, default="")

    major: Mapped[Major | None] = relationship(back_populates="students")


class Teacher(Base, TimestampMixin):
    """指导教师。"""

    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(32), default="")  # 职称
    college: Mapped[str] = mapped_column(String(128), default="")
    department: Mapped[str] = mapped_column(String(128), default="")
    research_areas: Mapped[list] = mapped_column(JSON, default=list)
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    can_mentor: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str] = mapped_column(Text, default="")


# ============================================================
#  二、竞赛台账
# ============================================================
class Competition(Base, TimestampMixin):
    """赛事本体的稳定信息（跨年度不变的部分）。"""

    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    short_name: Mapped[str] = mapped_column(String(128), default="")
    organizer: Mapped[str] = mapped_column(String(255), default="")  # 主办单位
    co_organizer: Mapped[str] = mapped_column(String(255), default="")  # 承办 / 协办
    # 认定级别：国家级 / 省级 / 校级；认定类别：A类 / B类 / C类（以学院目录为准，可维护）
    level: Mapped[str] = mapped_column(String(32), default="国家级", index=True)
    category: Mapped[str] = mapped_column(String(32), default="", index=True)
    competition_type: Mapped[str] = mapped_column(String(64), default="")  # 学科竞赛/创新创业/程序设计等
    discipline_tags: Mapped[list] = mapped_column(JSON, default=list)  # 适配学科方向
    official_url: Mapped[str] = mapped_column(String(512), default="")
    intro: Mapped[str] = mapped_column(Text, default="")
    target_audience: Mapped[str] = mapped_column(Text, default="")  # 面向对象
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    editions: Mapped[list["CompetitionEdition"]] = relationship(
        back_populates="competition", cascade="all, delete-orphan"
    )


class CompetitionEdition(Base, TimestampMixin):
    """赛事的某一届次（年度），承载时间节点、报名费、奖项设置等年度差异信息。"""

    __tablename__ = "competition_editions"
    __table_args__ = (
        UniqueConstraint("competition_id", "year", "edition_name", name="uq_edition"),
        Index("ix_edition_year_comp", "year", "competition_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(Integer, index=True)
    edition_name: Mapped[str] = mapped_column(String(128), default="")  # 如 第十八届
    notice_title: Mapped[str] = mapped_column(String(255), default="")
    notice_no: Mapped[str] = mapped_column(String(128), default="")  # 通知文号
    issued_by: Mapped[str] = mapped_column(String(255), default="")
    issued_date: Mapped[date | None] = mapped_column(Date)
    register_start: Mapped[date | None] = mapped_column(Date)
    register_end: Mapped[date | None] = mapped_column(Date)
    competition_period: Mapped[str] = mapped_column(String(128), default="")  # 比赛时间说明
    # 参赛资格与组队规则
    eligibility: Mapped[str] = mapped_column(Text, default="")
    team_size_min: Mapped[int] = mapped_column(Integer, default=1)
    team_size_max: Mapped[int] = mapped_column(Integer, default=1)
    mentor_limit: Mapped[int] = mapped_column(Integer, default=1)
    # 参赛费用与材料
    registration_fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    fee_note: Mapped[str] = mapped_column(Text, default="")
    required_materials: Mapped[list] = mapped_column(JSON, default=list)
    material_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="往届")  # 往届/进行中/筹备中
    source_ref: Mapped[str] = mapped_column(String(512), default="")  # 资料出处 / 链接

    competition: Mapped[Competition] = relationship(back_populates="editions")
    tracks: Mapped[list["CompetitionTrack"]] = relationship(
        back_populates="edition", cascade="all, delete-orphan"
    )
    milestones: Mapped[list["EditionMilestone"]] = relationship(
        back_populates="edition", cascade="all, delete-orphan"
    )
    award_rules: Mapped[list["AwardSetting"]] = relationship(
        back_populates="edition", cascade="all, delete-orphan"
    )


class CompetitionTrack(Base, TimestampMixin):
    """赛道 / 赛项方向。"""

    __tablename__ = "competition_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("competition_editions.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[list] = mapped_column(JSON, default=list)  # 提交材料/技术要求
    team_size_min: Mapped[int | None] = mapped_column(Integer)
    team_size_max: Mapped[int | None] = mapped_column(Integer)
    fee: Mapped[float | None] = mapped_column(Numeric(12, 2))
    discipline_tags: Mapped[list] = mapped_column(JSON, default=list)

    edition: Mapped[CompetitionEdition] = relationship(back_populates="tracks")


class EditionMilestone(Base, TimestampMixin):
    """届次时间节点：报名、校赛、省赛、国赛、作品提交、答辩等。"""

    __tablename__ = "edition_milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("competition_editions.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(32), default="")  # 报名/校赛/省赛/国赛/提交/答辩
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str] = mapped_column(Text, default="")

    edition: Mapped[CompetitionEdition] = relationship(back_populates="milestones")


class AwardSetting(Base, TimestampMixin):
    """奖项设置：等级、比例、奖励方式。"""

    __tablename__ = "award_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("competition_editions.id", ondelete="CASCADE"))
    award_level: Mapped[str] = mapped_column(String(32))  # 特等奖/一等奖/二等奖/三等奖/优胜奖
    ratio: Mapped[str] = mapped_column(String(64), default="")  # 获奖比例，如 "10%"
    quantity: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="")  # 国家级/省级
    prize: Mapped[str] = mapped_column(Text, default="")  # 奖金 / 奖励方式
    note: Mapped[str] = mapped_column(Text, default="")

    edition: Mapped[CompetitionEdition] = relationship(back_populates="award_rules")


class Registration(Base, TimestampMixin):
    """参赛记录（一支队伍在某一届次某一赛道的一次参赛）。"""

    __tablename__ = "registrations"
    __table_args__ = (Index("ix_reg_year_status", "year", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"))
    edition_id: Mapped[int | None] = mapped_column(ForeignKey("competition_editions.id", ondelete="SET NULL"))
    track_id: Mapped[int | None] = mapped_column(ForeignKey("competition_tracks.id", ondelete="SET NULL"))
    year: Mapped[int] = mapped_column(Integer, index=True)
    # 冗余字段，便于不联表统计
    competition_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    track_name: Mapped[str] = mapped_column(String(255), default="")
    competition_level: Mapped[str] = mapped_column(String(32), default="", index=True)
    competition_category: Mapped[str] = mapped_column(String(32), default="")
    team_name: Mapped[str] = mapped_column(String(128), default="")
    project_title: Mapped[str] = mapped_column(String(255), default="")
    project_brief: Mapped[str] = mapped_column(Text, default="")
    # 状态流转：报名中 / 备赛中 / 已提交 / 参赛中 / 已完赛 / 获奖 / 退赛
    status: Mapped[str] = mapped_column(String(32), default="报名中", index=True)
    register_date: Mapped[date | None] = mapped_column(Date)
    finish_date: Mapped[date | None] = mapped_column(Date)
    stage_reached: Mapped[str] = mapped_column(String(32), default="")  # 校赛/省赛/国赛
    lead_major: Mapped[str] = mapped_column(String(128), default="", index=True)  # 队长专业，统计用
    leader_name: Mapped[str] = mapped_column(String(64), default="")
    mentor_names: Mapped[str] = mapped_column(String(255), default="")  # 指导教师姓名（多值逗号分隔，便于统计）
    remark: Mapped[str] = mapped_column(Text, default="")

    members: Mapped[list["RegistrationMember"]] = relationship(
        back_populates="registration", cascade="all, delete-orphan"
    )
    mentors: Mapped[list["RegistrationMentor"]] = relationship(
        back_populates="registration", cascade="all, delete-orphan"
    )
    awards: Mapped[list["Award"]] = relationship(
        back_populates="registration", cascade="all, delete-orphan"
    )


class RegistrationMember(Base):
    """参赛队员。"""

    __tablename__ = "registration_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"))
    student_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    student_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    major_name: Mapped[str] = mapped_column(String(128), default="", index=True)
    grade: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(32), default="队员")  # 队长 / 队员
    order_no: Mapped[int] = mapped_column(Integer, default=1)

    registration: Mapped[Registration] = relationship(back_populates="members")


class RegistrationMentor(Base):
    """指导教师关联。"""

    __tablename__ = "registration_mentors"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"))
    teacher_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    role: Mapped[str] = mapped_column(String(32), default="指导教师")  # 第一指导教师 / 指导教师
    order_no: Mapped[int] = mapped_column(Integer, default=1)

    registration: Mapped[Registration] = relationship(back_populates="mentors")


class Award(Base, TimestampMixin):
    """获奖记录。"""

    __tablename__ = "awards"
    __table_args__ = (Index("ix_award_year_level", "award_year", "award_level"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(Integer, index=True)
    award_year: Mapped[int] = mapped_column(Integer, index=True)  # 获奖年份（可能与参赛年份不同）
    competition_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    track_name: Mapped[str] = mapped_column(String(255), default="")
    # 获奖等级：特等奖 / 一等奖 / 二等奖 / 三等奖 / 优胜奖 / 入围奖
    award_level: Mapped[str] = mapped_column(String(32), index=True)
    # 级别归属：国家级 / 省级 / 校级（与赛事认定一致）
    award_grade: Mapped[str] = mapped_column(String(32), default="", index=True)
    competition_level: Mapped[str] = mapped_column(String(32), default="", index=True)
    project_title: Mapped[str] = mapped_column(String(255), default="")
    team_name: Mapped[str] = mapped_column(String(128), default="")
    students: Mapped[str] = mapped_column(String(512), default="")  # 获奖学生姓名，逗号分隔
    majors: Mapped[str] = mapped_column(String(255), default="", index=True)  # 涉及专业
    mentors: Mapped[str] = mapped_column(String(255), default="", index=True)
    issuing_body: Mapped[str] = mapped_column(String(255), default="")
    certificate_no: Mapped[str] = mapped_column(String(128), default="")
    award_date: Mapped[date | None] = mapped_column(Date)
    points: Mapped[float] = mapped_column(Float, default=0)  # 按 award_point_rules 折算
    remark: Mapped[str] = mapped_column(Text, default="")

    registration: Mapped[Registration | None] = relationship(back_populates="awards")


# ============================================================
#  三、经费：预算 / 借款 / 报销
# ============================================================
class ExpenseStandard(Base, TimestampMixin):
    """费用标准规则表 —— 预算与报销的计算依据，全部可维护，不固化在代码中。"""

    __tablename__ = "expense_standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    # 费用类别：报名费/交通费/住宿费/伙食补助/市内交通/耗材费/测试费/劳务费/其他
    category: Mapped[str] = mapped_column(String(64), index=True)
    # 适用级别：国家级/省级/校级/不限
    competition_level: Mapped[str] = mapped_column(String(32), default="不限")
    region: Mapped[str] = mapped_column(String(64), default="不限")  # 地区（住宿/伙食标准用）
    # 取值方式：固定金额 fixed / 单价 unit_price / 上限 cap / 比例 ratio
    value_type: Mapped[str] = mapped_column(String(32), default="cap")
    value: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(32), default="元/人")  # 元/人、元/人·天、元/队
    condition: Mapped[dict] = mapped_column(JSON, default=dict)  # 附加条件，如 {"student_only": true}
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(512), default="")  # 制度出处
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Budget(Base, TimestampMixin):
    """竞赛经费预算申请单。"""

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id", ondelete="SET NULL"))
    competition_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    applicant_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"))
    applicant_name: Mapped[str] = mapped_column(String(64), default="")
    team_name: Mapped[str] = mapped_column(String(128), default="")
    student_count: Mapped[int] = mapped_column(Integer, default=0)
    teacher_count: Mapped[int] = mapped_column(Integer, default=0)
    destination: Mapped[str] = mapped_column(String(128), default="")
    trip_days: Mapped[int] = mapped_column(Integer, default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    approved_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    status: Mapped[str] = mapped_column(String(32), default="草稿", index=True)  # 草稿/待审批/已批准/已驳回
    basis: Mapped[str] = mapped_column(Text, default="")  # 预算依据说明
    reviewer: Mapped[str] = mapped_column(String(64), default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    review_date: Mapped[date | None] = mapped_column(Date)
    generated_text: Mapped[str] = mapped_column(Text, default="")  # 由工作流生成的申请正文
    agent_trace: Mapped[dict] = mapped_column(JSON, default=dict)  # 工作流节点轨迹
    remark: Mapped[str] = mapped_column(Text, default="")

    items: Mapped[list["BudgetItem"]] = relationship(
        back_populates="budget", cascade="all, delete-orphan"
    )


class BudgetItem(Base):
    """预算明细行。"""

    __tablename__ = "budget_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    item_name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(32), default="")
    quantity: Mapped[float] = mapped_column(Float, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    standard_code: Mapped[str] = mapped_column(String(64), default="")  # 引用的费用标准
    calc_basis: Mapped[str] = mapped_column(Text, default="")  # 计算依据说明（供审核）
    remark: Mapped[str] = mapped_column(Text, default="")

    budget: Mapped[Budget] = relationship(back_populates="items")


class Loan(Base, TimestampMixin):
    """借款单（暂付款）。"""

    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("budgets.id", ondelete="SET NULL"))
    registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id", ondelete="SET NULL"))
    borrower_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"))
    borrower_name: Mapped[str] = mapped_column(String(64), default="")
    borrower_no: Mapped[str] = mapped_column(String(32), default="")
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    amount_upper: Mapped[str] = mapped_column(String(128), default="")  # 大写金额
    purpose: Mapped[str] = mapped_column(String(255), default="")
    competition_name: Mapped[str] = mapped_column(String(255), default="")
    destination: Mapped[str] = mapped_column(String(128), default="")
    expected_repay_date: Mapped[date | None] = mapped_column(Date)
    payee: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="草稿", index=True)  # 草稿/待审批/已借出/已冲销
    generated_content: Mapped[dict] = mapped_column(JSON, default=dict)  # 借款单各字段
    checks: Mapped[list] = mapped_column(JSON, default=list)  # 校验结果
    agent_trace: Mapped[dict] = mapped_column(JSON, default=dict)
    remark: Mapped[str] = mapped_column(Text, default="")


class Reimbursement(Base, TimestampMixin):
    """报销单。"""

    __tablename__ = "reimbursements"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("budgets.id", ondelete="SET NULL"))
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id", ondelete="SET NULL"))
    registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id", ondelete="SET NULL"))
    competition_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    claimant_name: Mapped[str] = mapped_column(String(64), default="")  # 报销人
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    approved_budget_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    loan_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(32), default="草稿", index=True)
    # 材料完整性校验结果：[{code, level, message, suggestion}]
    checks: Mapped[list] = mapped_column(JSON, default=list)
    completeness_score: Mapped[float] = mapped_column(Float, default=0)
    generated_text: Mapped[str] = mapped_column(Text, default="")
    agent_trace: Mapped[dict] = mapped_column(JSON, default=dict)
    remark: Mapped[str] = mapped_column(Text, default="")

    items: Mapped[list["ReimbursementItem"]] = relationship(
        back_populates="reimbursement", cascade="all, delete-orphan"
    )


class ReimbursementItem(Base):
    """报销明细行。"""

    __tablename__ = "reimbursement_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    reimbursement_id: Mapped[int] = mapped_column(ForeignKey("reimbursements.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    item_name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    expense_date: Mapped[date | None] = mapped_column(Date)
    invoice_no: Mapped[str] = mapped_column(String(64), default="")
    has_invoice: Mapped[bool] = mapped_column(Boolean, default=True)
    payee: Mapped[str] = mapped_column(String(128), default="")
    standard_code: Mapped[str] = mapped_column(String(64), default="")
    over_standard: Mapped[bool] = mapped_column(Boolean, default=False)
    calc_basis: Mapped[str] = mapped_column(Text, default="")
    remark: Mapped[str] = mapped_column(Text, default="")

    reimbursement: Mapped[Reimbursement] = relationship(back_populates="items")


# ============================================================
#  四、规则表（驱动推荐、积分、经费，全部数据化）
# ============================================================
class MajorCompetitionFit(Base, TimestampMixin):
    """专业 / 技术方向 与赛事的适配度矩阵，驱动竞赛推荐。"""

    __tablename__ = "major_competition_fit"

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"), index=True)
    match_type: Mapped[str] = mapped_column(String(32), default="major")  # major / tech_tag / level
    match_value: Mapped[str] = mapped_column(String(128), index=True)  # 专业名或技术标签
    fit_score: Mapped[float] = mapped_column(Float, default=0.8)
    reason: Mapped[str] = mapped_column(Text, default="")
    recommended_grade: Mapped[str] = mapped_column(String(64), default="")  # 建议年级
    difficulty: Mapped[str] = mapped_column(String(32), default="中")  # 入门/中/高


class AwardPointRule(Base, TimestampMixin):
    """获奖积分 / 教师工作量折算规则。"""

    __tablename__ = "award_point_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    award_grade: Mapped[str] = mapped_column(String(32), index=True)  # 国家级/省级/校级
    award_level: Mapped[str] = mapped_column(String(32), index=True)  # 特等奖/一等奖...
    student_points: Mapped[float] = mapped_column(Float, default=0)
    teacher_workload: Mapped[float] = mapped_column(Float, default=0)  # 折算工作量（课时）
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(512), default="")


class CompetitionCategoryRule(Base, TimestampMixin):
    """竞赛认定目录：赛事等级 / 类别认定，供新增赛事时维护。"""

    __tablename__ = "competition_category_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_name_pattern: Mapped[str] = mapped_column(String(255), index=True)
    level: Mapped[str] = mapped_column(String(32), default="国家级")
    category: Mapped[str] = mapped_column(String(32), default="")
    score: Mapped[float] = mapped_column(Float, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(512), default="")


# ============================================================
#  五、知识库
# ============================================================
class KbDocument(Base, TimestampMixin):
    """知识库文档：竞赛通知、规程、管理办法等。"""

    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512), index=True)
    doc_type: Mapped[str] = mapped_column(String(64), default="其他", index=True)
    # 通知公告 / 竞赛规程 / 管理制度 / 获奖名单 / 评审标准 / 其他
    competition_id: Mapped[int | None] = mapped_column(ForeignKey("competitions.id", ondelete="SET NULL"))
    competition_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    issuing_body: Mapped[str] = mapped_column(String(255), default="")
    doc_no: Mapped[str] = mapped_column(String(128), default="")
    effective_date: Mapped[date | None] = mapped_column(Date)
    file_name: Mapped[str] = mapped_column(String(512), default="")
    source_path: Mapped[str] = mapped_column(String(1024), default="")
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    mime_type: Mapped[str] = mapped_column(String(128), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # 状态：待处理/已入库/失败
    status: Mapped[str] = mapped_column(String(32), default="待处理", index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    error_msg: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)

    chunks: Mapped[list["KbChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KbChunk(Base):
    """知识库分块，含向量与来源定位信息，用于引用溯源。"""

    __tablename__ = "kb_chunks"
    __table_args__ = (Index("ix_chunk_doc_idx", "document_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    section: Mapped[str] = mapped_column(String(512), default="")  # 所属章节 / 标题路径
    page_no: Mapped[int | None] = mapped_column(Integer)
    row_ref: Mapped[str] = mapped_column(String(255), default="")  # Excel 行位置等
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[str] = mapped_column(Text, default="")  # 分词结果缓存，加速关键词检索
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    embedding_dim: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    document: Mapped[KbDocument] = relationship(back_populates="chunks")


class QaLog(Base, TimestampMixin):
    """问答日志，用于准确率评估与测试报告。"""

    __tablename__ = "qa_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("chat_sessions.id", ondelete="SET NULL"))
    agent: Mapped[str] = mapped_column(String(64), default="qa")
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    llm_provider: Mapped[str] = mapped_column(String(64), default="")
    used_knowledge: Mapped[bool] = mapped_column(Boolean, default=False)
    used_structured_data: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[str] = mapped_column(String(32), default="")  # 有用 / 无用
    feedback_note: Mapped[str] = mapped_column(Text, default="")


# ============================================================
#  六、会话与工作流运行日志
# ============================================================
class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    agent: Mapped[str] = mapped_column(String(64), default="qa", index=True)
    user_role: Mapped[str] = mapped_column(String(32), default="学生")  # 学生/教师/管理员
    user_ref: Mapped[str] = mapped_column(String(64), default="")  # 学号 / 工号
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # 会话级上下文（如学生画像）

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # 结构化结果（推荐列表、预算表等）
    agent_trace: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class AgentRunLog(Base):
    """工作流运行日志：记录每个节点耗时与产出摘要，便于调试与验收。"""

    __tablename__ = "agent_run_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    node_trace: Mapped[list] = mapped_column(JSON, default=list)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="success")
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    llm_provider: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)