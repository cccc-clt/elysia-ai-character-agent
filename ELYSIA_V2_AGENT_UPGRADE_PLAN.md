# Elysia AI Character Agent V2 改造目标与实施方案

> 目标仓库：`cccc-clt/elysia-ai-character-agent`  
> 参考项目：`Playa-0v0/Cyrene-Agent`  
> 改造原则：**借鉴 Agent 架构，不套壳、不复制角色资源、不照搬 DMAE；保留 Elysia 项目已有优势，在现有 Python + Streamlit + SQLite 架构上做增量升级。**

---

## 0. 当前项目判断

当前 Elysia 已经不是一个最基础的角色聊天 Demo。现有仓库已经具备：

- `PromptBuilder`：角色设定、用户画像、陪伴模式、亲密度上下文注入；
- `MemoryService`：长期记忆、候选记忆、用户确认机制；
- `CompanionshipService`：亲密度、关系阶段与心情；
- `DailyCompanionService`：每日问候与陪伴；
- `VoiceService`：STT / TTS；
- `Evaluator`：角色一致性评测；
- `AnalyticsService`：玩家体验分析；
- SQLite 持久化；
- Streamlit UI。

现阶段最大的缺口不是“陪伴感”，而是：

> **Elysia 能回答，但还不能稳定地“规划 → 调工具 → 获取结果 → 再决策 → 完成任务”。**

因此 V2 的核心不是继续堆 UI、Live2D 或更多角色台词，而是补齐 **Agent Runtime、Tools、Knowledge、Memory Retrieval、Permission / Approval**。

---

# 1. V2 总目标

把项目从：

```text
Character Companion
= Persona + Memory + Voice + UI
```

升级为：

```text
Persona-driven Personal Agent
= Persona
+ Lore RAG
+ Layered Memory
+ Agent Harness
+ Tools / Workflow
+ Permission / Approval
+ Evaluation
```

最终产品定位建议：

> **Elysia — Persona-driven Personal Agent**  
> 一个保留角色人格、长期关系与游戏世界观，同时能够在明确权限边界内调用工具完成任务的角色化个人智能体。

---

# 2. V2 核心产品原则

## 2.1 Chat 与 Work 必须分离

不要让所有对话都进入 Agent Loop。

### Chat Mode

用于：

- 日常聊天；
- 情绪陪伴；
- 剧情互动；
- 角色 Lore 问答；
- 记忆召回。

默认只允许：

- Lore retrieval；
- Memory retrieval；
- 无副作用读取工具。

### Work Mode

用于：

- 搜索与整理资料；
- 生成报告；
- 处理本地/项目文件；
- 调用可扩展工具；
- 执行多步骤任务。

采用：

```text
User Request
→ Plan
→ Tool Call
→ Observation
→ Next Decision
→ Tool Call
→ Final Answer
```

---

## 2.2 人格层与执行层分离

角色人格不能影响执行可靠性。

推荐结构：

```text
用户
 ↓
Intent / Mode Router
 ↓
Agent Runtime
 ↓
Tools / RAG / Memory
 ↓
Raw Result
 ↓
Elysia Persona Renderer
 ↓
最终角色化回复
```

要求：

- 工具参数使用结构化数据；
- 工具内部不能依赖“角色语气”；
- 执行成功/失败必须先以客观状态记录；
- 最后一步才进行角色化表达。

---

## 2.3 权限必须显式设计

V2 不追求“AI 什么都能做”，而追求：

> **AI 在用户授权的 Action Space 中可靠行动。**

建议定义 4 类权限：

| Risk | 例子 | 默认策略 |
|---|---|---|
| `safe` | 计算、读取内存状态 | allow |
| `read` | 读取文件、搜索资料、RAG | allow |
| `write` | 写笔记、修改文件、写数据库 | ask |
| `external` | 发消息、调用外部账号、真实业务动作 | ask / deny |

第一版不要开放 shell、付款、下单、删除文件等高风险能力。

---

# 3. 目标架构

```text
                        ┌──────────────────┐
                        │   Streamlit UI   │
                        └────────┬─────────┘
                                 │
                        ┌────────▼─────────┐
                        │  Mode / Intent   │
                        │     Router       │
                        └────────┬─────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              │                                     │
       ┌──────▼──────┐                       ┌──────▼──────┐
       │  Chat Flow  │                       │  Work Flow  │
       └──────┬──────┘                       └──────┬──────┘
              │                                     │
        Persona Prompt                         ElysiaHarness
              │                                     │
       Lore + Memory                  ┌──────────────┼──────────────┐
              │                       │              │              │
              ▼                       ▼              ▼              ▼
            LLM                    Tools          Memory          Lore RAG
                                                    │              │
                                                    └──────┬───────┘
                                                           │
                                                   Permission Gate
                                                           │
                                                   Observation Log
                                                           │
                                                   Persona Renderer
```

---

# 4. P0：实现 ElysiaHarness

这是本轮改造优先级最高的部分。

新增目录：

```text
src/agent/
├── __init__.py
├── harness.py
├── state.py
├── tool_types.py
├── tool_registry.py
├── tool_executor.py
├── permission.py
├── events.py
└── trace.py
```

## 4.1 `harness.py`

职责：

- 接收用户任务；
- 调用 LLM；
- 解析 tool calls；
- 执行工具；
- 把 observation 写回上下文；
- 再次调用模型；
- 直到模型返回 final answer；
- 设置最大轮数和超时；
- 支持用户取消。

最低可接受 Agent Loop：

```python
while rounds < max_rounds:
    response = llm.chat(messages=messages, tools=tool_specs)

    if not response.tool_calls:
        return response.content

    for call in response.tool_calls:
        result = executor.execute(call)
        messages.append(tool_result_message(call, result))
```

必须补充：

- `max_rounds`；
- tool execution exception handling；
- tool timeout；
- 统一 tool result schema；
- trace；
- approval。

## 4.2 `state.py`

建议状态结构：

```python
@dataclass
class AgentState:
    run_id: str
    mode: str
    status: str
    current_step: str | None
    completed_steps: list[str]
    pending_approval: dict | None
    tool_history: list[dict]
```

不要一开始实现复杂 planner。

第一版只需要让模型根据历史和 observation 自己决定下一步。

---

# 5. P0：Tool Registry + Tool Result 标准化

新增：

```text
src/tools/
├── __init__.py
├── base.py
├── registry.py
├── lore_search.py
├── memory_search.py
├── web_search.py
├── read_text_file.py
├── write_note.py
└── generate_report.py
```

## 5.1 Tool Definition

统一 schema：

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict
    risk: Literal["safe", "read", "write", "external"]
    handler: Callable
```

## 5.2 Tool Result

所有工具必须返回：

```json
{
  "ok": true,
  "tool": "lore_search",
  "summary": "找到 4 条相关设定",
  "data": {},
  "error": null,
  "evidence": []
}
```

禁止工具直接返回一大段不可解析字符串。

---

# 6. P0：第一批只做 6 个工具

不要一开始追求 20 个工具。

## Tool 1 — `lore_search`

用途：搜索角色 / 世界观知识库。

风险：`read`

输入：

```json
{
  "query": "爱莉希雅和逐火十三英桀的关系",
  "top_k": 5
}
```

输出需要包含：

- chunk；
- source；
- score；
- title。

---

## Tool 2 — `memory_search`

用途：主动检索与当前问题有关的长期记忆。

风险：`safe`

不要把全部长期记忆直接塞进 Prompt。

---

## Tool 3 — `web_search`

用途：Work Mode 搜索公开资料。

风险：`read`

第一版可以做 Provider 抽象：

```python
SearchProvider
├── TavilyProvider
├── SerperProvider
└── MockProvider
```

没有 Key 时 UI 明确提示，不允许假装联网成功。

---

## Tool 4 — `read_text_file`

用途：读取用户明确授权目录中的 `.md/.txt/.json/.csv`。

风险：`read`

必须限制：

- allowed root；
- 最大文件大小；
- 禁止路径穿越；
- 禁止读取 `.env`、密钥文件。

---

## Tool 5 — `write_note`

用途：把 Agent 结果写入应用内笔记 / SQLite。

风险：`write`

执行前弹出 Approval Card。

---

## Tool 6 — `generate_report`

用途：把本轮研究结果整理为 Markdown 报告。

风险：`write`

默认只保存到：

```text
data/exports/
```

---

# 7. P0：Approval / Permission Gate

新增：

```text
src/agent/permission.py
src/ui_components/approval.py
```

策略：

```python
POLICY = {
    "safe": "allow",
    "read": "allow",
    "write": "ask",
    "external": "ask",
}
```

Approval Card 至少展示：

```text
Elysia 想执行：写入笔记

内容：将当前研究结论保存到 notes
目标：data/notes/agent-note-xxx.md
风险：会修改本地数据

[允许一次] [本次会话允许] [拒绝]
```

必须做到：

- 用户拒绝后 Tool 不执行；
- Agent 收到 `denied` observation；
- Agent 能继续给出不执行外部动作的替代方案。

---

# 8. P1：Lore RAG

当前项目需要从“角色卡 Prompt”升级到“可检索 Lore Knowledge”。

新增：

```text
src/rag/
├── __init__.py
├── document.py
├── chunker.py
├── indexer.py
├── retriever.py
├── reranker.py
└── citations.py

knowledge/
├── README.md
├── official/
├── curated/
└── index/
```

## 8.1 数据来源要求

每条知识必须记录：

```json
{
  "source_id": "...",
  "title": "...",
  "source_url": "...",
  "source_type": "official|curated",
  "retrieved_at": "...",
  "license_note": "..."
}
```

不要直接把未知来源的 Wiki / 社区内容当“官方设定”。

## 8.2 检索策略

MVP：

```text
Query
→ BM25 / keyword retrieval
→ optional embeddings
→ merge
→ top_k
→ optional rerank
→ prompt context
```

不要为了模仿 Cyrene 强行加入大型本地 embedding 模型。

优先保证：

1. 可以部署；
2. 来源可追溯；
3. 不相关时不注入；
4. 回答可以显示来源。

---

# 9. P1：把现有 MemoryService 升级成 L0 / L1 / L2

不要推翻现有记忆确认机制。

在当前 `MemoryService` 基础上升级。

## L0 — Session Memory

最近 N 轮对话：

```text
L0 = current session context
```

特点：

- 临时；
- 不长期保存或只作为聊天日志；
- 直接进入最近上下文。

## L1 — User Facts

已确认事实：

- 称呼；
- 偏好；
- 长期目标；
- 稳定习惯。

用户确认后才成为长期事实。

## L2 — Episodic / Relationship Memory

记录：

- 重要共同经历；
- 关系事件；
- 有持续价值的对话摘要；
- 重要情绪事件。

建议字段：

```text
importance
last_accessed_at
access_count
status
embedding / keywords
```

不照搬 DMAE。

先做一个容易解释、适合产品展示的激活评分：

```text
memory_score
= relevance * 0.50
+ importance * 0.30
+ recency * 0.20
```

最终只召回 Top-K。

这样面试时可以直接解释：

> 我没有无限扩张上下文，而是设计了“相关性 + 重要性 + 时效性”的记忆进入策略。

---

# 10. P1：Prompt Layer 重构

当前 `PromptBuilder` 不删除，而是拆成明确的 Prompt Layers。

目标：

```text
System
├── Safety / Identity
├── Persona Soul
├── Mode Instruction
├── User Profile
├── Relevant Memory
├── Relevant Lore
├── Tool Policy
└── Runtime Context
```

新增：

```text
src/prompt/
├── persona.py
├── layers.py
├── runtime_context.py
└── renderer.py
```

关键原则：

**稳定层和动态层分开。**

稳定：

- Persona；
- Safety；
- Tool Policy。

动态：

- memory；
- lore；
- 当前任务；
- tool observations。

---

# 11. P1：Agent Trace / 可观察性

这是作品集非常重要的一层。

新增数据库表：

```text
agent_runs
agent_steps
agent_tool_calls
agent_approvals
```

每次运行记录：

```text
run_id
user_request
mode
round
model
selected_tool
arguments
risk
approval_status
result_status
latency_ms
error
```

UI 增加：

```text
实验室 → Agent Trace
```

展示类似：

```text
Round 1
理解任务 → lore_search

Round 2
读取 4 条 Lore → web_search

Round 3
整理结果 → generate_report

Approval
用户允许保存报告

Done
```

这会显著提高项目的 Agent 产品完整度。

---

# 12. P1：Agent Evaluation

保留现有角色一致性 Evaluator，再新增 Agent 评测。

推荐指标：

| 指标 | 含义 |
|---|---|
| Task Success | 任务是否完成 |
| Tool Selection Accuracy | 是否选择正确工具 |
| Tool Argument Validity | 参数是否合法 |
| Groundedness | 是否基于 Lore / Tool Evidence |
| Persona Consistency | 执行任务后是否仍保持角色感 |
| Permission Compliance | 是否越权 |
| Recovery Rate | 工具失败后是否能恢复 |
| Avg Tool Calls | 平均工具调用次数 |
| Latency | 完整任务耗时 |

新增测试集：

```text
tests/eval_cases/
├── chat_cases.json
├── lore_cases.json
├── tool_cases.json
└── permission_cases.json
```

至少准备 20 个案例，而不是只展示 2-3 次成功截图。

---

# 13. P2：MCP，但不要第一阶段就做

等 Tool Registry 与 Approval 稳定后再接 MCP。

新增：

```text
src/mcp/
├── client.py
├── config.py
└── adapter.py
```

MCP Tool 必须转成统一 ToolDefinition：

```text
MCP Tool
→ Adapter
→ Tool Registry
→ Permission Gate
→ ElysiaHarness
```

不能让 MCP 绕过权限系统。

---

# 14. P2：主动 Agent

主动聊天不是第一优先级。

等基本 Agent 稳定后，可以增加：

```text
Proactive Trigger
├── time
├── inactivity
├── unfinished task
├── important memory date
└── user-defined reminder
```

必须有“不打扰策略”：

- quiet hours；
- 每日主动消息上限；
- 用户关闭主动模式；
- 同类消息冷却时间。

---

# 15. 暂时不要做的东西

第一轮改造明确不做：

- 不做 Live2D；
- 不做 13 个角色 Multi-Agent；
- 不做 QQ / 微信机器人；
- 不做手机控制；
- 不做闲鱼自动化；
- 不开放任意 Shell；
- 不复制 Cyrene 的 DMAE；
- 不重新训练大模型；
- 不大规模重写现有 Streamlit UI。

原因：这些都会扩大项目范围，但不能解决当前最核心的 Agent 能力缺口。

---

# 16. 推荐实施顺序

## Phase 1 — Agent Core（必须先完成）

- [ ] 新建 `src/agent/`
- [ ] 实现 `ElysiaHarness`
- [ ] Tool Registry
- [ ] Tool Result Schema
- [ ] Agent Trace
- [ ] 最大轮次 / timeout / error handling

**验收：**

用户输入一个需要 2 个工具的任务，Agent 能连续：

```text
Tool A → Observation → Tool B → Final Answer
```

---

## Phase 2 — Permission + Tools

- [ ] Permission Policy
- [ ] Approval Card
- [ ] `lore_search`
- [ ] `memory_search`
- [ ] `web_search`
- [ ] `read_text_file`
- [ ] `write_note`
- [ ] `generate_report`

**验收：**

- 读取类工具无需确认；
- 写入类工具必须确认；
- 拒绝后不会执行；
- Trace 中可查看完整过程。

---

## Phase 3 — Lore RAG

- [ ] knowledge 数据规范
- [ ] chunker
- [ ] indexer
- [ ] retriever
- [ ] source citation
- [ ] UI 中显示来源

**验收：**

给出 10 个角色设定问题：

- 能召回对应证据；
- 无证据时明确“不确定”；
- 不把用户私人记忆误当 Lore。

---

## Phase 4 — Memory V2

- [ ] L0 / L1 / L2 分层
- [ ] relevance / importance / recency score
- [ ] Top-K retrieval
- [ ] 记忆确认继续保留
- [ ] 用户可以查看 / 删除 / Pin 记忆

**验收：**

在 50+ 条长期记忆存在时，不全量注入 Prompt，只召回与当前问题有关的 Top-K。

---

## Phase 5 — Agent Evaluation

- [ ] 20+ eval cases
- [ ] Tool selection
- [ ] Task success
- [ ] Groundedness
- [ ] Permission compliance
- [ ] Persona consistency

**验收：**

实验室可以输出一次完整评测报告，而不仅是人工观察。

---

## Phase 6 — MCP / External Integrations

完成前五阶段后再决定是否加入：

- MCP；
- GitHub；
- Calendar；
- Reminder；
- Email；
- Browser automation。

---

# 17. 建议最终目录

```text
elysia-ai-character-agent/
├── app.py
├── characters/
├── knowledge/
│   ├── official/
│   ├── curated/
│   └── index/
├── src/
│   ├── agent/
│   │   ├── harness.py
│   │   ├── state.py
│   │   ├── events.py
│   │   ├── permission.py
│   │   └── trace.py
│   ├── tools/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── lore_search.py
│   │   ├── memory_search.py
│   │   ├── web_search.py
│   │   ├── read_text_file.py
│   │   ├── write_note.py
│   │   └── generate_report.py
│   ├── rag/
│   │   ├── document.py
│   │   ├── chunker.py
│   │   ├── indexer.py
│   │   ├── retriever.py
│   │   └── citations.py
│   ├── prompt/
│   │   ├── persona.py
│   │   ├── layers.py
│   │   └── renderer.py
│   ├── mcp/                    # P2
│   ├── memory_service.py       # 保留并升级
│   ├── companionship_service.py
│   ├── llm_client.py           # 扩展 tool calling
│   ├── evaluator.py
│   ├── analytics_service.py
│   └── ui.py
├── tests/
│   ├── agent/
│   ├── tools/
│   ├── rag/
│   └── eval_cases/
└── data/
    ├── exports/
    └── ...
```

---

# 18. 现有文件修改重点

## `src/llm_client.py`

目标：从“只生成文本”升级为：

```text
chat(messages, tools=None)
→ content
→ tool_calls
→ usage
```

不能把 Function Calling 逻辑写死在 UI。

---

## `src/prompt_builder.py`

目标：逐步迁移到 Prompt Layers。

保留兼容接口，避免一次性重构导致整个应用不可运行。

---

## `src/memory_service.py`

目标：

- 保留候选记忆确认；
- 增加分层；
- 增加 relevance retrieval；
- 增加访问时间和重要度；
- 禁止所有记忆无条件进入 Prompt。

---

## `src/database.py`

新增表建议：

```text
agent_runs
agent_steps
agent_tool_calls
agent_approvals
lore_sources
lore_chunks
```

数据库迁移要向后兼容。

---

## `src/ui.py`

不要重做视觉。

只新增：

1. Chat / Work 模式入口；
2. Tool Calling 状态；
3. Approval Card；
4. Agent Trace；
5. Lore 来源显示。

---

# 19. Codex 执行规则

把本文件交给 Codex 后，要求它遵守：

1. **先读现有仓库和 `AGENTS.md`，不要凭空重构。**
2. 每个 Phase 单独实施，不一次性完成 V2。
3. Phase 开始前先输出：
   - 现有实现；
   - 要修改的文件；
   - 新增文件；
   - 风险；
   - 测试方案。
4. 不删除现有可用的陪伴、语音、评估、记忆功能。
5. 新 Agent 能力必须兼容当前 Streamlit 启动方式。
6. 所有 Tool 必须经过 Registry。
7. 所有写操作必须经过 Permission Gate。
8. 所有 Tool Result 必须结构化。
9. 不在代码里写死 API Key。
10. 每个 Phase 完成后运行测试，并列出：
    - 修改文件；
    - 新增测试；
    - 测试结果；
    - 未完成项；
    - 下一阶段建议。
11. 不复制 Cyrene-Agent 源码；只参考产品/架构思想。
12. 如果某一功能会显著增加部署体积或破坏 Streamlit Cloud / Hugging Face Spaces 兼容性，先提供轻量方案再实现。

---

# 20. 第一轮 Codex 任务

第一轮只做 **Phase 1：Agent Core**。

任务目标：

> 在不破坏当前 Character Chat 的情况下，为 Elysia 新增一个最小可运行 `ElysiaHarness`，支持 OpenAI-compatible Function Calling、Tool Registry、连续两轮以上 Tool Loop、统一 Tool Result、最大轮次、超时、错误处理和 Trace；暂不加入外部写操作、MCP、RAG 重构和 UI 大改。

第一轮必须至少提供两个测试工具：

```text
get_current_companion_state
search_memory
```

测试任务：

```text
“回忆一下我最近提到的重要事情，并结合当前关系状态给我一个总结。”
```

期望链路：

```text
User
→ ElysiaHarness
→ search_memory
→ observation
→ get_current_companion_state
→ observation
→ LLM
→ persona-style final answer
```

验收标准：

- [ ] 至少连续调用 2 个 Tool；
- [ ] Tool 参数和返回值结构化；
- [ ] Agent Loop 最多执行配置的 N 轮；
- [ ] Tool 异常不会使整个 Streamlit 崩溃；
- [ ] Trace 可以记录每轮 Tool；
- [ ] 普通 Chat Mode 仍按原逻辑工作；
- [ ] 新增单元测试；
- [ ] README 暂只补一句“V2 Agent Core experimental”，不要重写整个 README。

---

# 21. 成功后的作品集叙事

完成 V2 后，项目介绍不要只写：

> 做了一个爱莉希雅聊天机器人。

而应描述为：

> 设计并实现人格化 Personal Agent：在角色 Persona、长期关系记忆与 Lore RAG 的基础上，引入多轮 Agent Harness、结构化 Tool Calling、权限审批和任务执行 Trace，使角色从“生成回复”升级为“在明确授权边界内完成任务”；同时建立角色一致性、工具选择、任务成功率与权限合规的 Agent 评测体系。

这才是 V2 最核心的项目价值。
