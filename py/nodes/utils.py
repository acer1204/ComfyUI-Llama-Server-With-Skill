"""Small helper nodes."""

CATEGORY = "Llama Prompter/advanced"


class LlamaPreviewText:
    """Display a STRING on the canvas (handy for checking the generated prompt)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "show"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY
    DESCRIPTION = "在畫布上顯示文字，同時原樣往下傳。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def show(self, text):
        value = text if isinstance(text, str) else str(text)
        return {"ui": {"text": [value]}, "result": (value,)}


class LlamaSectionGet:
    """Pull one named field out of a structured reply (JSON or ``name: value``)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
                "field_name": ("STRING", {
                    "default": "overall_soundscape",
                    "tooltip": "要取出的欄位名稱。",
                }),
            },
            "optional": {
                "fallback": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "找不到欄位時輸出這個。",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("value", "found")
    FUNCTION = "extract"
    CATEGORY = CATEGORY
    DESCRIPTION = "從結構化輸出中取出指定欄位，支援 JSON 與『欄位名: 內容』兩種格式。"

    def extract(self, text, field_name, fallback=""):
        from .prompter import parse_fields

        name = (field_name or "").strip()
        if not name:
            return (fallback, False)
        values = parse_fields(text, [name])
        value = values.get(name, "")
        if value:
            return (value, True)
        return (fallback, False)


class LlamaTestConnection:
    """Ping the server and report what it is running."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"server": ("LLAMA_SERVER",)}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report",)
    FUNCTION = "test"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY
    DESCRIPTION = "測試 llama-server 連線並回報模型 / context 長度 / 多模態能力。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def test(self, server):
        from .. import llama_client

        client = llama_client.LlamaClient(
            base_url=server.get("base_url"),
            api_key=server.get("api_key", ""),
            timeout=min(int(server.get("timeout", 60)), 60),
            verify_ssl=server.get("verify_ssl", True),
        )
        info = client.info()
        lines = [
            "base_url : %s" % info["base_url"],
            "reachable: %s" % ("yes" if info["ok"] else "NO"),
            "models   : %s" % (", ".join(info["models"]) or "(none reported)"),
            "model    : %s" % (info["model_path"] or "(unknown)"),
            "n_ctx    : %s" % (info["n_ctx"] or "(unknown)"),
            "multimodal: %s" % ("yes" if info["multimodal"] else "unknown/no"),
        ]
        if not info["ok"]:
            lines.append("error    : %s" % info["health"].get("error", ""))
        report = "\n".join(lines)
        return {"ui": {"text": [report]}, "result": (report,)}
