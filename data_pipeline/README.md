# 崩坏 3 设定知识采集管线

这是一套与聊天应用解耦的、低频率、可断点续跑的数据准备工具。第一阶段只处理爱莉希雅、逐火十三英桀、逐火之蛾、前文明、往世乐土、直接相关律者概念，以及链接文本明确指向相关剧情角色的公开官方页面。

当前状态：**Implemented（管线）**；官方页面的可访问性和实际正文产出需要在每次采集时重新验证。仓库当前没有 Chroma、FAISS 或其他向量索引，因此 `build-rag` 生成可导入的 JSONL/Markdown，不会自动修改或覆盖任何线上/本地索引。

## 数据来源与边界

- `https://www.bh3.com/valkyries`
- `https://baike.mihoyo.com/bh3/wiki/channel/map/17/59`
- 从上述栏目正常发现且属于白名单路径的官方详情页。
- `https://comic.bh3.com/book` 仅支持作品名、章节名、简介和原页面链接；不会请求、保存或 OCR 漫画图片。
- 不登录、不使用 Cookie/Token、不枚举数字 ID、不调用认证接口、不采集玩家帖子。
- 不下载图片、音频、视频或漫画页面；Playwright 会主动拦截图片、媒体和字体请求。
- 403、429 或验证码会立即熔断对应域名；robots.txt 禁止的 URL 会记录为 `robots_disallowed`。

来源分层和采集策略登记在 `data/config/source_registry.yaml`：Tier A 官方网页可以在质量门通过后进入主 RAG；Tier A-manual 游戏内官方资料必须由人工填写来源说明并审核；BH3Text 固定为 `Tier B-primary-transcript` 并进入独立剧情文本空间，不能伪装成官方网页、覆盖 Tier A 或生成 confirmed 关系。种子文件位于 `data/seeds/elysia_official_urls.txt`。URL 发现还必须匹配范围关键词，避免从栏目页扩散为全站爬取。

## 安装

```bash
pip install -r requirements.txt
```

动态页面兜底还需要安装 Chromium；普通静态页面不会启动浏览器：

```bash
python -m playwright install chromium
```

如果不安装浏览器，可用 `--no-render`；正文不足 200 个有效字符的页面会明确失败，不会把 `Loading` 当成正文。

## 候选审计与评分

正式采集前必须先审计 manifest 已发现的候选 URL。审计命令只读取已存在 raw 正文，并以遵守 robots、白名单、并发 1 和限速的公开页面请求补齐其余标题/正文摘要；不调用付费 LLM：

```bash
python -m data_pipeline.cli audit-candidates --scope elysia --delay 3
```

默认评分由 `data_pipeline/config.py` 的 `RelevanceScoringConfig` 控制，可修改关键词、权重和纳入阈值。当前规则是：

- 标题包含“爱莉希雅”：+10；
- 标题包含“逐火十三英桀、往世乐土、前文明、逐火之蛾”：+8；
- 标题包含任一核心角色姓名：+6；
- 正文摘要包含至少两个核心关键词：+4；
- 页面有剧情、档案、角色/组织设定信号：+4；
- 配装、武器、圣痕、补给、数值或战斗攻略：-8；
- 栏目导航页：-10；
- 有效中文正文少于 200 字：-10。

达到分数阈值仍不代表必然纳入：栏目页、正文不足、玩法/数值页、元数据失败，以及标题和摘要没有直接范围匹配的页面会被强制排除。“怪物信息”“材料描述”等结构化类型信号优先判定为玩法页；分类和摘要关键词只查看正文开头 1200 字符，避免 Wiki 页尾推荐污染判断；“华、樱、苏”等单字姓名只有作为标题中的独立词时才计分，避免误中“华彩、绯樱、复苏”。`--refresh` 会重新访问没有 raw 正文的候选；默认复用已有审计结果，方便安全断点续跑。正式 `crawl` 检测到审计 JSONL 后，只把 `decision=include` 的 URL 按 `crawl_priority` 加入队列，不再从页面继续扩张未经审计的 URL。

## 命令

```bash
python -m data_pipeline.cli discover --scope elysia --sources official-characters,official-news,official-wiki,official-comics --max-candidates 150
python -m data_pipeline.cli crawl --scope elysia --max-pages 5 --dry-run
python -m data_pipeline.cli audit-candidates --scope elysia --delay 3
python -m data_pipeline.cli crawl --scope elysia --max-pages 50 --delay 3 --concurrency 1 --accepted-candidates-only
python -m data_pipeline.cli normalize
python -m data_pipeline.cli extract-relations
python -m data_pipeline.cli import-manual --input data/manual_official/inbox
python -m data_pipeline.cli review-manual
python -m data_pipeline.cli build-rag
python -m data_pipeline.cli build-coverage
python -m data_pipeline.cli build-source-inventory
python -m data_pipeline.cli inspect-videos --seed-file data/video_sources/bilibili_seeds.txt
python -m data_pipeline.cli process-video-subtitles
python -m data_pipeline.cli build-video-review
python -m data_pipeline.cli discover-bh3text --scope elysia --max-candidates 300
python -m data_pipeline.cli crawl-bh3text --scope elysia --max-pages 10 --delay 3 --concurrency 1 --accepted-candidates-only
python -m data_pipeline.cli crawl-bh3text --scope elysia --mode coverage-gap --max-new-pages 40 --delay 3 --concurrency 1
python -m data_pipeline.cli build-bh3text
python -m data_pipeline.cli discover-bh3helper --scope elysia --max-pages 5
python -m data_pipeline.cli discover-bh3helper --scope elysia --max-pages 30
python -m data_pipeline.cli map-duplicate-sources
python -m data_pipeline.cli build-story-navigation
python -m data_pipeline.cli quality-report
python -m data_pipeline.cli status
```

采集器刻意只允许 `--concurrency 1`。`--max-pages` 是同一 manifest 内唯一 URL 的总上限；失败记录可在原槽位重试，不会让断点续跑突破该上限。成功、重复和 robots 禁止记录会从 manifest 恢复，不重复请求或写入。

## 数据目录

| 路径 | 用途 |
|---|---|
| `data/raw/official_pages.jsonl` | 本地采集的页面文档 |
| `data/cleaned/official_pages.jsonl` | 清洗、哈希去重后的页面文档 |
| `data/entities/entities_pending.jsonl` | 待审核实体候选 |
| `data/relations/relations_pending.jsonl` | 规则/可选 LLM 生成的待审核关系 |
| `data/relations/relations_confirmed.jsonl` | 只允许人工确认后写入 |
| `data/chunks/elysia_lore_chunks.jsonl` | 500～900 字符为目标的 RAG chunks |
| `data/chunks/elysia_lore_markdown/` | 同内容的 Markdown 版本 |
| `data/manifests/crawl_manifest.json` | URL、断点、状态与失败原因 |
| `data/manifests/elysia_candidate_audit.jsonl` | 候选 URL 评分、决定和原因 |
| `data/manifests/elysia_candidate_audit.md` | 便于人工检查的候选排名表 |
| `data/manifests/data_quality_report.md` | 采集、正文、chunk、实体和关系质量汇总 |
| `data/manifests/lore_coverage_matrix.json` | 27 个核心主题的文档、chunk、关系与覆盖状态 |
| `data/manifests/manual_source_gap.md` | 公开官方网页不足时的游戏内人工补录清单 |
| `data/manifests/source_inventory.json` | 四类隔离语料的来源层级、数量与开发原型结构门 |
| `data/manifests/deduplication_report.md` | 不含正文的hash去重、BH3Helper映射与结构验证报告 |
| `data/manual_official/templates/` | 游戏内官方资料人工录入模板 |
| `data/review/` | 实体、关系和人工资料审核工作台 |
| `data/review/relation_conflicts.md` | official/BH3Text pending语义关系的冲突清单；证据边不参与 |
| `data/video_sources/` | B 站待审元数据、字幕和独立视频审核空间 |
| `data/manifests/bh3text_candidate_audit.jsonl` | BH3Text 限定目录发现的候选详情页审计 |
| `data/cleaned/bh3text_dialogues.jsonl` | 本地解析的对话轮次；不提交 Git |
| `data/chunks/bh3text_lore_chunks.jsonl` | 与主 RAG 分离的剧情文本 chunks；不提交 Git |
| `data/relations/dialogue_evidence_edges.jsonl` | `SPEAKS_TO/SPEAKS_ABOUT/APPEARS_WITH` 文本证据边 |
| `data/relations/bh3text_relations_pending.jsonl` | 仅限明确台词的待审核设定关系，永不自动 confirmed |
| `data/review/bh3text_transcript_verification.md` | 默认 `not_checked` 的视频人工抽样核验清单 |
| `data/review/bh3text_transcript_verification.jsonl` | 2/1/1/2/2/2 固定章节分布的机器可读核验样本 |
| `data/manifests/bh3text_group_coverage_before.json` | coverage-gap 补采前分组配额快照 |
| `data/manifests/bh3text_group_coverage_after.json` | coverage-gap 补采后分组配额快照 |
| `data/manifests/vector_readiness.json` | 独立剧情向量索引的人工核验与数据质量门；本阶段不建索引 |
| `data/story_guide/bh3helper_navigation.jsonl` | BH3Helper 社区剧情导航元数据；本地生成 |
| `data/story_guide/bh3helper_official_links.jsonl` | 官方物料候选外链；始终先标记 `unverified` |
| `data/story_guide/bh3helper_archive_candidates.jsonl` | 游戏档案/追忆等待人工核验入口 |
| `data/story_guide/bh3helper_annotations.jsonl` | 社区作者注释，不能作为官方事实 |
| `data/story_guide/bh3helper_duplicate_map.jsonl` | 与 BH3Text 的可能重复映射，不复制正文 |
| `data/story_guide/source_link_graph.jsonl` | 来源导航关系图，与角色关系文件隔离 |
| `data/story_guide/story_navigation_chunks.jsonl` | 仅含短导航元数据的独立索引 |
| `data/logs/data_pipeline.log` | 不含密钥/Cookie 的运行日志 |

除种子文件和 `.gitkeep` 外，这些运行产物已加入 `.gitignore`，避免公开仓库重新发布大段官方正文。

栏目入口可保留在 raw 和 manifest 中用于链接发现。`normalize` 会为可解析 raw 文档记录 `accepted`、`needs_review` 或 `rejected` 及明确原因，保留审计轨迹；只有 `accepted` 文档会生成 RAG chunks、实体候选和关系候选。清洗会在 Wiki 的公开“词条内容由…编辑团队原创”/“建议与反馈”分隔符处截断评论和全站目录，删除导航提示和重复菜单；`duplicate_paragraph_count` 记录已删除的重复行，而不是把已经成功删除的菜单重新视作残留正文。导航页、有效中文少于 200 字、重复正文副本、纯玩法/数值页和范围外页面不会进入 RAG。

## 人工官方资料与覆盖矩阵

人工记录必须填写 `summary`、`evidence` 和 `source_note`。`import-manual` 只校验并登记 `pending`，不会补写字段、移动文件或确认资料；只有人工将状态改为 `accepted` 并移动到 `data/manual_official/accepted/` 的记录才会进入 `build-rag`，其 `source_type=official_game_manual`、`source_tier=A-manual`，不会与网页来源错误合并。

`build-coverage` 生成 JSON/Markdown 覆盖矩阵、实体/关系审核工作台；最低目标未满足时还会生成 `manual_source_gap.md`。每个主题分别显示 `official_coverage`、`bh3text_transcript_coverage` 和 `combined_coverage`。BH3Text 可以增加转录层及组合层的 direct/substantial evidence 和独立文档数，但不能增加独立官方文档、Tier A 文档或 confirmed 关系；视频元数据与 pending 关系同样不计入正式覆盖。

`build-source-inventory` 只输出来源数量、层级、hash去重组和结构质量门，不复制剧情正文。它分别统计 `official_lore`、`bh3text_dialogue`、`story_navigation` 与视频证据，验证社区资料没有计入官方文档，并记录 `prototype_only=true`、`contains_unverified_transcripts=true`、`production_enabled=false`。结构门通过不等于人工转录核验通过。

## BH3Text 剧情文本边界

BH3Text（`https://www.bh3text.com/dialog/`）不是米哈游官方网站。该站声明其内容是从网络收集的《崩坏3》游戏文本存档，版权归米哈游所有。管线只从公开目录正常发现“在无限的阴影之中”“致世界上的另一个我”“愿时光永驻此刻，愿明日——”以及主线第29—31章的详情链接，不构造编号、不遍历其他章节、不采集图片或联系方式。运行前检查 robots、公开访问与站点说明；遇到明确 robots 禁止、403、412、429 或验证码即停止，不绕过。

正文按页面中的显式说话者、台词、旁白和原顺序解析；未标明的说话者不会根据上下文猜测。完整 raw/cleaned 正文与 chunks 只保存在 `.gitignore` 覆盖的本地运行目录。它们只用于个人研究、检索和角色 Agent 实验，不在 GitHub 重新发布完整剧情文本，也不用于整章或整场复现。Agent 后续若接入独立索引，只应返回必要摘要与短证据，同时显示原页面 URL 和来源等级；本阶段尚未接入任何正式向量库。若站点要求删除或停止采集，应停止命令并按下方清理范围删除本地数据。

`coverage-gap` 按 `data/config/bh3text_collection_groups.yaml` 的章节目标上限工作：读取现有 manifest 和成功文档，跳过已满足分组及已成功 URL，优先补主线31章，再按缺口补往世乐土第三阶段、主线29和30章；卡牌、宝箱、纯探索、操作教学和无剧情系统提示不会为了凑配额而采集。单次最多新增40个唯一页面。

### BH3Text 人工核验标准

- `match`：场景标题一致或明确对应，说话者一致，抽样3～5轮台词内容一致且没有关键台词缺失；允许标点、空格和个别异体字差异。
- `minor_mismatch`：少量标点、个别错字或不影响含义的格式差异。
- `critical_mismatch`：说话者错误、台词被改写、大段缺失、不同场景混合，或身份、关系、事件含义发生变化。
- `not_checked`：尚未人工查看视频或游戏原文。程序只生成待核验样本，绝不自行将其改成 `match`。

`vector_readiness.json` 还要求至少10个已审核场景、至少8个 `match`、0个 critical mismatch、主线31章至少8个文档、至少120个BH3Text chunks、所有chunk有原始URL且fixture命中为0。即使数据数量达标，人工核验未完成时 `vector_ready` 仍必须为 `false`。

## BH3Helper 剧情导航边界

BH3Helper（`https://bh3helper.xrysnow.xyz/`）是个人制作的社区剧情辅助工具，不是米哈游官方网站。它仅作为观看顺序、档案入口与官方物料候选的发现/编排层：先用 httpx 读取公开 HTML，元数据不足时才用 Playwright 渲染；只跟随首页公开链接，不扫描连续 ID。嵌入式对话正文在解析前删除，不进入主 lore RAG 或 BH3Text corpus；作者注释明确标为社区注释，官方候选外链保持 `unverified`，直到目标域名或账号身份经过独立核验。

## B 站视频审计与字幕

`inspect-videos` 对每个 seed 只请求公开页面元数据，不使用 Cookie、登录或受保护接口，不抓评论、弹幕和用户主页，不下载视频/音频。403、412、429、验证码或登录要求会记录为 `metadata_access_blocked`，不重试绕过。只有 UID 已在 `data/config/bilibili_official_accounts.yaml` 中以人工证据登记的上传者才能分类为 `official_video / A`；标题包含“官方”等词不能证明官方身份。

公开视频字幕或用户自行提供的 SRT/VTT/TXT/Markdown 只会生成 `data/video_sources/chunks/video_chunks.jsonl` 中的 pending 视频块。它与主 `elysia_lore_chunks.jsonl` 完全分离；Tier C 分析/推测不生成视频块，任何玩家视频都不会自动写入 confirmed 实体或关系。无公开字幕不是失败，管线会生成 `manual_inbox/BV号.yaml` 供人工填写时间段和证据类型。完整原始/清洗字幕、视频块、元数据与运行审计均已加入 `.gitignore`。

## 关系审核

自动抽取只写 `relations_pending.jsonl`，并要求 `evidence` 逐字来自同一官方页面。审核者应同时打开 `source_url`，检查角色身份、时代、世界、本体/记忆体/同位体与剧情阶段。确认后才可把该行复制到 `relations_confirmed.jsonl` 并将 `review_status` 改为 `confirmed`；拒绝项不应进入确认文件。

默认使用严格的规则抽取。可选 LLM 模式复用应用现有 `API_KEY`、`BASE_URL` 和 `SUMMARY_MODEL_NAME`，模型失败不会影响此前完成的采集和清洗：

```bash
python -m data_pipeline.cli extract-relations --use-llm
```

提示词版本为 `elysia-official-lore-relations-v1`，要求只使用输入文本、逐字证据、无法确认时不输出；输出还会经过 Pydantic 和证据子串校验。不要把模型候选视作官方事实。

## RAG 导入

`elysia_lore_chunks.jsonl` 每行包含 `chunk_id`、`content` 和 metadata（标题、来源链接、来源类型、实体名、时代、世界、采集时间、文档 ID）。当前应用尚无向量库导入层；接入任意向量库时应创建新的 collection/index，以 `chunk_id` 做幂等 upsert，并保留 `source_url` 供回答引用。不要在未备份和未确认的情况下覆盖已有索引。

## 删除本地采集数据

停止正在运行的采集命令后，只删除以下专用子目录中的运行产物，保留 `.gitkeep` 与 `data/seeds/`：

- `data/raw/`
- `data/cleaned/`
- `data/chunks/`
- `data/entities/`
- `data/relations/`
- `data/manifests/`
- `data/logs/`

这些数据与 `data/elysia_companion.db`、聊天历史和用户记忆无关；不要删除整个 `data/` 目录。

## 版权与使用限制

原始资料只用于个人研究、检索和角色 Agent 实验。应用回答设定问题时应提供原页面链接和来源等级，只返回必要摘要与短证据，不提供整章、整场剧情文本复现。不得公开重新发布大段官方正文、BH3Text 完整剧情文本、漫画图片或其他受版权保护内容。

This project is a fan-made, non-commercial technical demonstration.
It is not officially affiliated with miHoYo, HoYoverse, or any other game company.
The repository does not provide official artwork, official voice recordings, or proprietary game assets.
