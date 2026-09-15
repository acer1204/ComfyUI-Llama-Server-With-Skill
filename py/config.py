"""Global configuration storage for ComfyUI-LlamaPrompter.

Settings live in ``<ComfyUI>/user/default/llama_prompter/config.json`` so they
survive updates of the custom node itself.  The ComfyUI settings panel (see
``js/llama_prompter.js``) writes to the same file through the HTTP routes in
``py/routes.py``.
"""

import json
import os
import threading

_LOCK = threading.RLock()
_CACHE = None
_CACHE_MTIME = None

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTIN_SKILL_DIR = os.path.join(PACKAGE_ROOT, "skills")

DEFAULT_CONFIG = {
    # --- llama-server connection -------------------------------------------
    "base_url": "https://g00392.asuscomm.com:10011",
    "api_key": "",
    "model": "",
    "timeout": 300,
    "verify_ssl": True,
    # --- default sampling parameters ---------------------------------------
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "min_p": 0.05,
    "max_tokens": 512,
    "repeat_penalty": 1.1,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
    # --- media defaults -----------------------------------------------------
    "max_frames": 8,
    "max_image_side": 768,
    "image_format": "jpeg",
    "jpeg_quality": 85,
    # --- behaviour ----------------------------------------------------------
    "stream": True,
    "strip_thinking": True,
    "default_skill": "(none)",
    "extra_skill_dirs": [],
    "debug": False,
}


def _comfy_user_dir():
    try:
        import folder_paths  # type: ignore

        get_user_directory = getattr(folder_paths, "get_user_directory", None)
        if callable(get_user_directory):
            return get_user_directory()
        return os.path.join(folder_paths.base_path, "user")
    except Exception:
        # Running outside ComfyUI (tests / linting) - keep everything local.
        return os.path.join(PACKAGE_ROOT, ".local_user")


def data_dir():
    path = os.path.join(_comfy_user_dir(), "llama_prompter")
    os.makedirs(path, exist_ok=True)
    return path


def user_skill_dir():
    path = os.path.join(data_dir(), "skills")
    os.makedirs(path, exist_ok=True)
    return path


def config_path():
    return os.path.join(data_dir(), "config.json")


def load(force=False):
    """Return the merged config dict (defaults + on-disk overrides)."""
    global _CACHE, _CACHE_MTIME
    path = config_path()
    with _LOCK:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if not force and _CACHE is not None and mtime == _CACHE_MTIME:
            return dict(_CACHE)

        cfg = dict(DEFAULT_CONFIG)
        if mtime is not None:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    stored = json.load(fh)
                if isinstance(stored, dict):
                    for key, value in stored.items():
                        if key in DEFAULT_CONFIG:
                            cfg[key] = value
            except Exception as exc:  # pragma: no cover - corrupt file
                print(f"[LlamaPrompter] failed to read config.json: {exc}")

        _CACHE = dict(cfg)
        _CACHE_MTIME = mtime
        return dict(cfg)


def get(key, fallback=None):
    cfg = load()
    if key in cfg:
        return cfg[key]
    return fallback if fallback is not None else DEFAULT_CONFIG.get(key)


def save(updates):
    """Merge ``updates`` into the stored config and return the new config."""
    global _CACHE, _CACHE_MTIME
    with _LOCK:
        cfg = load(force=True)
        for key, value in (updates or {}).items():
            if key in DEFAULT_CONFIG:
                cfg[key] = value
        path = config_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        _CACHE = None
        _CACHE_MTIME = None
        return load(force=True)


def skill_search_paths():
    """All directories scanned for skills, highest priority last."""
    paths = [BUILTIN_SKILL_DIR, user_skill_dir()]
    for extra in get("extra_skill_dirs") or []:
        extra = str(extra).strip()
        if extra and os.path.isdir(extra):
            paths.append(os.path.abspath(extra))
    seen = []
    for path in paths:
        if path not in seen:
            seen.append(path)
    return seen
