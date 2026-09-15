"""ComfyUI-LlamaPrompter

Send images, video frames, audio and text to a llama.cpp ``llama-server`` and
get a generation prompt back.  Skills (Markdown system-prompt packs) can be
imported from the ComfyUI settings panel or switched from inside the prompt.
"""

from .py.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__version__ = "1.0.0"

WEB_DIRECTORY = "./js"

try:
    from .py import routes

    routes.register()
except Exception as _exc:  # pragma: no cover - ComfyUI not fully booted
    print("[LlamaPrompter] could not register HTTP routes: %s" % _exc)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

print("[LlamaPrompter] loaded %d nodes" % len(NODE_CLASS_MAPPINGS))
