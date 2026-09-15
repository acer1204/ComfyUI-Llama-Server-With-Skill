# ComfyUI-Llama-Server-With-Skill

把 **圖片 / 影片 / 音訊 / 文字** 送到 llama.cpp 的 `llama-server`，取回可直接使用的
**生成提示詞**。技能（skill）是 Markdown 檔，可以在 ComfyUI 設定面板匯入，也可以在
prompt 裡用一行指令即時切換。

---

## 功能

- 連線任何 OpenAI 相容的 `llama-server`（本機或遠端、HTTP 或 HTTPS）
- 影像輸入：單張、整批、兩組不同尺寸
- 影片輸入：ComfyUI 原生 `VIDEO`，自動抽幀並縮圖
- 音訊輸入：需要模型支援（Qwen2-Audio、Ultravox 等）
- 角色標記影像：`first_frame` / `last_frame` / `reference` / 自訂標籤，可串接任意多張
- 完整取樣參數，附常用預設值；支援 JSON Schema 與 GBNF 文法
- 一個 AIO 節點包辦全部，插槽隨接線長出來，連線與取樣參數收在設定面板
- 技能系統：內建 29 個，依群組分類，可串接多個，可在設定面板匯入 `.md` / `.zip`，或用 `/skill 名稱` 切換
- 影片規格節點：秒數 0–15、畫面比例、解析度、模式（T2VA / I2VA / FL2VA / L2VA / Ref2VA）
- 結構化多輸出：H3 風格的欄位各自成為獨立的 STRING 輸出
- 顯存控制：請求前釋放 ComfyUI 模型，以及 `keep_alive` 秒數

---

## 範例工作流

`example_workflows/` 裡的檔案可以直接拖進 ComfyUI：

| 檔案 | 內容 |
| --- | --- |
| `00_aio_single_node.json` | **從這裡開始。** 一個 AIO 節點，一張圖 → 一則提示詞 |
| `04_aio_ref2va.json` | AIO 節點跑 Ref2VA，兩張參考圖 → 六個欄位 |
| `01_image_to_prompt.json` | 進階拆解版：一張圖 → 一則提示詞 |
| `02_h3_video_fields.json` | 進階拆解版：FL2VA，首幀＋尾幀 → 三個欄位 |
| `03_h3_ref2va_six_fields.json` | 進階拆解版：Ref2VA → 六個欄位 |

---

## 安裝

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/acer1204/ComfyUI-Llama-Server-With-Skill
pip install -r ComfyUI-Llama-Server-With-Skill/requirements.txt
```

重啟 ComfyUI。相依套件只有 `requests`、`Pillow`、`numpy`，ComfyUI 環境通常都已具備。

### 啟動 llama-server

視覺模型需要 `--mmproj`：

```bash
llama-server -m model.gguf --mmproj mmproj.gguf --host 0.0.0.0 --port 8080 -c 32768
```

用「Llama 連線測試」節點或設定面板的測試鈕確認連線，它會回報模型、`n_ctx` 與是否支援多模態。

---

## 節點

日常只需要一個：**Llama Prompter AIO**。

```
LoadImage ─→ image_1 ─→ Llama Prompter AIO ─→ full_prompt ─→ CLIP Text Encode
```

連線位址、取樣參數、抽幀設定都在 ComfyUI 設定面板，節點上只留每次會改的東西：

| 欄位 | 說明 |
| --- | --- |
| `text` | 你的補充內容。也可以像 webui 那樣自己一行寫 `/技能名稱` |
| `mode` | `plain` 只輸出一則提示詞；`T2VA` / `I2VA` / `FL2VA` / `L2VA` / `Ref2VA` 走 H3 分欄位 |
| `system_prompt` | 從設定面板自建的清單挑一個，會放在所有技能前面 |
| `output_language` | 輸出語言 |
| `skill_1` … `skill_5` | 依序套用，填了一個才會出現下一個 |
| `duration_seconds` | 0–15 秒，影片模式用 |
| `aspect_ratio` | 畫面比例 |
| `image_1` … `image_9` | 接上一個才會長出下一個 |
| `video_1` … `video_3` | 單支上限 15 秒，超過只取前段 |
| `audio_1` … `audio_3` | 三支合計上限 15 秒 |

影像角色由 `mode` 自動決定，不用另外標記：

| mode | image_1 | image_2 | 其餘 |
| --- | --- | --- | --- |
| I2VA | 首幀 | 參考圖 | 參考圖 |
| L2VA | 尾幀 | 參考圖 | 參考圖 |
| FL2VA | 首幀 | 尾幀 | 參考圖 |
| Ref2VA | 參考圖 | 參考圖 | 參考圖 |

### 進階節點

拆開的版本都還在，收在節點選單的 **Llama Prompter / advanced** 底下。
需要在同一張圖裡用兩組不同伺服器設定、或是要接字串節點動態換技能時才用得到。

| 節點 | 用途 |
| --- | --- |
| Llama Server 連線 | 位址、模型、金鑰、逾時、SSL、串流、顯存選項 |
| Llama 取樣參數 | temperature / top_p / top_k / min_p / max_tokens / 懲罰 / seed / stop / JSON Schema / GBNF |
| Llama 影像/影片選項 | 抽幀張數與方式、長邊上限、影像格式與品質 |
| Llama Skill | 選擇技能，可串接 |
| Llama 影像插槽 | 自訂影像角色標籤 |
| Llama 影片規格 | 模式、秒數、比例、解析度、fps、備註 |
| Llama Prompter | 輸出單一提示詞 |
| Llama 影片 Prompter | 分欄位輸出 |
| Llama 取出欄位 | 從結構化文字取出指定欄位 |
| Llama Skill 清單 | 列出目前可用的技能 |
| Llama 文字預覽 | 在畫布上顯示文字 |
| Llama 連線測試 | 回報伺服器狀態 |

---

## 技能

技能是一個帶 YAML front matter 的 Markdown 檔：

```markdown
---
name: flux-prompt
description: 一句話說明，auto 模式會用它來挑選。
version: 1.0.0
tags: [t2i, flux]
media: [text, image]
defaults:
  temperature: 0.6
  max_tokens: 400
---

系統提示寫在這裡。

## USER
{{text}}

[attached: {{media}}]
```

支援兩種擺放方式：

```
skills/<群組>/flux-prompt.md
skills/<群組>/flux-prompt/SKILL.md      ← 可另外放 references/ 資料夾
```

同一個資料夾裡的 `SKILL.cn.md` 會自動註冊成 `<名稱>-cn`，所以中英文版本可以分開選。

### 群組

技能在下拉選單裡以 `群組/名稱` 呈現，群組就是它所在的資料夾：

```
core/flux-prompt
addons/cinematic-look
minimax-h3/h3-prompt-writing
user/my-skill
```

這樣近三十個技能混在一起時，來源一眼可辨，也可以直接打 `minimax` 過濾。
群組來自資料夾名稱，想自己分類就在 `skills/` 底下開資料夾把 `.md` 丟進去，
或是在 front matter 寫 `group: 你的分類` 覆寫。

引用技能時打全名或只打名稱都可以，`core/sdxl-tags` 和 `sdxl-tags` 都找得到。

### 串接多個技能

`Llama Skill` 節點有 `chain` 輸入，可以一路串下去，**先接的先套用**：

```
Llama Skill (minimax-h3/h3-prompt-writing) ──chain──→ Llama Skill (addons/cinematic-look) ──→ Prompter
```

慣例是把決定輸出格式的技能放最前面，修飾用的放後面。`skills/addons/` 裡的三個
就是為此設計的：`cinematic-look` 加電影感，`brand-safe` 去掉商標、可讀文字與可辨識人物。
輸出語言不要用技能控制，那是 Prompter 節點 `output_language` 的工作。

串接時的合併規則：系統提示依序串起來並標上 `# skill: 群組/名稱`；
front matter 的 `defaults` 後面蓋前面；`## USER` 模板取最後一個有定義的技能。

### 切換方式

`Llama Skill` 節點的 `mode`：

- `manual` — 用下拉選單選
- `from_prompt` — 在文字自己一行寫指令，四種寫法都接受：
  `/skill sdxl-tags`、`/skill: sdxl-tags`、`@skill(sdxl-tags)`、`use skill = sdxl-tags`
  指令那一行會從送出的文字中移除。一行可以列多個，用逗號或 `+` 分隔，順序照寫：

  ```
  /skill h3-prompt-writing, addons/cinematic-look
  一隻貓走過下雪的木階
  ```

  prompt 裡只要出現指令，就會整條覆寫節點上串好的技能。
- `auto` — 讓模型依描述再追加一個技能到鏈的最後面
- `off` — 不套用任何技能

`skill_override` 欄位可以接字串節點動態指定，同樣支援用逗號分隔多個。

### 匯入技能

ComfyUI 設定面板 → **Llama Prompter → Skills → Manage skills**，可以：

- 匯入 `.md` 或 `.zip`（zip 內的 `references/` 會一併保留）
- 線上編輯並儲存
- 刪除自己匯入的技能（內建的不能刪）

使用者技能存在 `ComfyUI/user/default/llama_prompter/skills/`。匯入後按 **R** 重新整理節點定義，下拉選單才會出現新項目。

### 內建技能

| 群組 | 數量 | 內容 |
| --- | --- | --- |
| `core` | 10 | `flux-prompt`、`sdxl-tags`、`image-caption`、`image-to-prompt`、`video-prompt`、`video-to-prompt`、`negative-prompt`、`prompt-upsample`、`image-edit-instruction`、`zh-to-en-prompt` |
| `addons` | 2 | `cinematic-look`、`brand-safe`，設計來串在格式技能後面 |
| `minimax-h3` | 17 | MiniMax-H3 的 9 個技能包（來源：`MiniMax-AI/MiniMax-H3` 的 `skills/` 目錄）含中文版，其中 `h3-prompt-writing` 帶有 references |

---

## H3 影片提示詞：分欄位輸出

`Llama 影片 Prompter` 依照 `Llama 影片規格` 的模式決定欄位：

| 模式 | 欄位 |
| --- | --- |
| T2VA / I2VA / FL2VA / L2VA | `integrated_multimodal_description`、`overall_soundscape`、`non_diegetic_music` |
| Ref2VA | `subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music` |

節點固定有八個輸出：

```
full_prompt            全部欄位合併成一段文字
subject_definitions    Ref2VA 專用，其他模式為空
summary                Ref2VA 專用，其他模式為空
retention_analysis     Ref2VA 專用，其他模式為空
description            Ref2VA 給 detailed_description，其他模式給 integrated_multimodal_description
overall_soundscape     兩組模式都有
non_diegetic_music     兩組模式都有
info                   統計資訊
```

`description` 這條刻意合併，所以你在 T2VA 和 Ref2VA 之間切換時，下游接線不用重接。

`force_json` 預設開啟，會用 JSON Schema 逼模型填滿所有欄位；關掉則改用
`欄位名: 內容` 的寬鬆解析。`extra_fields` 可以再加自訂欄位名稱（逗號分隔），
再用 `Llama 取出欄位` 節點依名稱取值。

影像要用 `Llama 影像插槽` 標好角色，模型才知道哪張是首幀、哪張是尾幀：

```
LoadImage ─→ Llama 影像插槽 (first_frame) ─→ Llama 影像插槽 (last_frame) ─→ 影片 Prompter
                                    ↑
                              LoadImage
```

規格節點會把秒數、比例、解析度寫成一段 `[generation spec]` 附在請求裡，技能就不會再回頭問你這些值。

---

## 顯存

同一張卡要同時跑 llama.cpp 和擴散模型時，`Llama Server 連線` 有兩個選項：

- `free_comfy_vram` — 送出請求前先把 ComfyUI 已載入的模型移出顯存。這個一定有效。
- `keep_alive` — 產生後模型在顯存裡留幾秒。`-1` 不卸載、`0` 立刻卸載、`N` 閒置 N 秒後卸載。
  這需要伺服器支援；**純 llama-server 沒有卸載模型的 API，會忽略這個值**。
  搭配 llama-swap 或 Ollama 之類的前端才會真的釋放。實際結果會寫在 `info` 輸出裡。

其他省顯存的方式：把 `max_frames` 和 `max_image_side` 調小，vision token 數會直接下降。

---

## 設定面板

ComfyUI 設定 → **Llama Prompter**：

- **Server** — 位址、模型、金鑰、逾時、SSL、串流、測試連線
- **Defaults** — 取樣參數與媒體預設值，新建節點時會套用
- **Skills** — 預設技能、額外掃描資料夾（以 `;` 分隔）、技能管理器
- **System prompts** — AIO 節點下拉選單的內容，可自行新增與編輯
- **AIO** — 影像 / 影片 / 音訊 / 技能的數量上限與秒數上限、插槽是否隨接線長出來、以及要不要把技能的 `references/` 一起送出（預設關閉，開了 prompt 會從 1.6k 漲到 10k token）

設定存在 `ComfyUI/user/default/llama_prompter/config.json`，節點的 `use_global_settings`
打開後就會改讀這份設定。

---

## 疑難排解

| 狀況 | 處理 |
| --- | --- |
| `502 Bad Gateway` | 反向代理活著但 llama-server 沒起來 |
| `503 Loading model` | 模型還在載入，稍等再跑 |
| 模型看不到圖 | llama-server 沒帶 `--mmproj`，用連線測試節點確認 multimodal |
| 影片請求逾時 | 調高 `timeout`，或調低 `max_frames` |
| 新匯入的技能沒出現 | 按 **R** 重新整理節點定義 |
| 輸出夾雜推理內容 | 打開 `strip_thinking` |
| 中文輸出變亂碼 | 請更新到 1.0.1 以後，舊版串流解碼用錯字集 |
| 欄位是空的 | 打開 `force_json`，或把 `max_tokens` 調高 |

---

## 授權

MIT。`skills/` 目錄下的 MiniMax-H3 技能包版權屬於其原作者。
