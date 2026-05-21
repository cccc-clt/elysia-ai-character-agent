# 音频资源目录

本仓库 **不包含** 任何官方角色配音、模型权重或参考音频。

## 目录说明

| 路径 | 用途 |
|------|------|
| `ref/` | GPT-SoVITS 参考音频占位目录。请将您**合法拥有授权**的参考 wav 放在本地，并在 `.env` 中配置 `GPT_SOVITS_REF_AUDIO`。路径需能被 GPT-SoVITS 服务端读取。 |
| `official_lines/` | 本地官方语音片段库（可选）。编辑 `official_clips.json` 登记文件路径，应用按场景播放。 |

## 官方语音片段

- 仓库仅提供 `official_clips.json` 模板，**不含** wav/mp3 素材。
- 片段仅供用户在本机合法使用，**请勿**将官方语音上传到公开 GitHub。
- 本项目不提供声线克隆、官方声优复刻或素材提取教程。

## 生成语音缓存

TTS/STT 运行时文件保存在 `data/audio_cache/`，已在 `.gitignore` 中忽略。
