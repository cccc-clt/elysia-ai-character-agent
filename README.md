# 爱莉希雅 · AI 角色陪伴应用 V3

面向游戏角色互动场景的 **AI 角色陪伴应用**（fan-made、non-commercial）。以爱莉希雅为风格化抽象核心，展示多轮对话、长期记忆、SQLite 持久化、可选语音互动、亲密度陪伴系统、角色一致性评估与玩家体验分析。

> 与 miHoYo / HoYoverse **无任何官方关联**。不包含官方立绘/语音素材；生成内容仅供技术演示。

## 项目截图

将截图放入 [`docs/screenshots/`](docs/screenshots/)：

| 文件 | 说明 |
|------|------|
| `chat.png` | 主聊天（立绘/状态卡/气泡） |
| `sidebar.png` | 角色名片与亲密度 |
| `memory.png` | 记忆页 |
| `voice.png` | 语音页 |
| `lab.png` | 实验室 |

## 核心功能

- 爱莉希雅风格陪伴式对话（OpenAI 兼容 API）
- 长期记忆：偏好、称呼、重要事件、情绪、关系变化
- 每 N 轮自动记忆整理；SQLite 持久化（可回退 JSON）
- 亲密度 / 关系阶段 / 心情 / 每日问候
- 可选语音：上传音频转写、回复 TTS 播放（通用音色，非官方配音）
- 角色一致性五维评估 + 历史均值
- 玩家体验分析报告（游戏 AI 产品风格）
- 角色卡 JSON 导入导出
- 工程能力集中在「实验室」标签

### V3 数据库表（在 V2 表基础上追加）

`user_profile` · `pending_memories` · `daily_companion` · `relationship_events` · `message_feedback` · `daily_reflections`

`STORAGE_BACKEND=json` 时：记忆确认、反馈、回忆等部分功能受限（见页面提示）。

## V3 新增（角色陪伴体验）

- **首次引导 / 用户画像**：称呼、陪伴模式偏好、回复风格；写入 `user_profile`，注入 Prompt
- **记忆确认**：自动整理先入 `pending_memories`，用户「记住 / 不记住 / 编辑后记住」再写入正式记忆
- **五种陪伴模式**：日常聊天、情绪安慰、学习陪伴、睡前陪伴、剧情互动（侧边栏切换）
- **每日陪伴**：连续天数、今日问候、今日小纸条（同日不重复生成）
- **我们的回忆**：关系事件时间线、亲密度里程碑、今日回忆生成
- **回复反馈**：喜欢 / 不像她 / 重新生成 / 记住这段；实验室反馈统计

## V2 基础能力

| 模块 | 说明 |
|------|------|
| `database.py` | SQLite 多表持久化 |
| `companionship_service.py` | 亲密度、关系阶段、心情 |
| `voice_service.py` | 可选 STT/TTS |
| `assets/` | 立绘/头像占位 |
| UI | 聊天 / 记忆 / 语音 / 实验室 |

## 技术架构

```
Streamlit UI (ui.py)
    ├── LLMClient (OpenAI-compatible)
    ├── MemoryService → SQLite / JSON
    ├── CompanionshipService → SQLite
    ├── VoiceService (optional)
    ├── Evaluator → SQLite evaluations
    └── Analytics (LLM report)
```

## 项目结构

```
elysia-ai-character-agent/
├── app.py
├── requirements.txt
├── .env.example          # 仅示例，勿提交真实 Key
├── assets/
│   ├── README.md
│   ├── images/           # 本地可选素材
│   └── audio/
├── src/
│   ├── config.py
│   ├── database.py
│   ├── llm_client.py
│   ├── character_profile.py
│   ├── prompt_builder.py
│   ├── memory_service.py
│   ├── companionship_service.py
│   ├── companion_mode.py
│   ├── user_profile_service.py
│   ├── daily_companion_service.py
│   ├── relationship_event_service.py
│   ├── feedback_service.py
│   ├── reflection_service.py
│   ├── voice_service.py
│   ├── evaluator.py
│   ├── analytics_service.py
│   └── ui.py
├── characters/
│   └── elysia_character.json
├── data/
│   ├── elysia_companion.db   # 运行时生成
│   ├── audio_cache/
│   ├── memory_store.json     # JSON 回退
│   └── chat_logs.json
└── docs/screenshots/
```

## 本地运行

```bash
cd elysia-ai-character-agent
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # 编辑 API_KEY
streamlit run app.py
```

无 `API_KEY` 时页面可打开，聊天会提示配置密钥。

## 环境变量

**切勿将 `.env` 提交到 Git。** 使用本地 `.env`、Streamlit Secrets 或 Hugging Face Space Secrets。

| 变量 | 说明 |
|------|------|
| `API_KEY` | 必填（对话/评估/转写） |
| `BASE_URL` | OpenAI 兼容接口 |
| `MODEL_NAME` | 默认模型 |
| `CHAT_MODEL_NAME` / `EVAL_MODEL_NAME` / `SUMMARY_MODEL_NAME` | 分任务模型（可空） |
| `STORAGE_BACKEND` | `sqlite`（默认）或 `json` |
| `DATABASE_PATH` | SQLite 路径 |
| `ENABLE_VOICE` | `true` 开启语音 |
| `TTS_PROVIDER` | `edge` 或 `openai` |
| `STT_PROVIDER` | `openai`（Whisper 兼容） |
| `VOICE_NAME` | edge-tts 音色，如 `zh-CN-XiaoxiaoNeural` |
| `PORTRAIT_PATH` / `BACKGROUND_PATH` / `AVATAR_PATH` | 素材路径 |

完整列表见 [`.env.example`](.env.example)。

## 数据库说明

- 文件：`data/elysia_companion.db`（首次运行自动创建）
- 首次启动若存在旧 JSON，会自动迁移对话与记忆
- `STORAGE_BACKEND=json` 时仅使用 JSON，不写 SQLite
- 实验室页可查看记录数量与亲密度

## 语音功能

1. `.env` 设置 `ENABLE_VOICE=true`
2. **输入**：「语音」页上传 wav/mp3/m4a → Whisper 兼容转写 → 送入聊天
3. **输出**：「朗读最新回复」→ edge-tts 或 OpenAI TTS → `data/audio_cache/` → `st.audio`
4. 未安装 `edge-tts` 时可将 `TTS_PROVIDER=openai`
5. 语音为通用 TTS，**不代表官方角色配音**

## 素材使用

见 [`assets/README.md`](assets/README.md)。将合法获得的图片放入 `assets/images/`；仓库不包含受版权保护的大体积官方素材。

## 部署

### Streamlit Cloud

- Main file: `app.py`
- Secrets 示例：

```toml
API_KEY = "your_key"
BASE_URL = "https://api.openai.com/v1"
MODEL_NAME = "gpt-4o-mini"
STORAGE_BACKEND = "sqlite"
ENABLE_VOICE = "false"
```

### Hugging Face Spaces

- 类型：Streamlit
- 在 Settings → Secrets 配置同上
- 持久化：Space 重启后 SQLite 可能重置，生产建议外接存储

## 简历写法（示例）

> **爱莉希雅 AI 角色陪伴应用 V2** | Python, Streamlit, LLM, SQLite  
> 独立开发 fan-made 角色陪伴 Demo：实现陪伴式 Prompt、多轮对话、SQLite 长期记忆与自动摘要、亲密度/关系阶段系统、可选语音 STT/TTS、角色一致性评估与玩家体验分析；支持 Streamlit Cloud / Hugging Face Spaces 部署。

## 版权与免责声明

- 游戏与角色 IP 归原权利人所有；本项目非官方、非商业
- 请勿上传官方大段台词或未经授权素材
- 生成内容由大模型产生，涉及安全话题时会做脱离角色的安全提示

## Roadmap

- [ ] 多用户 / 多 session 隔离
- [ ] Hugging Face Dataset 备份对话
- [ ] 评估规则 + LLM 混合打分
- [ ] 用户反馈（点赞/点踩）闭环
- [ ] Docker 一键部署

## License

MIT（代码）；游戏相关 IP 归原权利人所有。
