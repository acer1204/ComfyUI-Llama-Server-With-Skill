"""Thin HTTP client for llama.cpp's ``llama-server`` (OpenAI compatible API)."""

import json
import re
import time
import urllib.error
import urllib.request

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None

_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"^\s*<(think|thinking|reasoning)>.*$", re.DOTALL | re.IGNORECASE)


class LlamaError(RuntimeError):
    pass


def normalise_base_url(base_url):
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise LlamaError("llama-server base URL is empty")
    if "://" not in url:
        url = "http://" + url
    # Accept both "http://host:8080" and "http://host:8080/v1".
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


def strip_thinking(text):
    if not text:
        return text
    cleaned = _THINK_RE.sub("", text)
    if "</think>" in cleaned.lower():
        # Unbalanced opening tag: keep whatever follows the last closing tag.
        idx = cleaned.lower().rfind("</think>")
        cleaned = cleaned[idx + len("</think>"):]
    elif _OPEN_THINK_RE.match(cleaned):
        cleaned = ""
    return cleaned.strip()


def _check_interrupt():
    try:
        import comfy.model_management as mm  # type: ignore

        mm.throw_exception_if_processing_interrupted()
    except ImportError:
        pass


class LlamaClient(object):
    def __init__(self, base_url, api_key="", timeout=300, verify_ssl=True, debug=False):
        self.base_url = normalise_base_url(base_url)
        self.api_key = (api_key or "").strip()
        self.timeout = int(timeout) if timeout else 300
        self.verify_ssl = bool(verify_ssl)
        self.debug = bool(debug)

    # -- plumbing ----------------------------------------------------------
    def _url(self, path):
        return self.base_url + "/" + path.lstrip("/")

    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    def _request_json(self, path, method="GET", body=None, timeout=None):
        url = self._url(path)
        timeout = timeout or self.timeout
        data = json.dumps(body).encode("utf-8") if body is not None else None

        if requests is not None:
            response = requests.request(
                method, url, headers=self._headers(), data=data,
                timeout=timeout, verify=self.verify_ssl,
            )
            if response.status_code >= 400:
                raise LlamaError(
                    "%s %s -> HTTP %d: %s"
                    % (method, url, response.status_code, response.text[:500])
                )
            if not response.content:
                return {}
            return response.json()

        request = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        context = None
        if not self.verify_ssl:
            import ssl

            context = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as handle:
                raw = handle.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise LlamaError(
                "%s %s -> HTTP %d: %s" % (method, url, exc.code, exc.read()[:500])
            )
        except urllib.error.URLError as exc:
            raise LlamaError("cannot reach %s: %s" % (url, exc.reason))
        return json.loads(raw) if raw.strip() else {}

    # -- introspection ------------------------------------------------------
    def health(self):
        try:
            return True, self._request_json("/health", timeout=min(self.timeout, 15))
        except Exception as exc:
            return False, {"error": str(exc)}

    def props(self):
        try:
            return self._request_json("/props", timeout=min(self.timeout, 15))
        except Exception:
            return {}

    def models(self):
        try:
            payload = self._request_json("/v1/models", timeout=min(self.timeout, 15))
        except Exception:
            return []
        items = payload.get("data") if isinstance(payload, dict) else None
        names = []
        for item in items or []:
            name = item.get("id") if isinstance(item, dict) else None
            if name:
                names.append(str(name))
        return names

    def info(self):
        """Best-effort snapshot used by the settings panel's Test button."""
        ok, health = self.health()
        props = self.props()
        result = {
            "ok": ok,
            "base_url": self.base_url,
            "health": health,
            "models": self.models(),
            "model_path": props.get("model_path") or props.get("default_generation_settings", {}).get("model", ""),
            "n_ctx": props.get("default_generation_settings", {}).get("n_ctx")
            or props.get("n_ctx"),
            "chat_template": bool(props.get("chat_template")),
            "multimodal": bool(props.get("modalities") or props.get("has_mtmd")),
            "modalities": props.get("modalities", {}),
        }
        return result

    # -- chat ---------------------------------------------------------------
    def build_body(self, messages, params=None, model=None, stream=False):
        params = dict(params or {})
        body = {"messages": messages, "stream": bool(stream)}
        if stream:
            # llama-server omits usage from the stream unless asked.
            body["stream_options"] = {"include_usage": True}
        if model:
            body["model"] = model

        passthrough = (
            "temperature", "top_p", "top_k", "min_p", "typical_p", "max_tokens",
            "presence_penalty", "frequency_penalty", "repeat_penalty", "repeat_last_n",
            "seed", "stop", "n_probs", "tfs_z", "mirostat", "mirostat_tau",
            "mirostat_eta", "dynatemp_range", "dynatemp_exponent", "grammar",
            "response_format", "json_schema", "reasoning_effort", "chat_template_kwargs",
            "keep_alive",
        )
        for key in passthrough:
            value = params.get(key)
            if value is None:
                continue
            if key in ("seed", "keep_alive") and int(value) < 0:
                continue
            if key == "stop" and not value:
                continue
            body[key] = value

        extra = params.get("extra_body")
        if isinstance(extra, dict):
            body.update(extra)
        return body

    def chat(self, messages, params=None, model=None, stream=False, on_delta=None,
             retries=1):
        body = self.build_body(messages, params, model, stream)
        last_error = None
        for attempt in range(max(1, int(retries) + 1)):
            try:
                if stream:
                    return self._chat_stream(body, on_delta)
                return self._chat_once(body)
            except LlamaError:
                raise
            except Exception as exc:  # transient network hiccup
                last_error = exc
                if attempt < retries:
                    time.sleep(1.0 + attempt)
                    continue
                raise LlamaError("chat request failed: %s" % exc)
        raise LlamaError("chat request failed: %s" % last_error)

    def _chat_once(self, body):
        payload = self._request_json("/v1/chat/completions", method="POST", body=body)
        choices = payload.get("choices") or []
        if not choices:
            raise LlamaError("llama-server returned no choices: %s" % json.dumps(payload)[:400])
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        usage = payload.get("usage") or {}
        return {
            "content": content,
            "reasoning": reasoning,
            "finish_reason": choices[0].get("finish_reason"),
            "usage": usage,
            "raw": payload,
        }

    def _chat_stream(self, body, on_delta=None):
        url = self._url("/v1/chat/completions")
        data = json.dumps(body).encode("utf-8")
        chunks = []
        reasoning_chunks = []
        finish_reason = None
        usage = {}

        if requests is not None:
            response = requests.post(
                url, headers=self._headers(), data=data, timeout=self.timeout,
                verify=self.verify_ssl, stream=True,
            )
            if response.status_code >= 400:
                raise LlamaError(
                    "POST %s -> HTTP %d: %s" % (url, response.status_code, response.text[:500])
                )
            # Server-sent events are always UTF-8, but requests falls back to
            # ISO-8859-1 for text/* without a charset and mangles the content.
            response.encoding = "utf-8"
            line_iter = response.iter_lines(decode_unicode=True)
        else:
            context = None
            if not self.verify_ssl:
                import ssl

                context = ssl._create_unverified_context()
            request = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
            handle = urllib.request.urlopen(request, timeout=self.timeout, context=context)

            def _iter():
                for raw in handle:
                    yield raw.decode("utf-8").rstrip("\n")

            line_iter = _iter()

        for line in line_iter:
            _check_interrupt()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                if line == "[DONE]":
                    break
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                piece = delta.get("content") or ""
                think = delta.get("reasoning_content") or ""
                if piece:
                    chunks.append(piece)
                    if on_delta:
                        on_delta(piece)
                if think:
                    reasoning_chunks.append(think)
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

        return {
            "content": "".join(chunks),
            "reasoning": "".join(reasoning_chunks),
            "finish_reason": finish_reason,
            "usage": usage,
            "raw": {"streamed": True},
        }
