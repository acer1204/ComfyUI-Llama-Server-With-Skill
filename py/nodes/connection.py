"""Configuration nodes: server connection, sampling params, media options, skill."""

from .. import config, skills

CATEGORY = "Llama Prompter/advanced"

FORMATS = ["jpeg", "png", "webp"]


class LlamaServer:
    """Holds everything needed to talk to a llama.cpp ``llama-server``."""

    @classmethod
    def INPUT_TYPES(cls):
        cfg = config.load()
        return {
            "required": {
                "base_url": ("STRING", {
                    "default": cfg["base_url"],
                    "tooltip": "llama-server 位址，例如 http://127.0.0.1:8080 或 https://host:10011。"
                               "結尾加不加 /v1 都可以。",
                }),
                "model": ("STRING", {
                    "default": cfg["model"],
                    "tooltip": "模型名稱。留空即使用伺服器目前載入的模型。",
                }),
                "api_key": ("STRING", {
                    "default": cfg["api_key"],
                    "tooltip": "若 llama-server 以 --api-key 啟動才需要填。",
                }),
                "timeout": ("INT", {
                    "default": cfg["timeout"], "min": 5, "max": 36000, "step": 5,
                    "tooltip": "單次請求逾時秒數。影片多幀輸入建議調大。",
                }),
                "verify_ssl": ("BOOLEAN", {
                    "default": cfg["verify_ssl"],
                    "tooltip": "自簽憑證請關閉。",
                }),
                "stream": ("BOOLEAN", {
                    "default": cfg["stream"],
                    "tooltip": "串流回應，可在產生途中被 ComfyUI 中斷。",
                }),
                "free_comfy_vram": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "送出請求前先把 ComfyUI 已載入的模型移出顯存，"
                               "讓同一張卡上的 llama-server 有空間。GPU 記憶體不夠就開這個。",
                }),
                "keep_alive": ("INT", {
                    "default": -1, "min": -1, "max": 86400, "step": 10,
                    "tooltip": "產生後模型在顯存裡留多久（秒）。-1 = 不卸載；"
                               "0 = 立刻卸載；N = 閒置 N 秒後卸載。"
                               "需要伺服器支援（Ollama / llama-swap 等）；"
                               "純 llama-server 會忽略，實際結果寫在 info 輸出。",
                }),
                "use_global_settings": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "開啟時忽略以上欄位，改用 ComfyUI 設定面板的 Llama Prompter 設定。",
                }),
            },
        }

    RETURN_TYPES = ("LLAMA_SERVER",)
    RETURN_NAMES = ("server",)
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "設定 llama-server 連線 (位址 / 模型 / 金鑰 / 逾時)。"

    def build(self, base_url, model, api_key, timeout, verify_ssl, stream,
              free_comfy_vram=False, keep_alive=-1, use_global_settings=False):
        if use_global_settings:
            cfg = config.load(force=True)
            server = {
                "base_url": cfg["base_url"],
                "model": cfg["model"],
                "api_key": cfg["api_key"],
                "timeout": int(cfg["timeout"]),
                "verify_ssl": bool(cfg["verify_ssl"]),
                "stream": bool(cfg["stream"]),
            }
        else:
            server = {
                "base_url": (base_url or "").strip() or config.get("base_url"),
                "model": (model or "").strip(),
                "api_key": (api_key or "").strip(),
                "timeout": int(timeout),
                "verify_ssl": bool(verify_ssl),
                "stream": bool(stream),
            }
        server["debug"] = bool(config.get("debug"))
        server["free_comfy_vram"] = bool(free_comfy_vram)
        server["keep_alive"] = int(keep_alive)
        return (server,)


class LlamaParams:
    """Sampling parameters with llama.cpp friendly defaults."""

    @classmethod
    def INPUT_TYPES(cls):
        cfg = config.load()
        return {
            "required": {
                "temperature": ("FLOAT", {
                    "default": cfg["temperature"], "min": 0.0, "max": 2.0, "step": 0.01,
                    "tooltip": "0 = 幾乎決定性輸出；提示詞生成建議 0.6 ~ 0.9。",
                }),
                "top_p": ("FLOAT", {"default": cfg["top_p"], "min": 0.0, "max": 1.0, "step": 0.01}),
                "top_k": ("INT", {"default": cfg["top_k"], "min": 0, "max": 1000}),
                "min_p": ("FLOAT", {"default": cfg["min_p"], "min": 0.0, "max": 1.0, "step": 0.01}),
                "max_tokens": ("INT", {
                    "default": cfg["max_tokens"], "min": 16, "max": 32768, "step": 16,
                    "tooltip": "回應長度上限。",
                }),
                "repeat_penalty": ("FLOAT", {
                    "default": cfg["repeat_penalty"], "min": 0.0, "max": 2.0, "step": 0.01,
                }),
                "presence_penalty": ("FLOAT", {
                    "default": cfg["presence_penalty"], "min": -2.0, "max": 2.0, "step": 0.01,
                }),
                "frequency_penalty": ("FLOAT", {
                    "default": cfg["frequency_penalty"], "min": -2.0, "max": 2.0, "step": 0.01,
                }),
                "seed": ("INT", {
                    "default": 0, "min": -1, "max": 0xFFFFFFFFFFFFFFFF,
                    "control_after_generate": True,
                    "tooltip": "-1 = 每次隨機（節點也會因此每次重跑）。",
                }),
                "stop": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "停止字串，以 | 分隔多個。",
                }),
            },
            "optional": {
                "json_schema": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "選填。填入 JSON Schema 可強制模型輸出結構化 JSON。",
                }),
                "grammar": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "選填。llama.cpp GBNF 文法。",
                }),
            },
        }

    RETURN_TYPES = ("LLAMA_PARAMS",)
    RETURN_NAMES = ("params",)
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "模型取樣參數（已附常用預設值）。"

    def build(self, temperature, top_p, top_k, min_p, max_tokens, repeat_penalty,
              presence_penalty, frequency_penalty, seed, stop,
              json_schema="", grammar=""):
        params = {
            "temperature": float(temperature),
            "top_p": float(top_p),
            "top_k": int(top_k),
            "min_p": float(min_p),
            "max_tokens": int(max_tokens),
            "repeat_penalty": float(repeat_penalty),
            "presence_penalty": float(presence_penalty),
            "frequency_penalty": float(frequency_penalty),
            "seed": int(seed),
        }
        stop_list = [s for s in (stop or "").split("|") if s.strip()]
        if stop_list:
            params["stop"] = stop_list

        schema_text = (json_schema or "").strip()
        if schema_text:
            import json as _json

            try:
                params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "output", "schema": _json.loads(schema_text)},
                }
            except ValueError as exc:
                raise ValueError("json_schema 不是合法 JSON: %s" % exc)

        grammar_text = (grammar or "").strip()
        if grammar_text:
            params["grammar"] = grammar_text
        return (params,)


class LlamaMediaOptions:
    """How images / video frames / audio are down-sampled before upload."""

    @classmethod
    def INPUT_TYPES(cls):
        cfg = config.load()
        from .. import media

        return {
            "required": {
                "max_frames": ("INT", {
                    "default": cfg["max_frames"], "min": 1, "max": 256,
                    "tooltip": "送給模型的最大張數（影片會先抽幀）。顯存/context 不夠就調小。",
                }),
                "frame_sample": (media.SAMPLE_MODES, {
                    "default": "uniform",
                    "tooltip": "uniform = 全片均勻抽樣；every_n = 每 N 幀取一張。",
                }),
                "every_n": ("INT", {"default": 1, "min": 1, "max": 1000}),
                "max_image_side": ("INT", {
                    "default": cfg["max_image_side"], "min": 128, "max": 4096, "step": 32,
                    "tooltip": "長邊縮放上限，直接影響 vision token 數與顯存用量。",
                }),
                "image_format": (FORMATS, {"default": cfg["image_format"]}),
                "jpeg_quality": ("INT", {"default": cfg["jpeg_quality"], "min": 30, "max": 100}),
            },
            "optional": {
                "max_audio_seconds": ("FLOAT", {
                    "default": 60.0, "min": 1.0, "max": 3600.0, "step": 1.0,
                    "tooltip": "音訊輸入的長度上限（需要支援 audio 的模型）。",
                }),
            },
        }

    RETURN_TYPES = ("LLAMA_MEDIA",)
    RETURN_NAMES = ("media_options",)
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "影像 / 影片抽幀與壓縮設定。"

    def build(self, max_frames, frame_sample, every_n, max_image_side, image_format,
              jpeg_quality, max_audio_seconds=60.0):
        return ({
            "max_frames": int(max_frames),
            "frame_sample": frame_sample,
            "every_n": int(every_n),
            "max_image_side": int(max_image_side),
            "image_format": image_format,
            "jpeg_quality": int(jpeg_quality),
            "max_audio_seconds": float(max_audio_seconds),
        },)


class LlamaSkillNode:
    """Pick a skill, and chain several of them in order."""

    MODES = ["manual", "from_prompt", "auto", "off"]

    @classmethod
    def INPUT_TYPES(cls):
        names = skills.list_names()
        default = config.get("default_skill") or skills.NONE_SKILL
        if default not in names:
            resolved = skills.get_skill(default)
            default = resolved["path"] if resolved else names[0]
        return {
            "required": {
                "skill": (names, {
                    "default": default,
                    "tooltip": "技能以 群組/名稱 列出。匯入新技能後按 R 重新整理節點定義。",
                }),
                "mode": (cls.MODES, {
                    "default": "manual",
                    "tooltip": "manual=用上面選的；from_prompt=文字裡寫 /skill 名稱 來切換；"
                               "auto=讓模型依描述再追加一個；off=不套用任何技能。",
                }),
            },
            "optional": {
                "chain": ("LLAMA_SKILL", {
                    "tooltip": "串接上一個 Skill 節點。前面的先套用，這個接在後面，"
                               "所以把格式技能（例如 h3-prompt-writing）放最前面。",
                }),
                "skill_override": ("STRING", {
                    "default": "",
                    "tooltip": "直接輸入技能名稱，優先於下拉選單。可用逗號分隔多個，依序套用。",
                }),
                "extra_instructions": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "附加在技能系統提示後面的額外規則。",
                }),
                "apply_skill_defaults": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "套用技能 front matter 裡的 defaults（temperature、max_tokens…）；"
                               "開啟時會覆寫取樣參數節點的同名欄位。",
                }),
                "include_references": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "把技能資料夾裡 references/ 的內容一併放進系統提示。"
                               "MiniMax-H3 這類技能需要，但很吃 context。",
                }),
            },
        }

    RETURN_TYPES = ("LLAMA_SKILL", "STRING")
    RETURN_NAMES = ("skill", "system_prompt")
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "選擇 skill，可串接多個並保有順序。"

    def build(self, skill, mode, chain=None, skill_override="", extra_instructions="",
              apply_skill_defaults=True, include_references=False):
        previous = dict(chain or {})
        items = list(previous.get("items") or [])

        wanted = [n.strip() for n in (skill_override or "").split(",") if n.strip()]
        if not wanted and skill != skills.NONE_SKILL:
            wanted = [skill]

        for name in wanted:
            items.append({
                "name": name,
                "include_references": bool(include_references),
            })

        notes = [previous.get("extra_instructions", ""), (extra_instructions or "").strip()]
        selector = {
            "items": items,
            "mode": mode,
            "extra_instructions": "\n\n".join(n for n in notes if n),
            "apply_defaults": bool(apply_skill_defaults),
        }

        parts = []
        for item in items:
            resolved = skills.get_skill(item["name"])
            if not resolved:
                parts.append("# missing skill: %s" % item["name"])
                continue
            body = "# skill: %s\n\n%s" % (resolved["path"], resolved["system"])
            if item["include_references"]:
                body += skills.load_references(resolved)
            parts.append(body)
        preview = "\n\n---\n\n".join(parts)
        if selector["extra_instructions"] and preview:
            preview += "\n\n" + selector["extra_instructions"]
        return (selector, preview)


class LlamaVideoSpec:
    """Duration / aspect / mode, so a video skill stops asking for them."""

    @classmethod
    def INPUT_TYPES(cls):
        from .prompter import ASPECT_RATIOS, MODEL_TYPES, RESOLUTIONS

        return {
            "required": {
                "model_type": (MODEL_TYPES, {
                    "default": "T2VA",
                    "tooltip": "T2VA=純文字；I2VA=給首幀；L2VA=給尾幀；"
                               "FL2VA=給首尾幀；Ref2VA=給參考圖。"
                               "影像請用 Llama 影像插槽 節點標上角色。",
                }),
                "duration_seconds": ("FLOAT", {
                    "default": 6.0, "min": 0.0, "max": 15.0, "step": 0.5,
                    "tooltip": "目標長度（秒）。0 = 不指定。",
                }),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "16:9"}),
                "resolution": (RESOLUTIONS, {"default": "Native (ShortEdge 768px)"}),
            },
            "optional": {
                "custom_aspect": ("STRING", {
                    "default": "",
                    "tooltip": "aspect_ratio 選 CUSTOM 時填這裡，例如 21:9。",
                }),
                "fps": ("INT", {"default": 0, "min": 0, "max": 120,
                                "tooltip": "0 = 不指定。"}),
                "audio": ("BOOLEAN", {"default": True, "tooltip": "是否要產生聲音描述。"}),
                "notes": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "其他要交代的限制，會原樣附在規格區塊裡。",
                }),
            },
        }

    RETURN_TYPES = ("LLAMA_SPEC", "STRING")
    RETURN_NAMES = ("spec", "spec_text")
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "影片生成規格：模式 / 秒數 / 比例 / 解析度。"

    def build(self, model_type, duration_seconds, aspect_ratio, resolution,
              custom_aspect="", fps=0, audio=True, notes=""):
        from .prompter import spec_block

        ratio = custom_aspect.strip() if aspect_ratio == "CUSTOM" else aspect_ratio
        spec = {
            "model_type": model_type,
            "duration_seconds": round(float(duration_seconds), 2) if duration_seconds else "",
            "aspect_ratio": ratio,
            "resolution": resolution,
            "fps": int(fps) or "",
            "audio": "yes" if audio else "no",
            "notes": (notes or "").strip(),
        }
        return (spec, spec_block(spec))


class LlamaImageSlot:
    """Attach an image with a role label (first frame, last frame, reference...)."""

    @classmethod
    def INPUT_TYPES(cls):
        from .. import media

        return {
            "required": {
                "image": ("IMAGE",),
                "role": (media.ROLES, {
                    "default": "reference",
                    "tooltip": "這張圖的角色。模型會先讀到 [first_frame] 這類標籤再看圖。",
                }),
            },
            "optional": {
                "custom_label": ("STRING", {
                    "default": "",
                    "tooltip": "role 選 custom 時使用，例如 character_a。",
                }),
                "chain": ("LLAMA_IMAGES", {
                    "tooltip": "串接上一個影像插槽，可接任意多張。",
                }),
            },
        }

    RETURN_TYPES = ("LLAMA_IMAGES",)
    RETURN_NAMES = ("image_slots",)
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "把影像標上角色（首幀 / 尾幀 / 參考圖），可串接多個。"

    def build(self, image, role, custom_label="", chain=None):
        label = (custom_label or "").strip() if role == "custom" else role
        slots = list(chain or [])
        slots.append({"label": label or "reference", "image": image})
        return (slots,)


class LlamaSkillList:
    """Utility node that dumps the available skills as text."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "refresh": ("BOOLEAN", {"default": True, "tooltip": "重新掃描 skills 目錄。"}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("catalog",)
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "列出目前可用的 skill 名稱與說明。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def build(self, refresh=True):
        if refresh:
            skills.invalidate()
        lines = []
        for path in config.skill_search_paths():
            lines.append("# " + path)
        lines.append("")
        lines.append(skills.catalog_text())
        return ("\n".join(lines),)
