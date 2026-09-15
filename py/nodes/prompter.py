"""The main node: image / video / audio / text -> prompt via llama-server."""

import json
import re
import time

from .. import config, llama_client, media as media_utils, skills, vram

CATEGORY = "Llama Prompter/advanced"

LANGUAGES = ["English", "繁體中文", "简体中文", "日本語", "same as input", "auto"]

LANGUAGE_RULES = {
    "English": "Always write the final answer in English.",
    "繁體中文": "最終答案一律使用繁體中文。",
    "简体中文": "最终答案一律使用简体中文。",
    "日本語": "最終的な回答は必ず日本語で書いてください。",
    "same as input": "Write the final answer in the same language as the user's text input.",
    "auto": "",
}

DEFAULT_SYSTEM = (
    "You are a prompt engineer for image and video generation models. "
    "Read the user's text and any attached media, then reply with ONE prompt only. "
    "Do not add explanations, headings, labels, markdown or quotation marks."
)

MODEL_TYPES = ["T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"]

MODE_HINTS = {
    "T2VA": "text only; build the whole audiovisual timeline from the text.",
    "I2VA": "the [first_frame] image is the opening frame; develop forward from it.",
    "FL2VA": "the [first_frame] and [last_frame] images bracket the shot; describe the path between them.",
    "L2VA": "the [last_frame] image is the closing frame; infer an opening that converges to it.",
    "Ref2VA": "the labelled [reference] / [subject] images define recurring subjects; keep their labels consistent.",
}

BASE_FIELDS = ["integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"]
REF_FIELDS = [
    "subject_definitions", "summary", "retention_analysis",
    "detailed_description", "overall_soundscape", "non_diegetic_music",
]

ASPECT_RATIOS = [
    "Auto", "1:1", "5:4", "4:3", "3:2", "16:9", "2:1",
    "1:2", "9:16", "2:3", "3:4", "4:5", "CUSTOM",
]

RESOLUTIONS = [
    "Native (ShortEdge 768px)", "Native (ShortEdge 512px)",
    "Native (ShortEdge 1024px)", "720p", "1080p",
]


def fields_for(model_type):
    return list(REF_FIELDS if model_type == "Ref2VA" else BASE_FIELDS)


_ROUTE_SYSTEM = (
    "You route a request to the single best skill. "
    "Reply with a JSON object of the form {\"skill\": \"<name>\"} and nothing else. "
    "If no skill fits, reply {\"skill\": \"(none)\"}."
)


def _send_ui(node_id, event, payload):
    if not node_id:
        return
    try:
        from server import PromptServer  # type: ignore

        data = dict(payload)
        data["node"] = node_id
        PromptServer.instance.send_sync(event, data)
    except Exception:
        pass


def spec_block(spec):
    """Render the generation spec so a skill stops asking for it."""
    lines = ["[generation spec] (use these values, do not ask the user for them)"]
    for key in ("model_type", "duration_seconds", "aspect_ratio", "resolution",
                "fps", "audio"):
        value = (spec or {}).get(key)
        if value in (None, "", "Auto"):
            continue
        lines.append("%s: %s" % (key, value))
    notes = (spec or {}).get("notes", "").strip()
    if notes:
        lines.append("notes: " + notes)
    hint = MODE_HINTS.get((spec or {}).get("model_type", ""), "")
    if hint:
        lines.append("input mode: " + hint)
    return "\n".join(lines)


def fields_block(fields, as_json):
    names = ", ".join(fields)
    if as_json:
        return ("Reply with a JSON object containing exactly these keys, in this order: %s. "
                "Every value is a plain string. No markdown, no extra keys." % names)
    return ("Reply with exactly these sections, each on its own line as "
            "`field_name: value`, in this order and with no extra text: %s" % names)


def fields_schema(fields):
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in fields},
        "required": list(fields),
        "additionalProperties": False,
    }


def parse_fields(text, fields):
    """Pull ``{field: value}`` out of a JSON or ``label:`` style reply."""
    result = {name: "" for name in fields}
    body = (text or "").strip()
    if not body:
        return result

    fence = re.search(r"```(?:json)?\s*\n(.*?)\n?```", body, re.DOTALL)
    if fence:
        body = fence.group(1).strip()

    start = body.find("{")
    end = body.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(body[start:end + 1])
            if isinstance(data, dict):
                hit = False
                lowered = {str(k).strip().lower(): v for k, v in data.items()}
                for name in fields:
                    value = lowered.get(name.lower())
                    if isinstance(value, (list, tuple)):
                        value = "\n".join(str(v) for v in value)
                    if value not in (None, ""):
                        result[name] = str(value).strip()
                        hit = True
                if hit:
                    return result
        except ValueError:
            pass

    # Fall back to "field_name: value" blocks.  A block ends at the next
    # snake_case header, so asking for one field out of many still works, and
    # the optional quotes let truncated JSON degrade gracefully instead of
    # losing every field.
    wanted = "|".join(re.escape(f) for f in fields)
    generic = r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+"
    pattern = re.compile(
        r"^[ \t>*#{-]*[\"']?(%s|%s)[\"']?[ \t]*\**[ \t]*[:：][ \t]*" % (wanted, generic),
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(pattern.finditer(body))
    lowered = {name.lower(): name for name in fields}
    for index, match in enumerate(matches):
        name = lowered.get(match.group(1).lower())
        if not name:
            continue
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[match.end():stop].strip()
        chunk = chunk.strip("*").strip().rstrip(",").strip()
        if len(chunk) >= 2 and chunk[0] == chunk[-1] and chunk[0] in "\"'":
            chunk = chunk[1:-1]
        chunk = chunk.strip().lstrip('"').rstrip('"').strip()
        if chunk:
            result[name] = chunk
    return result


def _postprocess(text, strip_quotes=True, single_line=False, max_chars=0):
    out = (text or "").strip()
    # Drop a leading "Prompt:" style label the model sometimes adds.
    out = re.sub(r"^\s*(?:final\s+)?prompt\s*[:：]\s*", "", out, flags=re.IGNORECASE)
    # Unwrap fenced code blocks.
    fence = re.match(r"^```[a-zA-Z0-9_\-]*\s*\n(.*?)\n?```\s*$", out, re.DOTALL)
    if fence:
        out = fence.group(1).strip()
    if strip_quotes and len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'“”「『":
        out = out[1:-1].strip()
    if single_line:
        out = re.sub(r"\s*\n+\s*", " ", out).strip()
    if max_chars and max_chars > 0 and len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out


class LlamaPrompter:
    @classmethod
    def INPUT_TYPES(cls):
        cfg = config.load()
        return {
            "required": {
                "server": ("LLAMA_SERVER",),
                "text": ("STRING", {
                    "default": "", "multiline": True, "dynamicPrompts": False,
                    "tooltip": "你的需求或想法。第一行寫 /skill 名稱 可即時切換技能"
                               "（需把 skill 節點的 mode 設為 from_prompt）。",
                }),
                "output_language": (LANGUAGES, {"default": "English"}),
            },
            "optional": {
                "images": ("IMAGE", {"tooltip": "單張或一整批圖。"}),
                "images_b": ("IMAGE", {
                    "tooltip": "第二組影像。ComfyUI 的 IMAGE batch 必須同尺寸，"
                               "要比較兩張不同尺寸的圖就接這裡。",
                }),
                "image_slots": ("LLAMA_IMAGES", {
                    "tooltip": "帶角色標籤的影像（首幀 / 尾幀 / 參考圖）。",
                }),
                "video": ("VIDEO", {"tooltip": "ComfyUI 原生 VIDEO；會依 media_options 抽幀。"}),
                "audio": ("AUDIO", {"tooltip": "需模型支援音訊（例如 Qwen2-Audio / Ultravox）。"}),
                "spec": ("LLAMA_SPEC", {"tooltip": "秒數 / 比例 / 模式規格。"}),
                "params": ("LLAMA_PARAMS",),
                "media_options": ("LLAMA_MEDIA",),
                "skill": ("LLAMA_SKILL",),
                "system_prompt": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "覆寫系統提示。留空則用技能的系統提示。",
                }),
                "prefix": ("STRING", {"default": "", "multiline": False}),
                "suffix": ("STRING", {"default": "", "multiline": False}),
                "strip_thinking": ("BOOLEAN", {
                    "default": cfg["strip_thinking"],
                    "tooltip": "移除 <think> 推理區塊。",
                }),
                "strip_quotes": ("BOOLEAN", {"default": True}),
                "single_line": ("BOOLEAN", {"default": False}),
                "max_chars": ("INT", {"default": 0, "min": 0, "max": 20000}),
            },
            "hidden": {"node_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "raw_response", "info", "used_skill")
    OUTPUT_TOOLTIPS = (
        "整理後的提示詞，可直接接 CLIP Text Encode。",
        "模型原始輸出（含推理內容）。",
        "本次請求的統計資訊。",
        "實際使用的技能名稱。",
    )
    FUNCTION = "run"
    CATEGORY = CATEGORY
    DESCRIPTION = "把圖片 / 影片 / 音訊 / 文字送到 llama-server，產生生成用的 prompt。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        params = kwargs.get("params") or {}
        try:
            if int(params.get("seed", 0)) < 0:
                return float("nan")
        except Exception:
            pass
        selector = kwargs.get("skill") or {}
        if selector.get("mode") == "auto":
            return float("nan")
        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_items(items, log):
        """Turn selector items into skill dicts, keeping the chain order."""
        resolved = []
        for item in items or []:
            name = item.get("name") if isinstance(item, dict) else item
            skill = skills.get_skill(name)
            if not skill:
                if name not in (skills.NONE_SKILL, "", None):
                    log.append("找不到技能 '%s'。" % name)
                continue
            skill = dict(skill)
            skill["include_references"] = bool(
                item.get("include_references") if isinstance(item, dict) else False
            )
            resolved.append(skill)
        return resolved

    def _resolve_skill(self, selector, text, client, model, media_summary, log):
        """Return ``(ordered_skills, cleaned_text, display_name)``."""
        selector = selector or {}
        mode = selector.get("mode", "manual")
        cleaned = text or ""

        items = selector.get("items")
        if items is None and selector.get("name"):
            items = [{"name": selector["name"],
                      "include_references": selector.get("include_references", False)}]

        if mode == "off":
            return [], cleaned, skills.NONE_SKILL

        if mode == "from_prompt":
            directives, cleaned = skills.extract_directives(cleaned)
            if directives:
                # An explicit list in the prompt replaces the whole chain.
                picked = self._resolve_items(
                    [{"name": n, "include_references": False} for n in directives], log
                )
                if picked:
                    return picked, cleaned, self._display(picked)
                log.append("prompt 指定的技能都不存在，改用節點上的設定。")

        resolved = self._resolve_items(items, log)

        if mode == "auto":
            picked = self._auto_pick(client, model, cleaned, media_summary, log)
            if picked and all(picked["path"] != s["path"] for s in resolved):
                picked = dict(picked)
                picked["include_references"] = False
                resolved.append(picked)

        return resolved, cleaned, self._display(resolved)

    @staticmethod
    def _display(resolved):
        return " + ".join(s["path"] for s in resolved) or skills.NONE_SKILL

    def _auto_pick(self, client, model, text, media_summary, log):
        catalog = skills.catalog_text()
        if not catalog.strip():
            return None
        question = (
            "Available skills:\n%s\n\nUser request: %s\nAttached media: %s"
            % (catalog, text or "(no text)", media_summary or "none")
        )
        try:
            reply = client.chat(
                [
                    {"role": "system", "content": _ROUTE_SYSTEM},
                    {"role": "user", "content": question},
                ],
                params={"temperature": 0.0, "max_tokens": 64},
                model=model,
                stream=False,
            )
            picked = self._parse_route(reply.get("content", ""))
        except Exception as exc:
            log.append("自動路由失敗（%s），只用手動選擇的技能。" % exc)
            return None
        if not picked:
            return None
        resolved = skills.get_skill(picked)
        if resolved:
            log.append("自動追加技能：%s" % resolved["path"])
            return resolved
        log.append("模型選了不存在的技能 '%s'。" % picked)
        return None

    @staticmethod
    def _parse_route(text):
        text = (text or "").strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                value = str(data.get("skill", "")).strip()
                return value if value and value != skills.NONE_SKILL else None
            except ValueError:
                pass
        token = re.search(r"[A-Za-z0-9_\-.]+", text)
        return token.group(0) if token else None

    # ------------------------------------------------------------------
    def run(self, **kwargs):
        outcome = self._execute(**kwargs)
        return {
            "ui": {"text": [outcome["prompt"]]},
            "result": (outcome["prompt"], outcome["raw_full"], outcome["info"],
                       outcome["used_skill"]),
        }

    def _execute(self, server, text, output_language="English", images=None, images_b=None,
                 video=None, audio=None, params=None, media_options=None, skill=None,
                 system_prompt="", prefix="", suffix="", strip_thinking=True,
                 strip_quotes=True, single_line=False, max_chars=0, node_id=None,
                 image_slots=None, spec=None, fields=None, force_json=False,
                 extra_parts=None, system_prefix=""):

        started = time.time()
        log = []
        cfg = config.load()
        server = server or {}

        client = llama_client.LlamaClient(
            base_url=server.get("base_url") or cfg["base_url"],
            api_key=server.get("api_key", ""),
            timeout=server.get("timeout", cfg["timeout"]),
            verify_ssl=server.get("verify_ssl", True),
            debug=server.get("debug", False),
        )
        model = server.get("model") or cfg.get("model") or None

        if server.get("free_comfy_vram"):
            log.append(vram.free_comfy())

        # --- media ------------------------------------------------------
        opts = dict(media_options or {
            "max_frames": cfg["max_frames"],
            "frame_sample": "uniform",
            "every_n": 1,
            "max_image_side": cfg["max_image_side"],
            "image_format": cfg["image_format"],
            "jpeg_quality": cfg["jpeg_quality"],
            "max_audio_seconds": 60.0,
        })
        image_inputs = [batch for batch in (images, images_b) if batch is not None]
        media_parts, summary = media_utils.build_media_parts(
            image_inputs or None, video, audio, opts, slots=image_slots
        )
        media_summary = media_utils.describe_media(summary)

        # --- skills (an ordered chain) ----------------------------------
        chain, cleaned_text, used_skill = self._resolve_skill(
            skill, text, client, model, media_summary, log
        )
        merged = skills.compose(chain)
        resolved_skill = merged if chain else None

        # --- sampling parameters ---------------------------------------
        request_params = dict(params or {
            "temperature": cfg["temperature"],
            "top_p": cfg["top_p"],
            "top_k": cfg["top_k"],
            "min_p": cfg["min_p"],
            "max_tokens": cfg["max_tokens"],
            "repeat_penalty": cfg["repeat_penalty"],
            "seed": 0,
        })
        keep_alive = int(server.get("keep_alive", -1))
        if keep_alive >= 0:
            request_params["keep_alive"] = keep_alive

        if resolved_skill and (skill or {}).get("apply_defaults", True):
            # The toggle is explicit, so a skill's own defaults win over the
            # sampling node.  Turn it off to keep full manual control.
            for key, value in (resolved_skill.get("defaults") or {}).items():
                request_params[key] = value

        # --- system prompt ---------------------------------------------
        system_parts = []
        prefix = (system_prefix or "").strip()
        if prefix:
            # Sits in front of the skills rather than replacing them.
            system_parts.append(prefix)

        override = (system_prompt or "").strip()
        if override:
            system_parts.append(override)
        elif resolved_skill and resolved_skill.get("system"):
            system_parts.append(resolved_skill["system"])
        else:
            system_parts.append(DEFAULT_SYSTEM)

        for item in chain:
            if not item.get("include_references"):
                continue
            references = skills.load_references(item)
            if references:
                system_parts.append(references)
                log.append("%s 附加了 %d 個 reference 檔案（%d 字元）"
                           % (item["path"], len(item.get("ref_files") or []),
                              len(references)))

        extra = (skill or {}).get("extra_instructions", "")
        if extra:
            system_parts.append(extra)

        # The language rule is appended to the user message instead of the
        # system prompt: buried under a long skill it simply gets ignored.
        language_rule = LANGUAGE_RULES.get(output_language, "")

        # --- user message ------------------------------------------------
        user_text = skills.render_user_template(resolved_skill, cleaned_text, media_summary)
        if not user_text.strip() and media_parts:
            user_text = "Describe the attached media and produce the prompt."
        if media_summary:
            user_text = user_text + "\n\n[attached: %s]" % media_summary

        if spec:
            user_text = user_text + "\n\n" + spec_block(spec)

        if fields:
            user_text = user_text + "\n\n" + fields_block(fields, force_json)
            if force_json:
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "prompt_fields", "schema": fields_schema(fields)},
                }
                # A schema-constrained answer must not be cut off half way.
                request_params["max_tokens"] = max(
                    int(request_params.get("max_tokens", 512)), 400 * len(fields)
                )

        if language_rule:
            if fields:
                language_rule += (" This applies to EVERY field value. "
                                  "Keep the field names themselves in English, "
                                  "exactly as listed.")
            # Stated twice on purpose: one mention gets drowned out by a long
            # English skill such as h3-prompt-writing.
            system_parts.append(language_rule)
            user_text = user_text + "\n\n" + language_rule

        content = list(media_parts) + list(extra_parts or [])
        content.append({"type": "text", "text": user_text})

        messages = [
            {"role": "system", "content": "\n\n".join(p for p in system_parts if p)},
            {"role": "user", "content": content},
        ]

        # --- request ------------------------------------------------------
        target_node = node_id or None
        stream = bool(server.get("stream", cfg["stream"]))
        buffer = {"text": "", "stamp": 0.0}

        def on_delta(piece):
            buffer["text"] += piece
            now = time.time()
            if now - buffer["stamp"] > 0.15:
                buffer["stamp"] = now
                _send_ui(target_node, "llama_prompter.stream", {"text": buffer["text"]})

        try:
            reply = client.chat(
                messages, params=request_params, model=model,
                stream=stream, on_delta=on_delta if stream else None,
            )
        except llama_client.LlamaError as exc:
            message = str(exc)
            _send_ui(target_node, "llama_prompter.stream", {"text": "[error] " + message})
            raise RuntimeError(
                "llama-server 請求失敗：%s\n檢查位址 %s 是否可連線、模型是否已載入。"
                % (message, client.base_url)
            )

        raw = reply.get("content", "") or ""
        reasoning = reply.get("reasoning", "") or ""
        cleaned = llama_client.strip_thinking(raw) if strip_thinking else raw
        prompt = _postprocess(cleaned, strip_quotes, single_line, max_chars)

        if prefix.strip():
            prompt = prefix.strip() + " " + prompt
        if suffix.strip():
            prompt = prompt + " " + suffix.strip()
        prompt = prompt.strip()

        usage = reply.get("usage") or {}
        elapsed = time.time() - started
        info_lines = [
            "server: %s" % client.base_url,
            "model: %s" % (model or "(server default)"),
            "skill: %s" % (used_skill or skills.NONE_SKILL),
            "media: %s" % (media_summary or "none"),
            "payload: %.1f KB" % (summary["payload_bytes"] / 1024.0),
            "tokens: prompt=%s completion=%s" % (
                usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?")),
            "finish: %s" % reply.get("finish_reason"),
            "elapsed: %.2fs" % elapsed,
        ]
        if summary.get("frame_indices"):
            info_lines.append("frames: %s" % summary["frame_indices"])
        info_lines.extend(log)
        info = "\n".join(str(line) for line in info_lines)

        raw_full = raw if not reasoning else ("<reasoning>\n%s\n</reasoning>\n%s" % (reasoning, raw))

        if keep_alive == 0:
            info = info + "\n" + vram.release_server(client)

        _send_ui(target_node, "llama_prompter.done", {"text": prompt, "info": info})
        if config.get("debug"):
            print("[LlamaPrompter]\n" + info)

        return {
            "prompt": prompt,
            "cleaned": cleaned,
            "raw_full": raw_full,
            "info": info,
            "used_skill": used_skill or "",
        }


class LlamaVideoPrompter(LlamaPrompter):
    """Same request, but split into the named fields an H3-style prompt needs."""

    @classmethod
    def INPUT_TYPES(cls):
        spec = LlamaPrompter.INPUT_TYPES()
        spec["required"]["spec"] = ("LLAMA_SPEC",)
        spec["optional"].pop("spec", None)
        spec["optional"].pop("single_line", None)
        spec["optional"].pop("max_chars", None)
        spec["optional"]["force_json"] = ("BOOLEAN", {
            "default": True,
            "tooltip": "用 JSON schema 強制模型填滿所有欄位。"
                       "關掉的話改用 `欄位名: 內容` 解析，較寬鬆但也較容易缺欄位。",
        })
        spec["optional"]["extra_fields"] = ("STRING", {
            "default": "", "multiline": False,
            "tooltip": "額外欄位名稱，以逗號分隔。會接在標準欄位後面。",
        })
        return spec

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
        "所有欄位合併成一段文字。",
        "Ref2VA：參考主體定義。其他模式為空。",
        "Ref2VA：摘要。其他模式為空。",
        "Ref2VA：保留分析。其他模式為空。",
        "主描述。Ref2VA 給 detailed_description，"
        "其他模式給 integrated_multimodal_description，接線不用跟著模式換。",
        "環境音描述。",
        "配樂描述。",
        "本次請求的統計資訊。",
    )
    FUNCTION = "run_video"
    CATEGORY = CATEGORY
    DESCRIPTION = "產生分欄位的影片提示詞（T2VA / I2VA / FL2VA / L2VA / Ref2VA）。"

    def run_video(self, spec, force_json=True, extra_fields="", **kwargs):
        model_type = (spec or {}).get("model_type", "T2VA")
        fields = fields_for(model_type)
        for name in (extra_fields or "").split(","):
            name = name.strip()
            if name and name not in fields:
                fields.append(name)

        outcome = self._execute(spec=spec, fields=fields, force_json=bool(force_json),
                                **kwargs)
        values = parse_fields(outcome["cleaned"], fields)

        missing = [name for name in fields if not values.get(name)]
        info = outcome["info"] + "\nmode: %s | fields: %s" % (model_type, ", ".join(fields))
        if missing:
            info += "\nmissing fields: " + ", ".join(missing)
            if "finish: length" in outcome["info"]:
                info += "\n回應被 max_tokens 截斷，請調高取樣參數的 max_tokens。"

        full = "\n\n".join(
            "%s: %s" % (name, values[name]) for name in fields if values.get(name)
        ) or outcome["prompt"]

        # One "description" line so downstream wiring survives a mode change.
        description = (values.get("detailed_description")
                       or values.get("integrated_multimodal_description", ""))

        ordered = (
            full,
            values.get("subject_definitions", ""),
            values.get("summary", ""),
            values.get("retention_analysis", ""),
            description,
            values.get("overall_soundscape", ""),
            values.get("non_diegetic_music", ""),
            info,
        )
        return {"ui": {"text": [full]}, "result": ordered}
