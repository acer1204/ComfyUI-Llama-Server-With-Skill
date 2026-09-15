"""HTTP routes backing the ComfyUI settings panel and the skill manager dialog."""

import asyncio
import io
import os
import shutil
import zipfile

from . import config, llama_client, skills

PREFIX = "/llama_prompter"


def _json(payload, status=200):
    from aiohttp import web

    return web.json_response(payload, status=status)


def _skill_row(skill):
    return {
        "name": skill["name"],
        "description": skill["description"],
        "version": skill["version"],
        "tags": skill["tags"],
        "media": skill["media"],
        "builtin": skill["builtin"],
        "source": skill["source"],
        "chars": len(skill["system"]),
    }


def _safe_member(name):
    """Reject absolute paths and ``..`` escapes inside an uploaded zip."""
    name = name.replace("\\", "/")
    if name.startswith("/") or ":" in name.split("/")[0]:
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _import_zip(data, target_dir):
    imported = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [m for m in archive.namelist() if not m.endswith("/")]
        markdown = [m for m in members if m.lower().endswith((".md", ".markdown"))]
        if not markdown:
            raise ValueError("zip 內找不到任何 .md 技能檔")

        # A zip that bundles one skill folder keeps its folder; loose files land flat.
        for member in members:
            safe = _safe_member(member)
            if safe is None:
                continue
            ext = os.path.splitext(safe)[1].lower()
            if ext not in (".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv"):
                continue
            destination = os.path.join(target_dir, *safe.split("/"))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with archive.open(member) as source, open(destination, "wb") as handle:
                shutil.copyfileobj(source, handle)
            if ext in (".md", ".markdown"):
                imported.append(safe)
    return imported


def register(server_instance=None):
    try:
        from aiohttp import web
        from server import PromptServer  # type: ignore
    except Exception as exc:  # pragma: no cover - not inside ComfyUI
        print("[LlamaPrompter] routes not registered: %s" % exc)
        return False

    instance = server_instance or PromptServer.instance
    routes = instance.routes

    # -- config ----------------------------------------------------------
    @routes.get(PREFIX + "/config")
    async def get_config(request):
        cfg = config.load(force=True)
        return _json({
            "config": cfg,
            "defaults": config.DEFAULT_CONFIG,
            "paths": {
                "config": config.config_path(),
                "user_skills": config.user_skill_dir(),
                "builtin_skills": config.BUILTIN_SKILL_DIR,
                "search": config.skill_search_paths(),
            },
        })

    @routes.post(PREFIX + "/config")
    async def post_config(request):
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "invalid JSON body"}, 400)
        if not isinstance(body, dict):
            return _json({"error": "expected an object"}, 400)
        cfg = config.save(body)
        skills.invalidate()
        return _json({"ok": True, "config": cfg})

    # -- skills ----------------------------------------------------------
    @routes.get(PREFIX + "/skills")
    async def get_skills(request):
        if request.query.get("refresh"):
            skills.invalidate()
        found = skills.discover(force=bool(request.query.get("refresh")))
        rows = [_skill_row(s) for s in sorted(found.values(), key=lambda s: s["name"].lower())]
        return _json({"skills": rows, "paths": config.skill_search_paths()})

    @routes.get(PREFIX + "/skill")
    async def get_skill(request):
        name = request.query.get("name", "")
        skill = skills.get_skill(name)
        if not skill:
            return _json({"error": "skill not found: %s" % name}, 404)
        try:
            with open(skill["source"], "r", encoding="utf-8") as fh:
                content = fh.read()
        except Exception as exc:
            return _json({"error": str(exc)}, 500)
        row = _skill_row(skill)
        row["content"] = content
        return _json(row)

    @routes.post(PREFIX + "/skill")
    async def post_skill(request):
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "invalid JSON body"}, 400)
        content = body.get("content") or ""
        if not content.strip():
            return _json({"error": "content is empty"}, 400)
        parsed = skills.parse_skill_text(content, name_hint=body.get("name") or "")
        name = body.get("name") or parsed["name"]
        try:
            path = skills.write_user_skill(name, content, overwrite=bool(body.get("overwrite", True)))
        except FileExistsError:
            return _json({"error": "skill already exists: %s" % name}, 409)
        except Exception as exc:
            return _json({"error": str(exc)}, 500)
        return _json({"ok": True, "name": parsed["name"], "path": path})

    @routes.delete(PREFIX + "/skill")
    async def delete_skill(request):
        name = request.query.get("name", "")
        try:
            path = skills.delete_user_skill(name)
        except KeyError:
            return _json({"error": "skill not found: %s" % name}, 404)
        except PermissionError as exc:
            return _json({"error": str(exc)}, 403)
        except Exception as exc:
            return _json({"error": str(exc)}, 500)
        return _json({"ok": True, "removed": path})

    @routes.post(PREFIX + "/skills/import")
    async def import_skills(request):
        target = config.user_skill_dir()
        imported = []
        errors = []
        try:
            reader = await request.multipart()
        except Exception:
            return _json({"error": "expected a multipart upload"}, 400)

        while True:
            part = await reader.next()
            if part is None:
                break
            filename = getattr(part, "filename", None)
            if not filename:
                await part.read()
                continue
            data = await part.read(decode=False)
            lower = filename.lower()
            try:
                if lower.endswith(".zip"):
                    imported.extend(_import_zip(data, target))
                elif lower.endswith((".md", ".markdown")):
                    text = data.decode("utf-8", errors="replace")
                    parsed = skills.parse_skill_text(
                        text, name_hint=os.path.splitext(os.path.basename(filename))[0]
                    )
                    skills.write_user_skill(parsed["name"], text, overwrite=True)
                    imported.append(parsed["name"])
                else:
                    errors.append("%s: 只接受 .md 或 .zip" % filename)
            except Exception as exc:
                errors.append("%s: %s" % (filename, exc))

        skills.invalidate()
        found = skills.discover(force=True)
        return _json({
            "ok": not errors,
            "imported": imported,
            "errors": errors,
            "skills": [_skill_row(s) for s in sorted(found.values(), key=lambda s: s["name"].lower())],
        })

    # -- connection test --------------------------------------------------
    @routes.post(PREFIX + "/test")
    async def test_connection(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        cfg = config.load()
        client = llama_client.LlamaClient(
            base_url=body.get("base_url") or cfg["base_url"],
            api_key=body.get("api_key", cfg["api_key"]),
            timeout=int(body.get("timeout", 20) or 20),
            verify_ssl=bool(body.get("verify_ssl", cfg["verify_ssl"])),
        )
        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, client.info)
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)}, 200)
        return _json(info)

    print("[LlamaPrompter] routes registered at %s/*" % PREFIX)
    return True
