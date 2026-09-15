---
name: video-to-prompt
description: Watch the sampled video frames and write a prompt that recreates the clip.
version: 1.0.0
tags: [v2t, t2v, video]
media: [video]
defaults:
  temperature: 0.6
  max_tokens: 400
---

You are given frames sampled in order from a single video clip.

Work out what happens across the clip, then write the text-to-video prompt that
would recreate it.

Rules:
- One paragraph of English prose, 60-100 words.
- Infer the motion from the differences between frames: what the subject does,
  and how the camera moves. State the camera move explicitly.
- Describe the setting, lighting, colour grade and the overall look (phone
  footage, 35mm film, 3D render, anime).
- Do not describe the frames one by one and do not mention frames at all.
- Output the prompt only.

## USER
{{text}}

[attached: {{media}}]
