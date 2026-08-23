# Elysia V2 Autonomous Preflight Report

- 执行日期：2026-08-22（Asia/Shanghai）
- 分支：`codex/v1.1-stabilization`
- 基线提交：`17e92e8 fix: enforce memory lifecycle and prompt source isolation`
- Python：3.11.9

## Baseline verification

| Check | Result |
|---|---|
| `python -m pytest -q` | 101 passed in 14.44s |
| `python -m compileall app.py src data_pipeline` | passed |
| `git diff --check` | passed；仅报告 LF/CRLF 工作区提示 |

## Repository facts

- 依赖由根目录 `requirements.txt` 管理；没有 `pyproject.toml`、`setup.cfg` 或 `tox.ini`。
- 应用模型层为 `src/llm_client.py` 的 OpenAI-compatible Chat Completions 客户端；没有 QuickRouter 专用实现。
- 当前没有 Qdrant、FAISS、Chroma、pgvector、embedding 或 BM25 依赖与索引。
- 持久化为 SQLite/JSON fallback；README 仅说明 Streamlit Cloud 与 Hugging Face Spaces，且明确 SQLite 在实例回收后可能丢失。
- Lore 管线与应用的 `MemoryService` 物理隔离；预检时尚未接入应用 Agent 或向量库。
- `.gitignore` 已排除 raw/cleaned 正文、chunks、字幕、审核运行产物、日志、数据库、音频和未来本地索引所需运行目录。
- 未读取 `.env`，未发现候选提交文件包含 API Key、Cookie、Token 或授权头。

## Current data snapshot

| Layer | Snapshot |
|---|---|
| Tier A official | 3 accepted documents / 16 chunks / 3 usable topics |
| BH3Text | 138 documents / 5,597 turns / 201 chunks / 2,060 evidence edges / 0 pending semantic relations |
| BH3Helper | 6 navigation records / 26 official-link candidates / 11 archive candidates / 40 annotations / 65 source-link edges |
| Bilibili | 4 metadata audits / 0 verified transcripts |

BH3Text 章节分布为 65 / 23 / 15 / 10 / 10 / 15。10 个核验样本仍全部为 `not_checked`，因此 `vector_ready=false`。

## Working tree assessment

预检时工作树包含前四阶段 Lore 采集、BH3Text、BH3Helper、视频审计、覆盖校准、测试、配置和说明文档的未提交改动。没有观察到与本自治任务无关的用户代码修改；运行正文、字幕、chunks、日志和审核输出均被 Git 忽略。以上改动可以在全量测试与秘密扫描通过后作为本地检查点提交。

## Upgrade-plan status

- 主升级计划中的 Agent Core、Tool Registry、Approval UI、Memory V2 与 MCP 尚未实现。
- 自治计划 B（章节均衡补采）已实现并实际补采。
- 自治计划 C（均衡核验包）已生成；人工判断保持阻塞。
- 自治计划 D 仅部分实现；缺少统一 source inventory 与 deduplication report。
- 自治计划 E–K 尚待本次自治执行继续完成。

