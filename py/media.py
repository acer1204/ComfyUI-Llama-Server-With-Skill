"""Convert ComfyUI media tensors into OpenAI-style multimodal content parts."""

import base64
import io
import math

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy always ships with ComfyUI
    np = None

try:
    import torch
except Exception:  # pragma: no cover
    torch = None

from PIL import Image

SAMPLE_MODES = ["uniform", "first", "last", "every_n"]


# ---------------------------------------------------------------------------
# tensors -> PIL
# ---------------------------------------------------------------------------
def tensor_to_pils(images):
    """Accept a ComfyUI IMAGE tensor ``[B, H, W, C]`` and return a PIL list."""
    if images is None:
        return []
    if isinstance(images, (list, tuple)):
        out = []
        for item in images:
            out.extend(tensor_to_pils(item))
        return out
    if isinstance(images, Image.Image):
        return [images]

    array = images
    if torch is not None and isinstance(array, torch.Tensor):
        array = array.detach().cpu().float().numpy()
    if np is None:
        raise RuntimeError("numpy is required to encode images")
    array = np.asarray(array)

    if array.ndim == 2:  # H, W
        array = array[None, ..., None]
    elif array.ndim == 3:
        # Either [H, W, C] or a batch of masks [B, H, W].
        if array.shape[-1] in (1, 3, 4):
            array = array[None, ...]
        else:
            array = array[..., None]
    elif array.ndim != 4:
        raise ValueError("unsupported image tensor shape: %s" % (array.shape,))

    if array.shape[1] in (1, 3, 4) and array.shape[-1] not in (1, 3, 4):
        # Channels-first batch [B, C, H, W] -> [B, H, W, C]
        array = np.transpose(array, (0, 2, 3, 1))

    if array.dtype != np.uint8:
        array = np.clip(array, 0.0, 1.0)
        array = (array * 255.0 + 0.5).astype(np.uint8)

    pils = []
    for frame in array:
        if frame.shape[-1] == 1:
            pils.append(Image.fromarray(frame[..., 0], mode="L").convert("RGB"))
        elif frame.shape[-1] == 4:
            pils.append(Image.fromarray(frame, mode="RGBA").convert("RGB"))
        else:
            pils.append(Image.fromarray(frame[..., :3], mode="RGB"))
    return pils


def video_to_pils(video):
    """Extract frames (and frame rate) from a ComfyUI VIDEO input."""
    if video is None:
        return [], None

    # Native ComfyUI VideoInput objects expose get_components().
    getter = getattr(video, "get_components", None)
    if callable(getter):
        components = getter()
        frames = getattr(components, "images", None)
        rate = getattr(components, "frame_rate", None)
        try:
            rate = float(rate) if rate is not None else None
        except Exception:
            rate = None
        return tensor_to_pils(frames), rate

    # VideoHelperSuite and friends hand over plain IMAGE batches.
    return tensor_to_pils(video), None


# ---------------------------------------------------------------------------
# frame selection / resizing
# ---------------------------------------------------------------------------
def sample_frames(pils, max_frames, mode="uniform", every_n=1):
    total = len(pils)
    if total == 0:
        return [], []
    if max_frames is None or max_frames <= 0 or total <= max_frames:
        return list(pils), list(range(total))

    if mode == "first":
        indices = list(range(max_frames))
    elif mode == "last":
        indices = list(range(total - max_frames, total))
    elif mode == "every_n":
        step = max(1, int(every_n))
        indices = list(range(0, total, step))[:max_frames]
    else:  # uniform
        if max_frames == 1:
            indices = [total // 2]
        else:
            step = (total - 1) / float(max_frames - 1)
            indices = [int(round(i * step)) for i in range(max_frames)]
            indices = sorted(set(min(total - 1, max(0, i)) for i in indices))
    return [pils[i] for i in indices], indices


def resize_to_max_side(image, max_side):
    if not max_side or max_side <= 0:
        return image
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = float(max_side) / float(longest)
    new_size = (max(1, int(math.floor(width * scale))), max(1, int(math.floor(height * scale))))
    return image.resize(new_size, Image.LANCZOS)


def encode_image(image, image_format="jpeg", quality=85, max_side=768):
    image = resize_to_max_side(image, max_side)
    buffer = io.BytesIO()
    fmt = (image_format or "jpeg").lower()
    if fmt in ("jpg", "jpeg"):
        image.convert("RGB").save(buffer, format="JPEG", quality=int(quality), optimize=True)
        mime = "image/jpeg"
    elif fmt == "webp":
        image.convert("RGB").save(buffer, format="WEBP", quality=int(quality))
        mime = "image/webp"
    else:
        image.save(buffer, format="PNG", optimize=True)
        mime = "image/png"
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:%s;base64,%s" % (mime, payload), len(buffer.getvalue())


def image_content_part(image, image_format="jpeg", quality=85, max_side=768):
    url, size = encode_image(image, image_format, quality, max_side)
    return {"type": "image_url", "image_url": {"url": url}}, size


# ---------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------
def audio_content_part(audio, max_seconds=60):
    """Encode a ComfyUI AUDIO dict as a base64 WAV content part."""
    if not audio:
        return None, 0
    waveform = audio.get("waveform") if isinstance(audio, dict) else None
    sample_rate = int(audio.get("sample_rate", 16000)) if isinstance(audio, dict) else 16000
    if waveform is None:
        return None, 0

    array = waveform
    if torch is not None and isinstance(array, torch.Tensor):
        array = array.detach().cpu().float().numpy()
    array = np.asarray(array)
    if array.ndim == 3:  # [B, C, T] -> take the first item
        array = array[0]
    if array.ndim == 1:
        array = array[None, :]

    channels, samples = array.shape
    limit = int(max_seconds * sample_rate) if max_seconds and max_seconds > 0 else samples
    if samples > limit:
        array = array[:, :limit]

    interleaved = np.clip(array.T.reshape(-1), -1.0, 1.0)
    pcm = (interleaved * 32767.0).astype("<i2").tobytes()

    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    raw = buffer.getvalue()
    payload = base64.b64encode(raw).decode("ascii")
    return {"type": "input_audio", "input_audio": {"data": payload, "format": "wav"}}, len(raw)


# ---------------------------------------------------------------------------
# high level helper used by the node
# ---------------------------------------------------------------------------
ROLES = [
    "reference", "first_frame", "last_frame", "subject", "style",
    "product", "background", "custom",
]


def build_labeled_parts(slots, opts):
    """Turn labelled image slots into ``[label]`` + image content parts.

    Video models distinguish the first frame, the last frame and free
    reference images (H3's I2VA / FL2VA / L2VA / Ref2VA modes), so each image
    is announced with its role before it is sent.
    """
    max_side = int(opts.get("max_image_side", 768))
    image_format = opts.get("image_format", "jpeg")
    quality = int(opts.get("jpeg_quality", 85))

    parts = []
    labels = []
    payload = 0
    for slot in slots or []:
        pils = tensor_to_pils(slot.get("image"))
        if not pils:
            continue
        label = str(slot.get("label") or "reference").strip()
        for index, pil in enumerate(pils):
            tag = label if len(pils) == 1 else "%s_%d" % (label, index + 1)
            parts.append({"type": "text", "text": "[%s]" % tag})
            part, size = image_content_part(pil, image_format, quality, max_side)
            parts.append(part)
            payload += size
            labels.append(tag)
    return parts, labels, payload


def clip_video(pils, frame_rate, max_seconds):
    """Trim a frame list to ``max_seconds``; returns ``(frames, note)``."""
    if not pils or not max_seconds or max_seconds <= 0:
        return pils, ""
    rate = float(frame_rate) if frame_rate else 0.0
    if rate <= 0:
        return pils, ""
    allowed = int(round(rate * max_seconds))
    if allowed <= 0 or len(pils) <= allowed:
        return pils, ""
    note = "影片超過 %.0f 秒，只取前 %.1f 秒（%d/%d 幀）" % (
        max_seconds, allowed / rate, allowed, len(pils))
    return pils[:allowed], note


def build_clip_parts(videos, opts):
    """Sample several VIDEO inputs, honouring the per-clip second limit."""
    max_frames = int(opts.get("max_frames", 8))
    max_side = int(opts.get("max_image_side", 768))
    image_format = opts.get("image_format", "jpeg")
    quality = int(opts.get("jpeg_quality", 85))
    mode = opts.get("frame_sample", "uniform")
    every_n = int(opts.get("every_n", 1))
    max_seconds = float(opts.get("max_video_seconds", 0) or 0)

    parts = []
    notes = []
    payload = 0
    total_frames = 0
    for index, video in enumerate(videos or []):
        if video is None:
            continue
        pils, rate = video_to_pils(video)
        if not pils:
            continue
        pils, note = clip_video(pils, rate, max_seconds)
        if note:
            notes.append("video_%d: %s" % (index + 1, note))
        chosen, _ = sample_frames(pils, max_frames, mode, every_n)
        label = "video_%d" % (index + 1)
        parts.append({"type": "text", "text": "[%s]" % label})
        for pil in chosen:
            part, size = image_content_part(pil, image_format, quality, max_side)
            parts.append(part)
            payload += size
        total_frames += len(chosen)
    return parts, total_frames, payload, notes


def build_audio_parts(audios, opts):
    """Encode several AUDIO inputs, capped at a shared total duration."""
    budget = float(opts.get("max_audio_seconds_total", 0) or 0)
    if budget <= 0:
        budget = float(opts.get("max_audio_seconds", 60) or 60)

    parts = []
    notes = []
    payload = 0
    seconds = 0.0
    for index, audio in enumerate(audios or []):
        if audio is None:
            continue
        remaining = budget - seconds
        if remaining <= 0.05:
            notes.append("audio_%d 略過：已達 %.0f 秒總長上限" % (index + 1, budget))
            continue
        part, size = audio_content_part(audio, remaining)
        if not part:
            continue
        try:
            rate = float(audio.get("sample_rate", 16000))
            length = audio.get("waveform").shape[-1]
            used = min(length / rate, remaining)
        except Exception:
            used = remaining
        parts.append({"type": "text", "text": "[audio_%d]" % (index + 1)})
        parts.append(part)
        payload += size
        seconds += used
    return parts, round(seconds, 2), payload, notes


def build_media_parts(images=None, video=None, audio=None, opts=None, slots=None):
    """Return ``(content_parts, summary_dict)`` for the given ComfyUI inputs."""
    opts = opts or {}
    max_frames = int(opts.get("max_frames", 8))
    max_side = int(opts.get("max_image_side", 768))
    image_format = opts.get("image_format", "jpeg")
    quality = int(opts.get("jpeg_quality", 85))
    mode = opts.get("frame_sample", "uniform")
    every_n = int(opts.get("every_n", 1))
    max_audio_seconds = float(opts.get("max_audio_seconds", 60))

    parts = []
    summary = {
        "images": 0,
        "video_frames": 0,
        "video_total_frames": 0,
        "frame_indices": [],
        "frame_rate": None,
        "audio_seconds": 0.0,
        "payload_bytes": 0,
        "labels": [],
    }

    # Labelled slots go first so the model reads the roles before the raw media.
    slot_parts, slot_labels, slot_payload = build_labeled_parts(slots, opts)
    if slot_parts:
        parts.extend(slot_parts)
        summary["labels"] = slot_labels
        summary["payload_bytes"] += slot_payload

    still_pils = tensor_to_pils(images) if images is not None else []
    video_pils, frame_rate = video_to_pils(video) if video is not None else ([], None)
    summary["frame_rate"] = frame_rate
    summary["video_total_frames"] = len(video_pils)

    if still_pils:
        chosen, _ = sample_frames(still_pils, max_frames, mode, every_n)
        summary["images"] = len(chosen)
        for pil in chosen:
            part, size = image_content_part(pil, image_format, quality, max_side)
            parts.append(part)
            summary["payload_bytes"] += size

    if video_pils:
        chosen, indices = sample_frames(video_pils, max_frames, mode, every_n)
        summary["video_frames"] = len(chosen)
        summary["frame_indices"] = indices
        for pil in chosen:
            part, size = image_content_part(pil, image_format, quality, max_side)
            parts.append(part)
            summary["payload_bytes"] += size

    if audio is not None:
        part, size = audio_content_part(audio, max_audio_seconds)
        if part:
            parts.append(part)
            summary["payload_bytes"] += size
            try:
                waveform = audio.get("waveform")
                rate = float(audio.get("sample_rate", 16000))
                length = waveform.shape[-1]
                summary["audio_seconds"] = round(min(length / rate, max_audio_seconds), 2)
            except Exception:
                pass

    return parts, summary


def describe_media(summary):
    """Human readable one-liner injected into the user message."""
    bits = []
    if summary.get("labels"):
        bits.append("labelled images: " + ", ".join(summary["labels"]))
    if summary.get("images"):
        bits.append("%d image(s)" % summary["images"])
    if summary.get("video_frames"):
        text = "%d video frame(s)" % summary["video_frames"]
        total = summary.get("video_total_frames") or 0
        if total and total != summary["video_frames"]:
            text += " sampled from %d" % total
        rate = summary.get("frame_rate")
        if rate:
            text += " at %.3g fps" % rate
        bits.append(text)
    if summary.get("audio_seconds"):
        bits.append("%.1fs of audio" % summary["audio_seconds"])
    return ", ".join(bits)
