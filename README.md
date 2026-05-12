# TTS Paragraph Split

TTS Paragraph Split 用于把 Shinsekai 内置的“按标点切分角色台词 TTS”替换为“只按段落/换行切分”。

## 插件信息

| 字段 | 内容 |
| --- | --- |
| 插件 ID | `com.shinsekai.tts_paragraph_split` |
| 版本 | `0.1.0` |
| 作者 | `End0rph1nww` |
| 插件入口 | `plugins.tts_paragraph_split.plugin:TtsParagraphSplitPlugin` |
| 插件能力 | TTS 消息处理器 |

## 功能说明

Shinsekai 主程序内置的普通角色 TTS handler 会按标点切分台词，并合并成较短的 TTS 片段。本插件只覆盖普通角色台词路径，把切分策略改成按换行或空行段落切分。

本插件不会处理系统类消息。以下消息仍然交给 Shinsekai 内置 handler：

- 思维链/状态消息。
- 系统对话消息。
- BGM 消息。
- CG 消息。

插件会保留原本的立绘参考音频和 TTS 生成流程，只改变文本切分策略。

## 安装方式

把本目录复制到：

```text
plugins/tts_paragraph_split
```

然后在 `data/config/plugins.yaml` 中加入：

```yaml
- entry: plugins.tts_paragraph_split.plugin:TtsParagraphSplitPlugin
  enabled: true
```

修改 `plugins.yaml` 后需要重启 Shinsekai。插件 handler 只会在启动时收集。

## 依赖说明

本插件不需要额外 Python 依赖。它只使用 Python 标准库和 Shinsekai 主程序已经提供的模块。

## 行为细节

段落切分由 `split_paragraphs(text)` 实现。切分正则为：

```python
r"(?:\r?\n\s*)+"
```

如果台词只有一个段落，插件会生成一条 TTS 音频，并向 UI 队列发送一条消息。

如果台词包含多个段落，插件会为每个段落分别生成一条 TTS 音频。第一段发送原始完整台词和特效；后续段落只作为音频续播；最后一段会标记为最终片段。

如果主程序没有启用 TTS manager，插件会和主程序角色台词路径一样，回退到当前立绘绑定的语音文件。

## 运行说明

- 本插件通过 `register_message_handler` 注册 `MessageHandler`。
- 插件 handler 会排在内置 handler 前面，所以启用后，普通角色台词会优先被本插件接管。
- 本插件没有设置页，也没有额外配置文件。
- 禁用本插件后，Shinsekai 会回到内置的按标点切分 TTS 行为。

## 常见问题

如果台词仍然被标点切碎，请确认 `data/config/plugins.yaml` 中插件入口已启用，然后重启 Shinsekai。

如果某条消息没有被本插件处理，请检查它是否属于系统、BGM、CG 或思维链消息。这些消息会被主动交还给内置 handler。
