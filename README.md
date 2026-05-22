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
- 可选语音：录音/上传 → STT → 聊天 → TTS 播放，支持 GPT-SoVITS / edge-tts / OpenAI TTS
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
| `voice_service.py` | 可配置 STT/TTS Provider |
| `audio_clip_service.py` | 本地官方语音片段（用户自备） |
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
│       ├── ref/                 # GPT-SoVITS 参考音频（本地，不入库）
│       └── official_lines/      # 官方片段 JSON + 本地 wav（不入库）
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
│   ├── audio_clip_service.py
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
| `STT_PROVIDER` | `local_whisper` / `openai` / `baidu` |
| `TTS_PROVIDER` | `edge` / `openai` / `gpt_sovits` / `custom` / `official_clips` |
| `TTS_FALLBACK_PROVIDER` | GPT-SoVITS 失败时回退，默认 `edge` |
| `VOICE_NAME` | edge-tts 音色，如 `zh-CN-XiaoxiaoNeural` |
| `GPT_SOVITS_URL` | 本地 GPT-SoVITS 服务地址，默认 `http://localhost:9872` |
| `PORTRAIT_PATH` / `BACKGROUND_PATH` / `AVATAR_PATH` | 素材路径 |

完整列表见 [`.env.example`](.env.example)。

> **迁移提示**：若从旧版升级，默认 STT 现为 `local_whisper`、TTS 为 `gpt_sovits`。无本地 Whisper 时可设 `STT_PROVIDER=openai`；无 GPT-SoVITS 时可设 `TTS_PROVIDER=edge`。

## 数据库说明

- 文件：`data/elysia_companion.db`（首次运行自动创建）
- 首次启动若存在旧 JSON，会自动迁移对话与记忆
- `STORAGE_BACKEND=json` 时仅使用 JSON，不写 SQLite
- 实验室页可查看记录数量与亲密度

## 本地语音部署

### 语音链路

```
用户语音输入（录音 / 上传）
    → STT 转文字
    → 现有聊天逻辑（LLM 生成爱莉希雅回复）
    → TTS 生成语音
    → Streamlit 播放
    → 文本、音频路径写入 SQLite（conversations + voice_logs）
```

### 支持的 Provider

| 类型 | Provider | 说明 |
|------|----------|------|
| STT | `local_whisper` | 本地 faster-whisper（默认，无需 API Key） |
| STT | `openai` | OpenAI 兼容 Whisper（`AUDIO_API_KEY` 空则复用 `API_KEY`） |
| STT | `baidu` | 百度语音识别（可选，需 `BAIDU_API_KEY` / `BAIDU_SECRET_KEY`） |
| TTS | `edge` | edge-tts 兜底，生成 mp3 |
| TTS | `openai` | OpenAI 兼容 TTS |
| TTS | `gpt_sovits` | 本地 GPT-SoVITS HTTP 服务（高质量角色向语音） |
| TTS | `custom` | 用户自有的合法授权本地 TTS HTTP 接口 |
| 片段 | `official_clips` | 仅播放本地预置片段，不动态合成 |

### 快速开始

```bash
pip install -r requirements.txt
# 可选：本地 STT
pip install faster-whisper
# 可选：edge-tts 兜底
pip install edge-tts

copy .env.example .env
# 编辑 ENABLE_VOICE=true、STT_PROVIDER、TTS_PROVIDER 等

streamlit run app.py
```

### GPT-SoVITS 本地使用

1. **自行安装并启动** [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) HTTP 服务（常见端口 `9872` 或官方 `api.py` 的 `9880`）。
2. 在 `.env` 中配置：

```env
ENABLE_VOICE=true
TTS_PROVIDER=gpt_sovits
TTS_FALLBACK_PROVIDER=edge
GPT_SOVITS_URL=http://localhost:9872
GPT_SOVITS_REF_AUDIO=assets/audio/ref/elysia_ref.wav
GPT_SOVITS_PROMPT_TEXT=你的参考音频对应文本
```

3. **参考音频**：将合法拥有的 wav 放入 `assets/audio/ref/`（该目录文件不会提交 Git）。`GPT_SOVITS_REF_AUDIO` 须为 **GPT-SoVITS 进程能读取的路径**（若在容器中运行，请使用容器内路径）。
4. 本项目 **仅调用** 本地 HTTP 服务，**不包含** 任何官方声线模型、权重或参考音频。
5. 服务未启动时，页面提示「未检测到本地 GPT-SoVITS 服务…」并自动回退 `edge-tts`，**不影响文字聊天**。

### 官方语音片段（本地）

- 编辑 [`assets/audio/official_lines/official_clips.json`](assets/audio/official_lines/official_clips.json) 登记场景与文件路径（`greeting` / `thinking` / `comfort` 等）。
- 仓库 **不包含** 官方语音素材；片段仅供用户在本机合法使用。
- **请勿** 将官方语音上传到公开 GitHub。
- 本项目 **不提供** 声线克隆、官方声优复刻或素材提取教程。

### 语音功能调试

| 需求 | 配置 |
|------|------|
| 关闭语音 | `ENABLE_VOICE=false` |
| 仅用 edge-tts | `TTS_PROVIDER=edge` |
| 使用 GPT-SoVITS | `TTS_PROVIDER=gpt_sovits`，并启动本地服务 |
| 使用云端 Whisper | `STT_PROVIDER=openai`，配置 `API_KEY` |
| 清理生成缓存 | 「语音」页「一键清理缓存」，或删除 `data/audio_cache/` |

### Custom TTS 接口

`TTS_PROVIDER=custom` 时，向 `CUSTOM_TTS_ENDPOINT` 发送 JSON `{"text": "..."}`，响应为音频字节流，或 JSON 含 `audio_url` / `audio_path`。  
**仅适用于您拥有合法授权的本地语音模型**，仓库不提供声线克隆教程。

## 素材使用

见 [`assets/README.md`](assets/README.md) 与 [`assets/audio/README.md`](assets/audio/README.md)。将合法获得的图片放入 `assets/images/`；仓库不包含受版权保护的大体积官方素材与官方配音。

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

- 本项目为 **fan-made non-commercial demo**，与 miHoYo / HoYoverse **无任何官方关联**
- **不拥有** 爱莉希雅角色、官方语音或游戏素材版权
- 官方素材与语音片段仅限用户 **本地合法使用**；请勿将官方语音资源提交到公开仓库
- 本项目 **不提供** 声线克隆教程，也 **不鼓励** 未授权复刻官方声线
- 语音合成为通用 TTS 或用户自部署模型，**不代表** 官方角色配音
- 生成内容由大模型产生，涉及安全话题时会做脱离角色的安全提示

## Roadmap

- [ ] 多用户 / 多 session 隔离
- [ ] Hugging Face Dataset 备份对话
- [ ] 评估规则 + LLM 混合打分
- [ ] 用户反馈（点赞/点踩）闭环
- [ ] Docker 一键部署

## License

MIT（代码）；游戏相关 IP 归原权利人所有。
