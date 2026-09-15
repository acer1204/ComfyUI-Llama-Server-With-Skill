"""Skill discovery, parsing and prompt-driven switching.

A *skill* is a Markdown file with YAML front matter, following the widely used
``SKILL.md`` convention.  Two layouts are accepted::

    skills/flux-prompt.md
    skills/flux-prompt/SKILL.md      # allows bundling extra resources

Front matter keys (all optional except ``name``)::

    ---
    name: flux-prompt
    description: Turn an idea or image into a FLUX.1 natural-language prompt.
    version: 1.0.0
    tags: [t2i, flux]
    media: [text, image]          # which inputs the skill expects
    resources: [examples.md]      # extra files appended to the system prompt
    defaults:                     # sampling overrides applied by the node
      temperature: 0.6
      max_tokens: 400
    ---

    <everything below is the system prompt>

Optional ``## SYSTEM`` / ``## USER`` headings split the body into a system
prompt and a user-message template.  The template understands the placeholders
``{{text}}`` (the node's text input), ``{{media}}`` (a short description of the
attached media) and ``{{skill}}``.
"""

import os
import re
import time

from . import config

_FRONT_MATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s*(SYSTEM|USER)\s*$", re.IGNORECASE | re.MULTILINE)
_LANG_VARIANT_RE = re.compile(r"^SKILL\.([A-Za-z]{2}(?:-[A-Za-z]{2,4})?)\.(?:md|markdown)$", re.IGNORECASE)

NONE_SKILL = "(none)"

_CACHE = {"stamp": 0.0, "skills": {}}
_CACHE_TTL = 2.0


# ---------------------------------------------------------------------------
# front matter parsing
# ---------------------------------------------------------------------------
def _parse_scalar(raw):
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] in "\"'" and raw[-1] == raw[0] and len(raw) >= 2:
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in inner.split(",")]
    low = raw.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d*\.\d+([eE][-+]?\d+)?", raw):
        return float(raw)
    return raw


def _parse_front_matter(block):
    """Minimal YAML subset parser (uses PyYAML when it is installed)."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    data = {}
    current_key = None
    current_list = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if stripped.startswith("- ") and current_key is not None:
            if current_list is None:
                current_list = []
                data[current_key] = current_list
            current_list.append(_parse_scalar(stripped[2:]))
            continue

        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()

        if indent > 0 and current_key is not None and isinstance(data.get(current_key), dict):
            data[current_key][key] = _parse_scalar(value)
            continue

        current_list = None
        if value == "":
            data[key] = {}
            current_key = key
        else:
            data[key] = _parse_scalar(value)
            current_key = key
    return data


def _split_body(body):
    """Return ``(system_prompt, user_template)`` from the markdown body."""
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return body.strip(), ""

    system_parts = []
    user_parts = []
    preamble = body[: matches[0].start()].strip()
    if preamble:
        system_parts.append(preamble)

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[match.end():end].strip()
        if match.group(1).upper() == "SYSTEM":
            system_parts.append(chunk)
        else:
            user_parts.append(chunk)
    return "\n\n".join(p for p in system_parts if p), "\n\n".join(p for p in user_parts if p)


def parse_skill_text(text, name_hint="", source=""):
    meta = {}
    body = text
    match = _FRONT_MATTER_RE.match(text)
    if match:
        meta = _parse_front_matter(match.group(1)) or {}
        body = text[match.end():]

    system, user_template = _split_body(body)
    name = str(meta.get("name") or name_hint or "unnamed").strip()
    defaults = meta.get("defaults")
    if not isinstance(defaults, dict):
        defaults = {}

    media = meta.get("media")
    if isinstance(media, str):
        media = [media]
    elif not isinstance(media, list):
        media = []

    tags = meta.get("tags")
    if isinstance(tags, str):
        tags = [tags]
    elif not isinstance(tags, list):
        tags = []

    resources = meta.get("resources")
    if isinstance(resources, str):
        resources = [resources]
    elif not isinstance(resources, list):
        resources = []

    is_builtin = False
    if source:
        try:
            is_builtin = os.path.abspath(source).startswith(
                os.path.abspath(config.BUILTIN_SKILL_DIR)
            )
        except Exception:
            is_builtin = False

    return {
        "name": name,
        "description": str(meta.get("description") or "").strip(),
        "version": str(meta.get("version") or "").strip(),
        "tags": [str(t) for t in tags],
        "media": [str(m).lower() for m in media],
        "defaults": defaults,
        "resources": [str(r) for r in resources],
        "system": system.strip(),
        "user_template": user_template.strip(),
        "source": source,
        "builtin": is_builtin,
        "language": "",
        "ref_files": [],
        "group": str(meta.get("group") or "").strip(),
        "path": name,
    }


def _load_skill_file(path, name_hint):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception as exc:
        print("[LlamaPrompter] cannot read skill %s: %s" % (path, exc))
        return None

    skill = parse_skill_text(text, name_hint=name_hint, source=path)

    # Append bundled resources (relative to the skill's own folder).
    base = os.path.dirname(path)
    extra = []
    for resource in skill["resources"]:
        resource_path = os.path.join(base, resource)
        if os.path.isfile(resource_path):
            try:
                with open(resource_path, "r", encoding="utf-8") as fh:
                    extra.append("\n\n<!-- %s -->\n" % resource + fh.read().strip())
            except Exception:
                continue
    if extra:
        skill["system"] = skill["system"] + "".join(extra)

    # SKILL.md packs keep supporting material in a references/ folder.
    skill["ref_files"] = []
    ref_dir = os.path.join(base, "references")
    if os.path.isdir(ref_dir):
        for name in sorted(os.listdir(ref_dir)):
            if name.lower().endswith((".md", ".markdown", ".txt", ".json", ".yaml", ".yml")):
                skill["ref_files"].append(os.path.join(ref_dir, name))
    return skill


def load_references(skill, max_chars=120000):
    """Concatenate a skill's references/ folder (used by include_references)."""
    chunks = []
    total = 0
    for path in (skill or {}).get("ref_files") or []:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read().strip()
        except Exception:
            continue
        if not text:
            continue
        header = "\n\n===== reference: %s =====\n" % os.path.basename(path)
        if total + len(text) + len(header) > max_chars:
            remaining = max(0, max_chars - total - len(header))
            if remaining < 200:
                break
            text = text[:remaining] + "\n[...truncated...]"
        chunks.append(header + text)
        total += len(text) + len(header)
    return "".join(chunks)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------
def discover(force=False):
    """Return ``{name: skill_dict}`` for every skill on disk."""
    now = time.time()
    if not force and (now - _CACHE["stamp"]) < _CACHE_TTL and _CACHE["skills"]:
        return dict(_CACHE["skills"])

    found = {}
    for directory in config.skill_search_paths():
        if not os.path.isdir(directory):
            continue
        _scan(directory, _base_group(directory), found, depth=0)

    _CACHE["skills"] = found
    _CACHE["stamp"] = now
    return dict(found)


def _base_group(directory):
    """Group label for loose skills sitting directly in a search path."""
    directory = os.path.abspath(directory)
    if directory == os.path.abspath(config.BUILTIN_SKILL_DIR):
        return "core"
    if directory == os.path.abspath(config.user_skill_dir()):
        return "user"
    return safe_slug(os.path.basename(directory.rstrip(os.sep))) or "extra"


def _pack_entry(directory, name):
    """Return the main SKILL.md of a skill folder, or None if it is a group."""
    for candidate in ("SKILL.md", "skill.md", name + ".md"):
        path = os.path.join(directory, candidate)
        if os.path.isfile(path):
            return path
    return None


def _register(found, skill, group):
    skill["group"] = group
    skill["path"] = ("%s/%s" % (group, skill["name"])) if group else skill["name"]
    found[skill["path"]] = skill


def _scan(directory, group, found, depth):
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return

    for entry in entries:
        full = os.path.join(directory, entry)

        if os.path.isdir(full):
            main = _pack_entry(full, entry)
            if main is None:
                # Not a skill pack, so treat it as a group folder.
                if depth < 3:
                    child = entry if depth == 0 else "%s/%s" % (group, entry)
                    _scan(full, safe_group(child), found, depth + 1)
                continue

            skill = _load_skill_file(main, entry)
            if skill:
                _register(found, skill, skill.get("group") or group)

            # Localised variants, e.g. SKILL.cn.md -> "<name>-cn".
            for fname in sorted(os.listdir(full)):
                match = _LANG_VARIANT_RE.match(fname)
                if not match:
                    continue
                variant = _load_skill_file(os.path.join(full, fname), entry)
                if not variant:
                    continue
                variant["language"] = match.group(1).lower()
                variant["name"] = "%s-%s" % (variant["name"], variant["language"])
                _register(found, variant, variant.get("group") or group)

        elif entry.lower().endswith((".md", ".markdown")):
            skill = _load_skill_file(full, os.path.splitext(entry)[0])
            if skill:
                _register(found, skill, skill.get("group") or group)


def safe_group(group):
    parts = [safe_slug(p) for p in str(group or "").split("/") if p.strip()]
    return "/".join(p for p in parts if p)


def invalidate():
    _CACHE["stamp"] = 0.0
    _CACHE["skills"] = {}


def list_names(include_none=True):
    """Dropdown entries, as ``group/name`` sorted by group then name."""
    skills = discover()
    names = sorted(skills.keys(), key=lambda p: (p.count("/") == 0, p.lower()))
    return ([NONE_SKILL] + names) if include_none else names


def get_skill(name):
    """Resolve by ``group/name``, by bare name, or case-insensitively."""
    if not name or name == NONE_SKILL:
        return None
    wanted = str(name).strip().strip("/")
    skills = discover()
    if wanted in skills:
        return skills[wanted]

    by_path = {path.lower(): skill for path, skill in skills.items()}
    if wanted.lower() in by_path:
        return by_path[wanted.lower()]

    # Bare name: unique match wins, otherwise the first in group order.
    matches = [skill for path, skill in sorted(skills.items())
               if skill["name"].lower() == wanted.lower()]
    if matches:
        return matches[0]

    # Last resort: a unique suffix match, so "h3/h3-prompt-writing" style
    # abbreviations still resolve.
    suffix = [skill for path, skill in sorted(skills.items())
              if path.lower().endswith("/" + wanted.lower())]
    return suffix[0] if suffix else None


def groups():
    """``{group: [skill, ...]}`` for the settings UI."""
    buckets = {}
    for skill in discover().values():
        buckets.setdefault(skill.get("group") or "", []).append(skill)
    for items in buckets.values():
        items.sort(key=lambda s: s["name"].lower())
    return buckets


def catalog_text(max_items=80):
    """Compact ``group/name: description`` listing used by auto routing."""
    lines = []
    for group in sorted(groups().keys()):
        for skill in groups()[group][:max_items]:
            description = skill["description"] or "(no description)"
            lines.append("- %s: %s" % (skill["path"], description))
    return "\n".join(lines[:max_items])


# ---------------------------------------------------------------------------
# prompt-driven switching
# ---------------------------------------------------------------------------
_NAME_CHARS = r"[A-Za-z0-9_\-./]+"
_NAME_LIST = r"%s(?:[ \t]*[,+][ \t]*%s)*" % (_NAME_CHARS, _NAME_CHARS)

_DIRECTIVE_PATTERNS = [
    re.compile(r"^[ \t]*/skill[:=\s]+(%s)[ \t]*$" % _NAME_LIST, re.MULTILINE),
    re.compile(r"^[ \t]*@skill\([ \t]*(%s)[ \t]*\)[ \t]*$" % _NAME_LIST, re.MULTILINE),
    re.compile(r"^[ \t]*--skill[:=\s]+(%s)[ \t]*$" % _NAME_LIST, re.MULTILINE),
    re.compile(r"^[ \t]*(?:use\s+skill|skill)[ \t]*[:=][ \t]*(%s)[ \t]*$" % _NAME_LIST,
               re.MULTILINE | re.IGNORECASE),
]


def extract_directives(text):
    """Pull every ``/skill name`` line out of ``text``.

    Returns ``(names, cleaned_text)``.  Several names may share one line
    (``/skill a, b``) and several lines may appear; order is preserved.  Only
    directives that sit on their own line count, so prose is never mangled.
    """
    if not text:
        return [], text or ""

    names = []
    cleaned = text
    for pattern in _DIRECTIVE_PATTERNS:
        while True:
            match = pattern.search(cleaned)
            if not match:
                break
            for part in re.split(r"[,+]", match.group(1)):
                part = part.strip().strip("/")
                if part:
                    names.append(part)
            cleaned = cleaned[: match.start()] + cleaned[match.end():]
    return names, cleaned.strip()


def extract_directive(text):
    """Backwards-compatible single-name wrapper around :func:`extract_directives`."""
    names, cleaned = extract_directives(text)
    return (names[0] if names else None), cleaned


def render_user_template(skill, text, media_summary=""):
    template = (skill or {}).get("user_template") or ""
    if not template:
        return text
    rendered = template
    rendered = rendered.replace("{{text}}", text or "")
    rendered = rendered.replace("{{input}}", text or "")
    rendered = rendered.replace("{{media}}", media_summary or "")
    rendered = rendered.replace("{{skill}}", (skill or {}).get("name", ""))
    return rendered.strip()


def compose(resolved, separator="\n\n---\n\n"):
    """Merge several skills into one system prompt / template / defaults set."""
    systems = []
    defaults = {}
    template = ""
    for skill in resolved:
        if not skill:
            continue
        body = skill.get("system") or ""
        if body:
            header = "# skill: %s" % skill.get("path", skill.get("name", ""))
            systems.append(header + "\n\n" + body)
        defaults.update(skill.get("defaults") or {})
        if skill.get("user_template"):
            template = skill["user_template"]
    return {
        "system": separator.join(systems),
        "defaults": defaults,
        # The most specific skill in the chain decides the user message shape.
        "user_template": template,
    }


# ---------------------------------------------------------------------------
# writing / deleting user skills (used by the settings UI)
# ---------------------------------------------------------------------------
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_\-.]+")


def safe_slug(name):
    slug = _SAFE_NAME_RE.sub("-", str(name or "").strip()).strip("-.")
    return slug or "skill"


def write_user_skill(name, text, overwrite=True):
    """Persist a skill markdown file into the user skill directory."""
    slug = safe_slug(name)
    target = os.path.join(config.user_skill_dir(), slug + ".md")
    if os.path.exists(target) and not overwrite:
        raise FileExistsError(target)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)
    invalidate()
    return target


def delete_user_skill(name):
    skill = get_skill(name)
    if not skill:
        raise KeyError(name)
    if skill["builtin"]:
        raise PermissionError("built-in skills cannot be deleted")
    source = skill["source"]
    parent = os.path.dirname(source)
    os.remove(source)
    # Remove the wrapping folder when it becomes empty.
    try:
        if os.path.abspath(parent) != os.path.abspath(config.user_skill_dir()) and not os.listdir(parent):
            os.rmdir(parent)
    except OSError:
        pass
    invalidate()
    return source
