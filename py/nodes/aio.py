"""One node that does the whole job.

Connection, sampling and media settings live in the ComfyUI settings panel, so
this node only asks for the things that change per shot: the media, up to five
skills, a system prompt, and the extra text.  Inputs appear as you fill them,
so an unused workflow shows one image slot rather than fifteen.

What reaches the model, in this order:

    system : chosen system prompt (or the skills' own)
    user   : skill_1 + skill_2 + ... + your text + [generation spec] + format rules
"""

import time

from .. import config, media as media_utils, presets, skills
from .prompter import (
    ASPECT_RATIOS, LANGUAGES, MODEL_TYPES, LlamaPrompter, fields_for, parse_fields,
)

CATEGORY = "Llama Prompter"

PLAIN = "plain (single prompt)"
AIO_MODES = [PLAIN] + MODEL_TYPES

# Which role each image takes, per mode.  Saves wiring up slot nodes by hand.
ROLE_PLANS = {
    "I2VA": ["first_frame"],
    "L2VA": ["last_frame"],
    "FL2VA": ["first_frame", "last_frame"],
}


def _image_roles(mode, count):
    plan = ROLE_PLANS.get(mode)
    if plan:
        roles = list(plan[:count])
        roles += ["reference_%d" % (i + 1) for i in range(len(roles), count)]
        return roles
    if mode == "Ref2VA":
        return ["reference_%d" % (i + 1) for i in range(count)]
    return ["image_%d" % (i + 1) for i in range(count)]


class LlamaPromptAIO(LlamaPrompter):
    """Everything in one node."""

    @classmethod
    def INPUT_TYPES(cls):
        cfg = config.load()
        max_images = int(cfg.get("max_images", 9))
        max_videos = int(cfg.get("max_videos", 3))
        max_audios = int(cfg.get("max_audios", 3))
        max_skills = int(cfg.get("max_skills", 5))
        skill_names = skills.list_names()

        required = {
            "text": ("STRING", {
                "default": "", "multiline": True, "dynamicPrompts": False,
                "tooltip": "你要補充的內容。也可以像 webui 那樣自己一行寫 /技能名稱，"
                           "會接在下面選的技能後面。",
            }),
            "mode": (AIO_MODES, {
                "default": PLAIN,
                "tooltip": "plain = 只輸出一則提示詞；其餘為 H3 影片模式，會拆成欄位輸出。"
                           "I2VA 第一張圖當首幀，FL2VA 第一張首幀第二張尾幀，"
                           "L2VA 第一張當尾幀，Ref2VA 全部當參考圖。",
            }),
            "system_prompt": (presets.names(), {
                "default": presets.NONE,
                "tooltip": "在 ComfyUI 設定 → Llama Prompter → System prompts 自行增加。",
            }),
            "output_language": (LANGUAGES, {"default": "English"}),
        }
        for index in range(1, max_skills + 1):
            required["skill_%d" % index] = (skill_names, {
                "default": skills.NONE_SKILL,
                "tooltip": "依序套用。格式技能放前面，修飾技能放後面。",
            })
        required["duration_seconds"] = ("FLOAT", {
            "default": 6.0, "min": 0.0, "max": 15.0, "step": 0.5,
            "tooltip": "影片模式的目標長度。0 = 不指定。plain 模式會忽略。",
        })
        required["aspect_ratio"] = (ASPECT_RATIOS, {"default": "16:9"})

        optional = {}
        for index in range(1, max_images + 1):
            optional["image_%d" % index] = ("IMAGE",)
        for index in range(1, max_videos + 1):
            optional["video_%d" % index] = ("VIDEO",)
        for index in range(1, max_audios + 1):
            optional["audio_%d" % index] = ("AUDIO",)
        optional["extra_instructions"] = ("STRING", {
            "default": "", "multiline": False,
            "tooltip": "附加規則，接在所有技能後面。",
        })

        return {"required": required, "optional": optional,
                "hidden": {"node_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("STRING",) * 8
    RETURN_NAMES = (
        "full_prompt",
        "subject_definitions",
        "summary",
        "retention_analysis",
        "description",
        "overall_soundscape",
        "non_diegetic_music",
        "info",
    )
    OUTPUT_TOOLTIPS = (
        "plain 模式的提示詞，或影片模式所有欄位合併。",
        "Ref2VA：參考主體定義。",
        "Ref2VA：摘要。",
        "Ref2VA：保留分析。",
        "主描述。Ref2VA 給 detailed_description，其他給 integrated_multimodal_description。",
        "環境音描述。",
        "配樂描述。",
        "本次請求的統計資訊。",
    )
    FUNCTION = "run_aio"
    CATEGORY = CATEGORY
    DESCRIPTION = ("一個節點完成全部：圖片 / 影片 / 音訊 / 文字 + 最多 5 個技能。"
                   "連線與取樣參數請在 ComfyUI 設定面板調整。")

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return None

    # ------------------------------------------------------------------
    def run_aio(self, text, mode, system_prompt, output_language,
                duration_seconds=6.0, aspect_ratio="16:9",
                extra_instructions="", node_id=None, **slots):
        cfg = config.load(force=True)
        started = time.time()
        log = []

        # --- server + sampling come from the settings panel ---------------
        server = {
            "base_url": cfg["base_url"],
            "model": cfg["model"],
            "api_key": cfg["api_key"],
            "timeout": int(cfg["timeout"]),
            "verify_ssl": bool(cfg["verify_ssl"]),
            "stream": bool(cfg["stream"]),
            "debug": bool(cfg["debug"]),
            "free_comfy_vram": False,
            "keep_alive": -1,
        }
        params = {
            "temperature": cfg["temperature"],
            "top_p": cfg["top_p"],
            "top_k": cfg["top_k"],
            "min_p": cfg["min_p"],
            "max_tokens": cfg["max_tokens"],
            "repeat_penalty": cfg["repeat_penalty"],
            "presence_penalty": cfg["presence_penalty"],
            "frequency_penalty": cfg["frequency_penalty"],
            "seed": 0,
        }
        media_options = {
            "max_frames": int(cfg["max_frames"]),
            "frame_sample": "uniform",
            "every_n": 1,
            "max_image_side": int(cfg["max_image_side"]),
            "image_format": cfg["image_format"],
            "jpeg_quality": int(cfg["jpeg_quality"]),
            "max_video_seconds": float(cfg.get("max_video_seconds", 15.0)),
            "max_audio_seconds_total": float(cfg.get("max_audio_seconds_total", 15.0)),
        }

        # --- gather the numbered inputs in order --------------------------
        images = self._collect(slots, "image_", int(cfg.get("max_images", 9)))
        videos = self._collect(slots, "video_", int(cfg.get("max_videos", 3)))
        audios = self._collect(slots, "audio_", int(cfg.get("max_audios", 3)))

        chosen = []
        for index in range(1, int(cfg.get("max_skills", 5)) + 1):
            name = slots.get("skill_%d" % index)
            if name and name != skills.NONE_SKILL:
                chosen.append(name)

        # A /name line in the text appends to the chain, like a webui command.
        directives, cleaned_text = skills.extract_directives(text)
        for name in directives:
            if name not in chosen:
                chosen.append(name)

        use_refs = bool(cfg.get("include_references", False))
        selector = {
            "items": [{"name": name, "include_references": use_refs} for name in chosen],
            "mode": "manual",
            "extra_instructions": (extra_instructions or "").strip(),
            "apply_defaults": True,
        }

        spec = None
        fields = None
        if mode != PLAIN:
            spec = {
                "model_type": mode,
                "duration_seconds": round(float(duration_seconds), 2) if duration_seconds else "",
                "aspect_ratio": aspect_ratio,
                "resolution": cfg.get("resolution", ""),
                "audio": "yes",
                "notes": "",
            }
            fields = fields_for(mode)

        image_slots = self._label_images(images, mode)
        clip_parts, frame_count, clip_bytes, clip_notes = media_utils.build_clip_parts(
            videos, media_options)
        audio_parts, audio_seconds, audio_bytes, audio_notes = media_utils.build_audio_parts(
            audios, media_options)
        log.extend(clip_notes)
        log.extend(audio_notes)

        outcome = self._execute(
            server=server, text=cleaned_text, output_language=output_language,
            params=params, media_options=media_options, skill=selector,
            system_prefix=presets.get(system_prompt), image_slots=image_slots,
            extra_parts=clip_parts + audio_parts, spec=spec, fields=fields,
            force_json=bool(fields), node_id=node_id,
        )

        info = outcome["info"]
        extra_bytes = clip_bytes + audio_bytes
        if extra_bytes:
            info += "\nclips: %d frame(s), audio %.1fs, +%.1f KB" % (
                frame_count, audio_seconds, extra_bytes / 1024.0)
        if log:
            info += "\n" + "\n".join(log)

        if not fields:
            return {"ui": {"text": [outcome["prompt"]]},
                    "result": (outcome["prompt"], "", "", "", "", "", "", info)}

        values = parse_fields(outcome["cleaned"], fields)
        missing = [name for name in fields if not values.get(name)]
        info += "\nmode: %s | fields: %s" % (mode, ", ".join(fields))
        if missing:
            info += "\nmissing fields: " + ", ".join(missing)

        full = "\n\n".join("%s: %s" % (name, values[name])
                           for name in fields if values.get(name)) or outcome["prompt"]
        description = (values.get("detailed_description")
                       or values.get("integrated_multimodal_description", ""))
        return {
            "ui": {"text": [full]},
            "result": (
                full,
                values.get("subject_definitions", ""),
                values.get("summary", ""),
                values.get("retention_analysis", ""),
                description,
                values.get("overall_soundscape", ""),
                values.get("non_diegetic_music", ""),
                info,
            ),
        }

    @staticmethod
    def _collect(slots, prefix, limit):
        found = []
        for index in range(1, limit + 1):
            value = slots.get("%s%d" % (prefix, index))
            if value is not None:
                found.append(value)
        return found

    @staticmethod
    def _label_images(images, mode):
        roles = _image_roles(mode, len(images))
        return [{"label": role, "image": batch} for role, batch in zip(roles, images)]
