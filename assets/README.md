# Assets 素材说明

本项目为 **fan-made、non-commercial** 角色陪伴互动 Demo，与游戏官方无任何关联。

## 版权

- 游戏名称、角色名称、美术素材等知识产权归原权利人所有。
- 本仓库**不包含**官方立绘、语音等大体积受版权保护素材。
- 请勿将未获授权的官方素材提交到公开 Git 仓库。

## 目录结构

```
assets/
├── images/
│   ├── elysia_portrait.png   # 首页立绘（可选）
│   ├── elysia_background.png # 背景图（可选）
│   └── avatar.png            # 侧边栏头像（可选）
└── audio/                    # 参考音频与官方片段（见 audio/README.md）
    ├── ref/                  # GPT-SoVITS 参考 wav（本地，不入库）
    └── official_lines/       # official_clips.json + 本地片段
```

## 使用方式

1. 将你**合法获得**的素材放入 `assets/images/`（建议压缩后 < 500KB）。
2. 或在 `.env` 中修改 `PORTRAIT_PATH` / `BACKGROUND_PATH` / `AVATAR_PATH`。
3. 若文件不存在，应用会自动使用渐变 + emoji 占位，**不会报错**。

## 建议

- 作品集展示可使用自制插画、剪影或抽象粉色主题图。
- 不要使用官方声优录音；语音功能使用通用 TTS 或用户自部署 GPT-SoVITS，不代表官方配音。
- 官方语音片段说明见 [`audio/README.md`](audio/README.md)。
