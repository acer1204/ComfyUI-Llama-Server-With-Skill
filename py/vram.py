"""VRAM juggling helpers for machines that cannot hold ComfyUI and the LLM at once.

Plain ``llama-server`` has no endpoint that unloads its model, so there are only
two things that actually help:

* free ComfyUI's own models before the request, so llama.cpp has room; and
* ask the llama side to release, which works when llama-server sits behind a
  swapper such as llama-swap, or when the endpoint is an Ollama-style server.

Both report honestly what happened instead of pretending memory was freed.
"""

UNLOAD_ENDPOINTS = [
    "/unload",                      # llama-swap
    "/api/unload",
    "/v1/internal/model/unload",    # text-generation-webui
    "/v1/models/unload",
]


def free_comfy(aggressive=True):
    """Unload ComfyUI's models from VRAM.  Returns a status line."""
    try:
        import comfy.model_management as mm  # type: ignore
    except ImportError:
        return "vram: ComfyUI not present, nothing to free"

    try:
        mm.unload_all_models()
        if aggressive:
            free_memory = getattr(mm, "free_memory", None)
            if callable(free_memory):
                try:
                    free_memory(1e30, mm.get_torch_device())
                except Exception:
                    pass
            mm.soft_empty_cache(True)
        return "vram: ComfyUI models unloaded before the request"
    except Exception as exc:
        return "vram: could not unload ComfyUI models (%s)" % exc


def release_server(client):
    """Ask the llama endpoint to drop its model.  Returns a status line."""
    for path in UNLOAD_ENDPOINTS:
        try:
            client._request_json(path, method="POST", body={}, timeout=20)
            return "vram: llama endpoint released the model via %s" % path
        except Exception:
            continue

    # Ollama-compatible servers unload when asked for a zero keep-alive.
    try:
        client._request_json(
            "/api/generate", method="POST",
            body={"model": "", "keep_alive": 0}, timeout=20,
        )
        return "vram: llama endpoint released the model via keep_alive=0"
    except Exception:
        pass

    return ("vram: this server has no unload endpoint "
            "(plain llama-server keeps the model resident; "
            "use llama-swap or restart it to free VRAM)")
