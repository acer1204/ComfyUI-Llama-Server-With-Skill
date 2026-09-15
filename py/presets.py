"""Reusable system prompts, managed from the ComfyUI settings panel.

These are deliberately simpler than skills: a name and a block of text, no
front matter, no templates, no references.  The AIO node lists them in a combo
so a house style can be picked without wiring anything up.
"""

from . import config

NONE = "(skill default)"

BUILTIN = [
    {
        "name": "prompt-engineer",
        "text": (
            "You are a prompt engineer for image and video generation models. "
            "Read the user's text and any attached media, then reply with the "
            "prompt only. No explanations, headings, labels or quotation marks."
        ),
    },
    {
        "name": "literal-describer",
        "text": (
            "Describe only what is actually present in the attached media. "
            "Never infer intent, mood, brand or backstory. If something is not "
            "visible, do not mention it."
        ),
    },
    {
        "name": "concise",
        "text": (
            "Be concise. Prefer concrete nouns and verbs over adjectives. "
            "Never pad the answer to reach a length."
        ),
    },
]


def _stored():
    items = config.get("system_prompts") or []
    clean = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        text = str(item.get("text") or "").strip()
        if name and text:
            clean.append({"name": name, "text": text})
    return clean


def all_presets():
    """Built-ins first, then user presets; a user preset may shadow a built-in."""
    merged = {item["name"]: dict(item, builtin=True) for item in BUILTIN}
    for item in _stored():
        merged[item["name"]] = dict(item, builtin=False)
    return [merged[name] for name in sorted(merged, key=str.lower)]


def names(include_none=True):
    listed = [item["name"] for item in all_presets()]
    return ([NONE] + listed) if include_none else listed


def get(name):
    if not name or name == NONE:
        return ""
    wanted = str(name).strip().lower()
    for item in all_presets():
        if item["name"].lower() == wanted:
            return item["text"]
    return ""


def save(name, text):
    name = str(name or "").strip()
    text = str(text or "").strip()
    if not name:
        raise ValueError("preset needs a name")
    if not text:
        raise ValueError("preset needs some text")
    items = [item for item in _stored() if item["name"].lower() != name.lower()]
    items.append({"name": name, "text": text})
    items.sort(key=lambda item: item["name"].lower())
    config.save({"system_prompts": items})
    return items


def delete(name):
    wanted = str(name or "").strip().lower()
    items = [item for item in _stored() if item["name"].lower() != wanted]
    config.save({"system_prompts": items})
    return items
