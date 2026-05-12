from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from core.messaging.dialog_tokens import (
    match_bgm_name,
    match_cg_name,
    match_cot_tts,
    match_system_dialog_tts,
)
from core.runtime.app_runtime import get_app_runtime, tts_emit_to_ui_queue
from i18n import tr as tr_i18n
from sdk.handlers import MessageHandler
from sdk.messages import LLMDialogMessage, TTSOutputMessage
from sdk.plugin import PluginBase

if TYPE_CHECKING:
    from sdk.plugin_host_context import PluginHostContext
    from sdk.register import PluginCapabilityRegistry


_PARAGRAPH_RE = re.compile(r"(?:\r?\n\s*)+")
PLUGIN_ID = "com.shinsekai.tts_paragraph_split"
PLUGIN_VERSION = "0.1.0"


def split_paragraphs(text: str) -> list[str]:
    """只按空行/换行段落切分，保留原插件“不按标点拆句”的行为。"""
    segments = [
        segment.strip()
        for segment in _PARAGRAPH_RE.split(text or "")
        if segment.strip()
    ]
    if segments:
        return segments
    return [text] if text else []


def _cc():
    return get_app_runtime().opencc


def _post_tts_busy(text: str) -> None:
    try:
        get_app_runtime().ui_update_manager.post_busy_bar(text, 0.0)
    except Exception:
        pass


def _hide_tts_busy() -> None:
    try:
        get_app_runtime().ui_update_manager.hide_busy_bar()
    except Exception:
        pass


def _optional_posix_path(value: object) -> str:
    if not value:
        return ""
    return Path(value).resolve().as_posix()


def _sprite_index(asset_id: object, sprite_count: int) -> int:
    """把 1-based 立绘编号转成列表索引；非法编号回退到 -1。"""
    try:
        idx = int(asset_id) - 1
        if idx < 0 or idx >= sprite_count:
            raise IndexError("Sprite ID out of range")
        return idx
    except (ValueError, TypeError, IndexError):
        print(f"TTS paragraph split plugin: invalid sprite id: {asset_id}")
        return -1


def _sprite_voice_path(character_config: object, asset_id: object) -> str:
    """无 TTS manager 时沿用角色立绘绑定语音，编号异常则安静回退为空。"""
    try:
        sprite_id = _sprite_index(asset_id, len(character_config.sprites))
        if sprite_id < 0:
            return ""
        return character_config.sprites[sprite_id].get("voice_path", "")
    except Exception:
        return ""


class ParagraphOnlyCharacterTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        name = msg.name or ""
        # 系统消息仍交给内置 handler；本插件只覆盖普通角色台词的 TTS 分段策略。
        if (
            match_cot_tts(_cc(), name)
            or match_system_dialog_tts(_cc(), name)
            or match_bgm_name(name)
            or match_cg_name(name)
        ):
            return False
        name_s = _cc().convert(name)
        return get_app_runtime().config.get_character_by_name(name_s) is not None

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        name_s = _cc().convert(msg.name)
        character_config = rt.config.get_character_by_name(name_s)
        if character_config is None:
            raise ValueError(f"Character not found: {name_s}")

        translate = msg.translate
        speech = msg.text or ""
        asset_id = msg.asset_id
        text_processor = rt.text_processor
        speech_text = speech
        if translate:
            text_processor = None
            speech_text = rt.text_processor.remove_parentheses(translate)

        audio_path = ""
        if rt.tts_manager:
            _post_tts_busy(tr_i18n("desktop.tts_busy_synthesizing", name=name_s))
            try:
                model_info = {
                    "character_name": name_s,
                    "sovits_model_path": _optional_posix_path(
                        character_config.sovits_model_path
                    ),
                    "gpt_model_path": _optional_posix_path(
                        character_config.gpt_model_path
                    ),
                }
                rt.tts_manager.switch_model(model_info)
                print("TTS paragraph split plugin: using model", name_s, model_info)

                sprite_id = _sprite_index(asset_id, len(character_config.sprites))
                ref_audio_path = _optional_posix_path(character_config.refer_audio_path)
                prompt_text = character_config.prompt_text
                if 0 <= sprite_id < len(character_config.sprites):
                    sprite_data = character_config.sprites[sprite_id]
                    if sprite_data.get("voice_text"):
                        ref_audio_path = _optional_posix_path(
                            sprite_data.get("voice_path")
                        )
                        prompt_text = sprite_data.get("voice_text")

                if text_processor:
                    speech_text = text_processor.remove_parentheses(speech_text)

                segments = split_paragraphs(speech_text)
                speed = character_config.speech_speed
                if len(segments) <= 1:
                    # 单段时保持内置链路：生成一次音频，再统一 emit 到 UI 队列。
                    audio_path = rt.tts_manager.generate_tts(
                        speech_text,
                        text_processor=text_processor,
                        ref_audio_path=ref_audio_path,
                        prompt_text=prompt_text,
                        prompt_lang=character_config.prompt_lang,
                        character_name=name_s,
                        speed_factor=speed,
                    )
                else:
                    asset_str = str(asset_id)
                    for index, segment in enumerate(segments):
                        path = rt.tts_manager.generate_tts(
                            segment,
                            text_processor=text_processor,
                            ref_audio_path=ref_audio_path,
                            prompt_text=prompt_text,
                            prompt_lang=character_config.prompt_lang,
                            character_name=name_s,
                            speed_factor=speed,
                        )
                        is_first = index == 0
                        is_last = index == len(segments) - 1
                        # 多段时每段单独入 UI 队列；首段携带原文和特效，后续段只接续播放。
                        rt.audio_path_queue.put(
                            TTSOutputMessage(
                                audio_path=path or "",
                                name=name_s,
                                text=speech if is_first else "",
                                asset_id=asset_str,
                                effect=msg.effect if is_first else "",
                                is_final_segment=is_last,
                                timeout=None if is_first else 0,
                            )
                        )
                    rt.tts_queue.task_done()
                    return
            finally:
                _hide_tts_busy()
        else:
            audio_path = _sprite_voice_path(character_config, asset_id)

        tts_emit_to_ui_queue(
            name_s,
            speech,
            str(asset_id),
            audio_path,
            is_system_message=False,
            effect=msg.effect,
        )


class TtsParagraphSplitPlugin(PluginBase):
    @property
    def plugin_id(self) -> str:
        return PLUGIN_ID

    @property
    def plugin_version(self) -> str:
        return PLUGIN_VERSION

    @property
    def plugin_name(self) -> str:
        return "TTS Paragraph Split"

    @property
    def plugin_description(self) -> str:
        return "Replaces character TTS sentence splitting with paragraph-only splitting."

    @property
    def plugin_author(self) -> str:
        return "End0rph1nww"

    @property
    def priority(self) -> int:
        return 10

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        register.register_message_handler(
            tts_handler=ParagraphOnlyCharacterTtsHandler()
        )


Plugin = TtsParagraphSplitPlugin
