# Prompt 与工作流配置

系统使用 LangGraph 编排 8 个智能体，共 **32 个节点**。每个节点的 Prompt、标题、说明与全局回答规则都放在 `backend/prompts/<agent>.yaml`，代码只负责节点逻辑与图结构。启动时 `validate_graphs()` 会校验 YAML 声明与代码节点是否一致，避免配置漂移。

## 1. 运行机制

```
用户请求
  → FastAPI /api/agents/{agent}/run
  → runner 组装 AgentState（question / profile / payload / user_role / session）
  → LangGraph 依次执行节点
      ├── 配置了大模型：节点调用 LLM 做抽取或生成
      └── 未配置或调用失败：节点使用规则/台账完成同样的产出
  → 汇总 answer / sections / tables / charts / checks / citations / structured
  → 写入 agent_run_logs、qa_logs、chat_messages
  → 前端 ResultView 渲染 Markdown、表格、图表、引用与节点轨迹
```

关键点：

- **双通道输出同构**：无论离线还是大模型，`AgentState` 字段一致，前端和导出模块无需感知模式。
- **单节点容错**：节点异常被包装为 `error` 与 `trace` 条目，不会中断整条工作流。
- **Prompt 外置**：文本节点（生成回答）读 `system`/`user`；抽取节点还声明 `output_schema`，供维护者参考，实际解析使用健壮的 JSON 提取与规则兜底。
- **回答规则注入**：`answer_rules` 在合成节点拼接进 Prompt；离线回答也遵循同一套业务约束（如引用格式、金额来源）。
- **缓存**：Prompt 使用 `lru_cache`，修改 YAML 后需重启服务；知识库索引也在进程内缓存，文档变更后自动或手动重建。

### 1.1 角色与鉴权边界

工作流运行前，API 层先完成身份与权限校验，再把可信角色写入 `AgentState.user_role`：

```
X-User-Role → current_role() → ensure_agent_access(agent, role)
           → runner.run_agent(..., user_role=role) → AgentState.user_role
```

- 智能体与权限的映射集中在 `backend/app/security.py` 的 `AGENT_PERMISSIONS`：`qa` / `recommend` / `prep` / `review` / `stats` / `export.result` 对所有身份开放；`budget` / `loan` / `reimbursement` 归属 `finance.use`（教师、管理员）。
- **默认拒绝**：新增智能体若未在 `AGENT_PERMISSIONS` 中登记，所有身份均无法运行；必须在接入时显式授权。
- 请求体里的 `user_role` 不参与授权，后端始终以验证后的请求头角色覆盖它；Prompt 仅用该字段调整称谓与建议口径，不能作为权限判断依据。
- `GET /api/meta/agents` 会按当前身份过滤，学生只能看到 5 个通用智能体，教师与管理员看到 8 个。
- 会话 `session_id` 需通过所属身份校验，跨身份运行或读取返回 `403`。

### 1.2 通用模型问答不属于 LangGraph 工作流

「通用模型问答」是独立的通用对话能力，刻意不纳入 8 个业务智能体：

- 不注册到 `AGENT_PERMISSIONS`，不出现在 `GET /api/meta/agents`，也不参与 `validate_graphs()` 的节点校验。
- 不读写 `AgentState`，不检索知识库、不读取台账、不生成引用，不写入 `agent_run_logs` / `qa_logs` / `chat_messages`。
- 模型目录与可用性判断在 `backend/app/llm/catalog.py`：只暴露模型标识、名称、说明与可用状态，密钥与端点仅在后端读取。
- 接口与固定系统边界在 `backend/app/api/llm_chat.py`：`GET /api/llm/models`、`POST /api/llm/chat`，统一要求 `llm.use` 权限；系统提示词由后端注入，客户端只能提交 `user` / `assistant` 消息。
- Prompt 不放在 `backend/prompts/`，避免被当作可配置的业务智能体；调整回答边界应修改 `SYSTEM_PROMPT` 并重启服务。

如果需要让通用问答具备业务流程（检索、台账、引用、导出），应新增正式的 LangGraph 智能体，而不是扩展本页面。

## 2. Prompt 配置文件规范

以 `prompts/qa.yaml` 为例：

```yaml
agent: qa
name: 竞赛知识问答
description: 面向学生与教师的竞赛政策、通知、规程问答。强制走知识库检索，回答必须给出原文出处。
mode: 知识检索增强（RAG）

answer_rules:
  - 涉及政策条款、时间节点、报名条件、材料清单、奖项设置等事实性内容时，必须基于检索片段作答，不得凭模型记忆编造。
  - 每个结论后标注引用编号，格式为 [^n]，n 与"参考资料"中的序号一致。
  - 检索片段中没有的内容，明确回答"知识库中未收录相关内容"，并说明需要补充哪份文件。
  - 涉及统计数字的问题，优先引用结构化台账数据，并在回答中标明"数据来源：竞赛台账"。

nodes:
  - id: understand
    title: 问题理解与查询扩展
    desc: 识别问题意图，抽取赛事名称、年份、条款主题，并扩展为多个检索查询。
    system: |
      你是高校学科竞赛业务的理解助手……
    user: |
      用户问题：{question}
      对话上下文：{history}
      已知赛事名单：{competition_names}
      请完成……
      以 JSON 输出：{{"intent": "", "competition": "", "year": null, "queries": []}}
    output_schema:
      intent: string
      competition: string
      year: number|null
      queries: string[]
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `agent` | 是 | 智能体标识，需与文件名一致 |
| `name` / `description` / `mode` | 否 | 工作流页面展示的名称、说明与模式标签 |
| `answer_rules` | 否 | 合成节点的业务约束列表，逐条注入 Prompt |
| `nodes[].id` | 是 | 节点 id，必须与 `app/agents/graphs.py` 中的节点一致 |
| `nodes[].title` | 否 | 节点显示名，用于轨迹与页面 |
| `nodes[].desc` | 否 | 节点说明，用于「智能体工作流」页面 |
| `nodes[].system` | 否 | System Prompt；为空时回退到 `agent.system` |
| `nodes[].user` | 否 | User Prompt 模板 |
| `nodes[].output_schema` | 否 | 期望的 JSON 结构，供维护与评审参考 |
| `edges` | 否 | 仅用于文档展示；实际边以代码 `GRAPH_SPECS` 为准 |

模板占位符使用 `{name}` 形式，渲染器只做字符串替换，缺失值替换为空串，不抛异常。代码中存在但模板未使用的变量会被清理，避免把 `{...}` 原样发给模型。

## 3. 八个工作流

### 3.1 竞赛知识问答（qa，6 节点）

| 节点 | 职责 | 关键输入 | 产出 |
| --- | --- | --- | --- |
| `understand` | 意图识别、赛事/年份抽取、查询扩展 | `question`、`history`、赛事名单 | `intent`、`queries`、`filters` |
| `retrieve` | 向量 + 关键词混合检索，按赛事/年份限定范围 | 查询列表 | `evidence`、`citations` |
| `structured_lookup` | 查询赛事届次、时间节点、奖项设置与台账统计 | 赛事、年份、意图 | `structured`、`tables` |
| `grade` | 判断证据是否充分；不足时改写查询重试一次 | 证据数量与最高分 | `need_retry`、`gaps` |
| `synthesize` | 有模型时综合证据生成回答；否则抽取式合成 | 证据、结构化数据、回答规则 | `answer`、`sections` |
| `fallback` | 无任何召回时的如实说明与补资料指引 | 问题、知识库统计 | `answer` |

图结构：

```
START → understand → retrieve
retrieve → structured_lookup（有证据） / fallback（无证据）
structured_lookup → grade
grade → retrieve（证据不足且未重试） / synthesize（证据充分或重试后）
synthesize → END
fallback → END
```

数据优先级：结构化赛事信息与台账统计优先于模型记忆；知识库原文用于政策、时间、材料与奖项条款。引用保留 `[^n]` 编号，与「参考资料」一一对应。

### 3.2 竞赛推荐（recommend，4 节点）

| 节点 | 职责 |
| --- | --- |
| `parse_profile` | 解析专业、年级、技术方向、项目基础、意向级别；规则与模型结果合并 |
| `score` | 按 `major_competition_fit` 与 `recommend_weights.yaml` 计算适配度，输出前 6 项 |
| `enrich_kb` | 为前 3 个候选赛事检索报名与材料要求片段 |
| `synthesize` | 生成推荐清单、推荐理由、台账参考与下一步动作 |

```
START → parse_profile → score → enrich_kb → synthesize → END
```

打分维度：专业适配、技术方向、年级、项目情况、级别偏好、报名时效。权重在 `data/rules/recommend_weights.yaml`，赛事适配数据在数据库 `major_competition_fit`，均无需改代码。

### 3.3 备赛辅助（prep，4 节点）

| 节点 | 职责 |
| --- | --- |
| `resolve_event` | 按名称/ID 定位赛事与届次；未识别时返回可选赛事 |
| `build_plan` | 以目标日期或报名截止倒排阶段，生成任务、交付物与材料清单 |
| `retrieve_materials` | 检索该赛事规程中的材料与组队要求 |
| `synthesize` | 输出备赛方案，附提醒与台账参考 |

```
START → resolve_event → build_plan → retrieve_materials → synthesize → END
```

报名已截止时仍输出该届材料与时间信息，但明确提示不再按该届节点倒排。

### 3.4 项目指导辅助（review，4 节点）

| 节点 | 职责 |
| --- | --- |
| `prepare_text` | 识别材料类型、统计字数；空材料返回提示 |
| `rule_check` | 按 `review_rubrics.yaml` 检查章节、篇幅、要素关键词与规范性，计算评分 |
| `llm_suggest` | 可选：大模型生成改写建议、追问；离线时使用量表内置建议 |
| `compose` | 汇总评分、问题分级、亮点与预答辩问题 |

```
START → prepare_text → rule_check → llm_suggest → compose → END
```

评分量表可按材料类型扩展；`llm_suggest` 的失败不会影响规则检查结果，只会记录为离线模式。

### 3.5 预算申请辅助（budget，4 节点）

| 节点 | 职责 |
| --- | --- |
| `parse_params` | 抽取赛事、人数、地点、天数、交通、报名费等要素，规则兜底 |
| `compute` | 按费用标准计算明细、合计、大写金额、审批路径与校验项 |
| `policy_lookup` | 检索经费管理办法与差旅标准原文 |
| `compose` | 生成预算说明、明细表、风险提示与申请正文 |

```
START → parse_params → compute → policy_lookup → compose → END
```

金额只来自 `expense_standards` 与 `finance_policy.yaml`，模型不得编造单价。每行明细带 `standard_code` 与 `calc_basis`，供财务审核。

### 3.6 借款辅助（loan，3 节点）

| 节点 | 职责 |
| --- | --- |
| `load_budget` | 按预算单号/ID 读取已批准预算，解析借款人、金额、用途等 |
| `compute` | 生成借款单要素、金额大写、预计冲销日期并执行校验 |
| `compose` | 输出借款单字段、校验结论与后续步骤 |

```
START → load_budget → compute → compose → END
```

校验包括：预算存在且已批准、借款金额不超过预算、借款人信息完整、前账是否未清、预计冲销日期是否合理。

### 3.7 报销辅助（reimbursement，3 节点）

| 节点 | 职责 |
| --- | --- |
| `parse_items` | 解析支出明细、票据号、日期、发票状态与关联预算/借款 |
| `compute` | 汇总金额、计算完整性评分，校验缺票、超标、超预算、时限、支付对象 |
| `compose` | 输出报销单、补件清单、预算/借款冲销提示 |

```
START → parse_items → compute → compose → END
```

校验规则来自 `finance_policy.yaml` 与 `expense_standards`；完整性评分按材料项权重计算。无明细时直接返回可解释提示，不生成空单据。

### 3.8 竞赛数据统计（stats，4 节点）

| 节点 | 职责 |
| --- | --- |
| `parse_query` | 解析年度、赛事、专业、级别、获奖等级、统计维度与图表类型 |
| `query` | 从结构化台账聚合总览与维度明细，生成数据表 |
| `chart` | 生成 ECharts 配置（趋势/柱状/饼图/热力图等） |
| `compose` | 按口径生成关键结论、明细表与建议 |

```
START → parse_query → query → chart → compose → END
```

图表失败不会影响数据表与结论；统计结果直接来自 `registrations` / `awards` / `registration_members` / `registration_mentors`。

## 4. 代码结构与扩展

| 文件 | 职责 |
| --- | --- |
| `app/agents/state.py` | `AgentState` 定义、`trace_entry()` |
| `app/agents/graphs.py` | 32 个节点实现、`GRAPH_SPECS`、图编译与校验 |
| `app/agents/tools.py` | 检索、抽取、统计过滤、引用构造、格式化等工具 |
| `app/agents/prompts.py` | YAML 加载、模板渲染、节点标题、注册表校验 |
| `app/agents/runner.py` | 运行入口、状态初始化、日志落库、结果组装 |
| `prompts/*.yaml` | 8 个智能体的 Prompt、节点说明与回答规则 |

### 4.1 调整 Prompt

1. 修改 `backend/prompts/<agent>.yaml` 的 `system`、`user` 或 `answer_rules`。
2. 保持节点 `id` 不变；如新增/删除节点，必须同步修改 `graphs.py` 中的 `GRAPH_SPECS`。
3. 重启服务，在「智能体工作流」点击「校验配置」，并运行一次在线测试台。
4. 检查节点轨迹、引用与结构化结果是否符合预期；离线回答由规则模板生成，修改 Prompt 只影响大模型通道与回答规则注入。

### 4.2 调整业务规则

| 需求 | 修改位置 | 是否需改代码 |
| --- | --- | --- |
| 调整预算单价/上限 | 「经费辅助 → 费用标准」或 `expense_standards` 表 | 否 |
| 调整审批金额阈值、报销时限 | `data/rules/finance_policy.yaml` | 否 |
| 调整推荐权重/年级档位 | `data/rules/recommend_weights.yaml` | 否 |
| 新增赛事适配 | 「赛事台账」或 `competitions.json` 的 `fits` | 否 |
| 调整积分/工作量 | `data/rules/award_point_rules.yaml` 后重新导入 | 否 |
| 新增材料类型/检查项 | `data/rules/review_rubrics.yaml` | 否 |
| 新增统计维度 | `StatsService` + `graphs.py` 的 `_STATS_COLUMNS` | 是 |
| 调整角色对智能体的可用范围 | `app/security.py` 的 `AGENT_PERMISSIONS` | 是（权限矩阵代码） |

### 4.3 新增一个智能体

1. 在 `app/agents/graphs.py` 实现节点函数，使用 `_wrap` 包装（或直接注册到 `_mk_graph`）。
2. 在 `GRAPH_SPECS` 注册节点、边与条件路由。
3. 新建 `prompts/<new_agent>.yaml`，节点 id 与代码一致。
4. 在 `AGENT_LABELS` 增加中文名，按需在 `runner.py` 的输入处理中补充字段。
5. 在 `app/security.py` 的 `AGENT_PERMISSIONS` 登记权限；未登记时默认拒绝所有身份，登记后才出现在对应角色的可用列表中。
6. 前端「智能体工作流」会自动读取配置；如需专属页面，在 `frontend/src/router.js`、`auth.js` 的权限矩阵与 `views/` 增加路由、权限与组件。
7. 运行 `validate_graphs()` 与 `scripts/smoke_agents.py`，确认无缺失节点；再用三角色请求头各调用一次接口验证 403/200 边界。

新增智能体不需要修改数据库表；运行记录写入现有 `agent_run_logs`。

## 5. 校验与排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 「校验配置」提示 YAML 缺少节点 | 代码新增节点未补 YAML | 在对应 YAML 增加同名 `id` |
| 修改 Prompt 不生效 | 进程缓存 | 重启 uvicorn |
| 大模型结果不稳定 | 温度或 Prompt 过长 | 调整 `LLM_TEMPERATURE`、精简证据或限制输出长度 |
| 工作流显示 offline | 密钥/端点/模型不完整或调用失败 | 查看 `/api/health`、后端日志；系统会自动回退 |
| 回答缺少引用 | 检索无命中或模型未按规则输出 | 检查知识库命中；离线通道会追加参考资料；必要时强化 `answer_rules` |
| 节点耗时异常 | 大模型超时或检索索引重建 | 查看轨迹中的耗时；调整 `LLM_TIMEOUT` 或检查索引 |

调试接口：

- `GET /api/meta/agents`：当前身份可用的智能体名称、节点与规则。
- `GET /api/meta/agents/{agent}`：单个智能体配置（不可用时返回 403）。
- `GET /api/logs/runs?agent=qa&limit=20`：最近运行记录与节点轨迹（需 `logs.view`，教师/管理员）。
- `POST /api/agents/{agent}/run`：直接运行；`question`、`profile`、`payload` 三个字段。

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/agents/qa/run \
  -H "Content-Type: application/json" \
  -H "X-User-Role: student" \
  -d '{"question":"2026 年蓝桥杯的报名截止时间和参赛对象是什么？"}'
```

权限验证示例（教师可运行预算智能体，学生返回 403）：

```bash
curl -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/agents/budget/run \
  -H "Content-Type: application/json" -H "X-User-Role: student" -d '{"query":"经费预算"}'
# 403
curl -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/agents/budget/run \
  -H "Content-Type: application/json" -H "X-User-Role: teacher" -d '{"query":"经费预算"}'
# 200
```
