"""Node registry for ComfyUI-Llama-Server-With-Skill."""

from .connection import (
    LlamaServer,
    LlamaParams,
    LlamaMediaOptions,
    LlamaSkillNode,
    LlamaSkillList,
    LlamaVideoSpec,
    LlamaImageSlot,
)
from .prompter import LlamaPrompter, LlamaVideoPrompter
from .utils import LlamaPreviewText, LlamaTestConnection, LlamaSectionGet

NODE_CLASS_MAPPINGS = {
    "LlamaServer": LlamaServer,
    "LlamaParams": LlamaParams,
    "LlamaMediaOptions": LlamaMediaOptions,
    "LlamaSkill": LlamaSkillNode,
    "LlamaSkillList": LlamaSkillList,
    "LlamaVideoSpec": LlamaVideoSpec,
    "LlamaImageSlot": LlamaImageSlot,
    "LlamaPrompter": LlamaPrompter,
    "LlamaVideoPrompter": LlamaVideoPrompter,
    "LlamaSectionGet": LlamaSectionGet,
    "LlamaPreviewText": LlamaPreviewText,
    "LlamaTestConnection": LlamaTestConnection,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LlamaServer": "Llama Server 連線",
    "LlamaParams": "Llama 取樣參數",
    "LlamaMediaOptions": "Llama 影像/影片選項",
    "LlamaSkill": "Llama Skill",
    "LlamaSkillList": "Llama Skill 清單",
    "LlamaVideoSpec": "Llama 影片規格 (秒數/比例/模式)",
    "LlamaImageSlot": "Llama 影像插槽 (角色標記)",
    "LlamaPrompter": "Llama Prompter (圖/影片/文字 → Prompt)",
    "LlamaVideoPrompter": "Llama 影片 Prompter (分欄位輸出)",
    "LlamaSectionGet": "Llama 取出欄位",
    "LlamaPreviewText": "Llama 文字預覽",
    "LlamaTestConnection": "Llama 連線測試",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
