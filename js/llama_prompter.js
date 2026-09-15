import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const PREFIX = "/llama_prompter";
const EXT = "LlamaPrompter.Settings";

let pushing = false;
let backendConfig = null;

/* ------------------------------------------------------------------ */
/* backend helpers                                                     */
/* ------------------------------------------------------------------ */
async function getConfig() {
  const response = await api.fetchApi(`${PREFIX}/config`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}

async function pushConfig(patch) {
  if (pushing) return;
  const response = await api.fetchApi(`${PREFIX}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  backendConfig = data.config;
  return data.config;
}

async function listSkills(refresh = true) {
  const response = await api.fetchApi(`${PREFIX}/skills${refresh ? "?refresh=1" : ""}`);
  return await response.json();
}

async function readSkill(name) {
  const response = await api.fetchApi(`${PREFIX}/skill?name=${encodeURIComponent(name)}`);
  return await response.json();
}

async function saveSkill(name, content) {
  const response = await api.fetchApi(`${PREFIX}/skill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, content, overwrite: true }),
  });
  return await response.json();
}

async function deleteSkill(name) {
  const response = await api.fetchApi(`${PREFIX}/skill?name=${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  return await response.json();
}

async function importSkillFiles(files) {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  const response = await api.fetchApi(`${PREFIX}/skills/import`, { method: "POST", body: form });
  return await response.json();
}

async function testConnection(payload) {
  const response = await api.fetchApi(`${PREFIX}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  return await response.json();
}

function toast(message, severity = "info") {
  try {
    app.extensionManager?.toast?.add({ severity, summary: "Llama Prompter", detail: message, life: 4000 });
  } catch (_) {
    console.log("[LlamaPrompter]", message);
  }
}

/* ------------------------------------------------------------------ */
/* skill manager dialog                                                */
/* ------------------------------------------------------------------ */
const TEMPLATE = `---
name: my-skill
description: 一句話說明這個技能做什麼，auto 模式會用它來挑選。
version: 1.0.0
tags: [t2i]
media: [text, image]
defaults:
  temperature: 0.7
  max_tokens: 400
---

你是提示詞工程師。根據使用者的文字與附件，輸出「一則」可直接使用的提示詞。
不要加上任何解釋、標題或引號。

## USER
{{text}}

[attached: {{media}}]
`;

function el(tag, style, text) {
  const node = document.createElement(tag);
  if (style) Object.assign(node.style, style);
  if (text !== undefined) node.textContent = text;
  return node;
}

function openSkillManager() {
  const overlay = el("div", {
    position: "fixed", inset: "0", background: "rgba(0,0,0,.55)",
    zIndex: "10000", display: "flex", alignItems: "center", justifyContent: "center",
  });

  const panel = el("div", {
    background: "var(--comfy-menu-bg, #202020)", color: "var(--fg-color, #ddd)",
    width: "min(920px, 94vw)", height: "min(700px, 90vh)", borderRadius: "10px",
    display: "flex", flexDirection: "column", boxShadow: "0 12px 40px rgba(0,0,0,.5)",
    font: "13px/1.5 system-ui, sans-serif", overflow: "hidden",
  });

  const header = el("div", {
    display: "flex", alignItems: "center", gap: "8px",
    padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,.12)",
  });
  header.appendChild(el("strong", { fontSize: "15px", flex: "1" }, "Llama Prompter — Skills"));

  const importButton = el("button", {}, "匯入 .md / .zip");
  const newButton = el("button", {}, "新增");
  const refreshButton = el("button", {}, "重新整理");
  const closeButton = el("button", {}, "關閉");
  for (const button of [importButton, newButton, refreshButton, closeButton]) {
    Object.assign(button.style, {
      padding: "5px 12px", cursor: "pointer", borderRadius: "5px",
      border: "1px solid rgba(255,255,255,.2)", background: "rgba(255,255,255,.07)",
      color: "inherit", font: "inherit",
    });
    header.appendChild(button);
  }

  const body = el("div", { display: "flex", flex: "1", minHeight: "0" });
  const sidebar = el("div", {
    width: "260px", display: "flex", flexDirection: "column", minHeight: "0",
    borderRight: "1px solid rgba(255,255,255,.12)",
  });
  const filter = el("input", {
    margin: "8px", padding: "5px 8px", borderRadius: "5px", font: "inherit",
    border: "1px solid rgba(255,255,255,.18)", background: "rgba(0,0,0,.25)",
    color: "inherit", outline: "none",
  });
  filter.placeholder = "搜尋技能…";
  const list = el("div", { flex: "1", overflowY: "auto" });
  sidebar.append(filter, list);
  const editorPane = el("div", { flex: "1", display: "flex", flexDirection: "column", minWidth: "0" });

  const editorBar = el("div", {
    display: "flex", gap: "8px", alignItems: "center",
    padding: "8px 12px", borderBottom: "1px solid rgba(255,255,255,.12)",
  });
  const title = el("span", { flex: "1", opacity: ".85" }, "選一個技能，或按「新增」");
  const saveButton = el("button", {}, "儲存");
  const deleteButton = el("button", {}, "刪除");
  for (const button of [saveButton, deleteButton]) {
    Object.assign(button.style, {
      padding: "4px 12px", cursor: "pointer", borderRadius: "5px",
      border: "1px solid rgba(255,255,255,.2)", background: "rgba(255,255,255,.07)",
      color: "inherit", font: "inherit",
    });
  }
  editorBar.append(title, saveButton, deleteButton);

  const editor = el("textarea", {
    flex: "1", width: "100%", boxSizing: "border-box", resize: "none", border: "0",
    padding: "12px", background: "rgba(0,0,0,.25)", color: "inherit",
    font: "12px/1.6 ui-monospace, Consolas, monospace", outline: "none",
  });

  const footer = el("div", {
    padding: "8px 14px", borderTop: "1px solid rgba(255,255,255,.12)",
    fontSize: "11px", opacity: ".65",
  }, "");

  editorPane.append(editorBar, editor, footer);
  body.append(sidebar, editorPane);
  panel.append(header, body);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  const fileInput = el("input", { display: "none" });
  fileInput.type = "file";
  fileInput.multiple = true;
  fileInput.accept = ".md,.markdown,.zip";
  panel.appendChild(fileInput);

  let current = null;

  function close() {
    overlay.remove();
    app.refreshComboInNodes?.();
  }

  const collapsed = new Set();

  async function reload(selectPath) {
    const data = await listSkills(true);
    const filterText = filter.value.trim().toLowerCase();
    list.innerHTML = "";
    footer.textContent = `skills 搜尋路徑：${(data.paths || []).join("  |  ")}`;

    const buckets = new Map();
    for (const skill of data.skills || []) {
      if (filterText && !skill.path.toLowerCase().includes(filterText)) continue;
      const group = skill.group || "(ungrouped)";
      if (!buckets.has(group)) buckets.set(group, []);
      buckets.get(group).push(skill);
    }

    if (!buckets.size) {
      list.appendChild(el("div", { padding: "14px", opacity: ".6" }, "沒有符合的技能"));
      return;
    }

    let rowToOpen = null;
    for (const [group, items] of buckets) {
      const header = el("div", {
        display: "flex", alignItems: "center", gap: "6px",
        padding: "7px 10px", cursor: "pointer", userSelect: "none",
        background: "rgba(255,255,255,.06)", fontWeight: "600", fontSize: "12px",
        position: "sticky", top: "0",
      });
      const caret = el("span", { width: "10px", opacity: ".7" },
        collapsed.has(group) ? "▸" : "▾");
      header.append(caret, el("span", { flex: "1" }, group),
        el("span", { opacity: ".55", fontWeight: "400" }, String(items.length)));
      list.appendChild(header);

      const body = el("div", { display: collapsed.has(group) ? "none" : "block" });
      header.onclick = () => {
        if (collapsed.has(group)) collapsed.delete(group);
        else collapsed.add(group);
        caret.textContent = collapsed.has(group) ? "▸" : "▾";
        body.style.display = collapsed.has(group) ? "none" : "block";
      };

      for (const skill of items) {
        const row = el("div", {
          padding: "6px 10px 6px 26px", cursor: "pointer", fontSize: "12.5px",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }, skill.name);
        row.title = skill.description || "(無說明)";
        if (skill.references) {
          row.appendChild(el("span", { opacity: ".5", fontSize: "10px" },
            `  ref×${skill.references}`));
        }
        row.onmouseenter = () => { if (current?.path !== skill.path) row.style.background = "rgba(255,255,255,.05)"; };
        row.onmouseleave = () => { if (current?.path !== skill.path) row.style.background = ""; };
        row.onclick = async () => {
          const detail = await readSkill(skill.path);
          if (detail.error) return toast(detail.error, "error");
          current = detail;
          title.textContent = `${detail.path}${detail.builtin ? "（內建，儲存會另存為使用者技能）" : ""}`;
          editor.value = detail.content || "";
          for (const child of list.querySelectorAll("[data-skill]")) child.style.background = "";
          row.style.background = "rgba(255,255,255,.12)";
        };
        row.dataset.skill = skill.path;
        if (selectPath && skill.path === selectPath) rowToOpen = row;
        body.appendChild(row);
      }
      list.appendChild(body);
    }
    if (rowToOpen) setTimeout(() => rowToOpen.click(), 0);
  }

  closeButton.onclick = close;
  overlay.onclick = (event) => { if (event.target === overlay) close(); };
  refreshButton.onclick = () => reload(current?.path);
  filter.oninput = () => reload();
  importButton.onclick = () => fileInput.click();
  newButton.onclick = () => {
    current = { name: "my-skill", path: "user/my-skill", builtin: false };
    title.textContent = "新技能（改好 front matter 的 name 再儲存）";
    editor.value = TEMPLATE;
  };

  fileInput.onchange = async () => {
    if (!fileInput.files?.length) return;
    const result = await importSkillFiles(fileInput.files);
    fileInput.value = "";
    if (result.errors?.length) toast(result.errors.join("\n"), "warn");
    if (result.imported?.length) toast(`已匯入 ${result.imported.length} 個技能`, "success");
    await reload();
  };

  saveButton.onclick = async () => {
    const content = editor.value;
    const match = content.match(/^\s*---\s*[\s\S]*?\bname\s*:\s*([^\n#]+)/);
    const name = (match ? match[1] : current?.name || "my-skill").trim().replace(/^["']|["']$/g, "");
    const result = await saveSkill(name, content);
    if (result.error) return toast(result.error, "error");
    toast(`已儲存 ${result.name}`, "success");
    await reload(result.name);
  };

  deleteButton.onclick = async () => {
    if (!current?.path) return;
    if (!confirm(`確定刪除技能「${current.path}」？`)) return;
    const result = await deleteSkill(current.path);
    if (result.error) return toast(result.error, "error");
    current = null;
    editor.value = "";
    title.textContent = "已刪除";
    await reload();
  };

  reload();
}

/* ------------------------------------------------------------------ */
/* system prompt manager                                               */
/* ------------------------------------------------------------------ */
async function listPresets() {
  const response = await api.fetchApi(`${PREFIX}/presets`);
  return (await response.json()).presets || [];
}

async function savePreset(name, text) {
  const response = await api.fetchApi(`${PREFIX}/preset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, text }),
  });
  return await response.json();
}

async function deletePreset(name) {
  const response = await api.fetchApi(`${PREFIX}/preset?name=${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  return await response.json();
}

function openPresetManager() {
  const overlay = el("div", {
    position: "fixed", inset: "0", background: "rgba(0,0,0,.55)",
    zIndex: "10000", display: "flex", alignItems: "center", justifyContent: "center",
  });
  const panel = el("div", {
    background: "var(--comfy-menu-bg, #202020)", color: "var(--fg-color, #ddd)",
    width: "min(760px, 92vw)", height: "min(560px, 88vh)", borderRadius: "10px",
    display: "flex", flexDirection: "column", boxShadow: "0 12px 40px rgba(0,0,0,.5)",
    font: "13px/1.5 system-ui, sans-serif", overflow: "hidden",
  });

  const header = el("div", {
    display: "flex", alignItems: "center", gap: "8px",
    padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,.12)",
  });
  header.appendChild(el("strong", { fontSize: "15px", flex: "1" },
    "Llama Prompter — System prompts"));
  const newButton = el("button", {}, "新增");
  const closeButton = el("button", {}, "關閉");
  for (const button of [newButton, closeButton]) {
    Object.assign(button.style, {
      padding: "5px 12px", cursor: "pointer", borderRadius: "5px",
      border: "1px solid rgba(255,255,255,.2)", background: "rgba(255,255,255,.07)",
      color: "inherit", font: "inherit",
    });
    header.appendChild(button);
  }

  const body = el("div", { display: "flex", flex: "1", minHeight: "0" });
  const list = el("div", {
    width: "220px", overflowY: "auto", borderRight: "1px solid rgba(255,255,255,.12)",
  });
  const right = el("div", { flex: "1", display: "flex", flexDirection: "column", minWidth: "0" });

  const bar = el("div", {
    display: "flex", gap: "8px", padding: "8px 12px",
    borderBottom: "1px solid rgba(255,255,255,.12)",
  });
  const nameInput = el("input", {
    flex: "1", padding: "5px 8px", borderRadius: "5px", font: "inherit",
    border: "1px solid rgba(255,255,255,.18)", background: "rgba(0,0,0,.25)",
    color: "inherit", outline: "none",
  });
  nameInput.placeholder = "名稱";
  const saveButton = el("button", {}, "儲存");
  const deleteButton = el("button", {}, "刪除");
  for (const button of [saveButton, deleteButton]) {
    Object.assign(button.style, {
      padding: "4px 12px", cursor: "pointer", borderRadius: "5px",
      border: "1px solid rgba(255,255,255,.2)", background: "rgba(255,255,255,.07)",
      color: "inherit", font: "inherit",
    });
  }
  bar.append(nameInput, saveButton, deleteButton);

  const editor = el("textarea", {
    flex: "1", width: "100%", boxSizing: "border-box", resize: "none", border: "0",
    padding: "12px", background: "rgba(0,0,0,.25)", color: "inherit",
    font: "12px/1.6 ui-monospace, Consolas, monospace", outline: "none",
  });
  editor.placeholder = "系統提示內容…";

  right.append(bar, editor);
  body.append(list, right);
  panel.append(header, body);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  function close() {
    overlay.remove();
    app.refreshComboInNodes?.();
  }
  closeButton.onclick = close;
  overlay.onclick = (event) => { if (event.target === overlay) close(); };
  newButton.onclick = () => { nameInput.value = ""; editor.value = ""; nameInput.focus(); };

  async function reload(select) {
    const items = await listPresets();
    list.innerHTML = "";
    for (const item of items) {
      const row = el("div", {
        padding: "8px 12px", cursor: "pointer", fontSize: "12.5px",
        borderBottom: "1px solid rgba(255,255,255,.06)",
      }, item.name);
      if (item.builtin) {
        row.appendChild(el("span", {
          marginLeft: "6px", fontSize: "10px", padding: "1px 5px",
          borderRadius: "3px", background: "rgba(120,170,255,.22)",
        }, "內建"));
      }
      row.title = item.text;
      row.onclick = () => {
        nameInput.value = item.name;
        editor.value = item.text;
        for (const child of list.children) child.style.background = "";
        row.style.background = "rgba(255,255,255,.1)";
      };
      if (select && item.name === select) setTimeout(() => row.click(), 0);
      list.appendChild(row);
    }
  }

  saveButton.onclick = async () => {
    const result = await savePreset(nameInput.value, editor.value);
    if (result.error) return toast(result.error, "error");
    toast(`已儲存 ${nameInput.value}`, "success");
    await reload(nameInput.value);
  };
  deleteButton.onclick = async () => {
    if (!nameInput.value.trim()) return;
    if (!confirm(`確定刪除「${nameInput.value}」？`)) return;
    await deletePreset(nameInput.value);
    nameInput.value = "";
    editor.value = "";
    await reload();
  };

  reload();
}

/* ------------------------------------------------------------------ */
/* settings                                                            */
/* ------------------------------------------------------------------ */
function makeButton(label, onClick) {
  return () => {
    const button = document.createElement("button");
    button.textContent = label;
    Object.assign(button.style, {
      padding: "4px 12px", cursor: "pointer", borderRadius: "5px",
      border: "1px solid rgba(255,255,255,.25)", background: "rgba(255,255,255,.08)",
      color: "inherit", font: "inherit",
    });
    button.onclick = onClick;
    return button;
  };
}

const CATEGORY_SERVER = ["Llama Prompter", "Server"];
const CATEGORY_DEFAULTS = ["Llama Prompter", "Defaults"];
const CATEGORY_SKILLS = ["Llama Prompter", "Skills"];

function setting(id, key, name, type, defaultValue, category, attrs = {}) {
  return {
    id,
    name,
    type,
    defaultValue,
    category: [...category, name],
    ...attrs,
    onChange: (value) => {
      if (pushing) return;
      pushConfig({ [key]: value }).catch((error) => toast(String(error), "error"));
    },
  };
}

app.registerExtension({
  name: EXT,

  settings: [
    setting("LlamaPrompter.base_url", "base_url", "Server URL", "text",
      "https://g00392.asuscomm.com:10011", CATEGORY_SERVER,
      { tooltip: "llama-server 位址，結尾可省略 /v1。" }),
    setting("LlamaPrompter.model", "model", "Model", "text", "", CATEGORY_SERVER,
      { tooltip: "留空 = 使用伺服器目前載入的模型。" }),
    setting("LlamaPrompter.api_key", "api_key", "API Key", "text", "", CATEGORY_SERVER,
      { tooltip: "llama-server 以 --api-key 啟動時才需要。" }),
    setting("LlamaPrompter.timeout", "timeout", "Timeout (s)", "number", 300, CATEGORY_SERVER),
    setting("LlamaPrompter.verify_ssl", "verify_ssl", "Verify SSL", "boolean", true, CATEGORY_SERVER,
      { tooltip: "自簽憑證請關閉。" }),
    setting("LlamaPrompter.stream", "stream", "Stream responses", "boolean", true, CATEGORY_SERVER),
    {
      id: "LlamaPrompter.test",
      name: "Test connection",
      category: [...CATEGORY_SERVER, "Test connection"],
      type: makeButton("測試連線", async () => {
        const settings = app.ui.settings;
        const info = await testConnection({
          base_url: settings.getSettingValue("LlamaPrompter.base_url"),
          api_key: settings.getSettingValue("LlamaPrompter.api_key"),
          verify_ssl: settings.getSettingValue("LlamaPrompter.verify_ssl"),
          timeout: 20,
        });
        if (info.ok) {
          toast(`OK — models: ${(info.models || []).join(", ") || "n/a"}; n_ctx: ${info.n_ctx ?? "?"}`,
            "success");
        } else {
          toast(`連線失敗：${info.error || info.health?.error || "unknown"}`, "error");
        }
      }),
    },

    setting("LlamaPrompter.temperature", "temperature", "Temperature", "slider", 0.7,
      CATEGORY_DEFAULTS, { attrs: { min: 0, max: 2, step: 0.01 } }),
    setting("LlamaPrompter.top_p", "top_p", "Top P", "slider", 0.95, CATEGORY_DEFAULTS,
      { attrs: { min: 0, max: 1, step: 0.01 } }),
    setting("LlamaPrompter.top_k", "top_k", "Top K", "number", 40, CATEGORY_DEFAULTS),
    setting("LlamaPrompter.min_p", "min_p", "Min P", "slider", 0.05, CATEGORY_DEFAULTS,
      { attrs: { min: 0, max: 1, step: 0.01 } }),
    setting("LlamaPrompter.max_tokens", "max_tokens", "Max tokens", "number", 512, CATEGORY_DEFAULTS),
    setting("LlamaPrompter.max_frames", "max_frames", "Max frames", "number", 8, CATEGORY_DEFAULTS,
      { tooltip: "影片抽幀張數上限；顯存不足就調小。" }),
    setting("LlamaPrompter.max_image_side", "max_image_side", "Max image side", "number", 768,
      CATEGORY_DEFAULTS, { tooltip: "影像長邊上限，直接影響 vision token 數。" }),
    setting("LlamaPrompter.strip_thinking", "strip_thinking", "Strip <think> blocks", "boolean",
      true, CATEGORY_DEFAULTS),
    setting("LlamaPrompter.debug", "debug", "Debug logging", "boolean", false, CATEGORY_DEFAULTS),

    setting("LlamaPrompter.default_skill", "default_skill", "Default skill", "text", "(none)",
      CATEGORY_SKILLS, { tooltip: "新建 Llama Skill 節點時的預設選項。" }),
    {
      id: "LlamaPrompter.extra_skill_dirs",
      name: "Extra skill folders",
      category: [...CATEGORY_SKILLS, "Extra skill folders"],
      type: "text",
      defaultValue: "",
      tooltip: "額外掃描的技能資料夾，用 ; 分隔。",
      onChange: (value) => {
        if (pushing) return;
        const dirs = String(value || "").split(";").map((s) => s.trim()).filter(Boolean);
        pushConfig({ extra_skill_dirs: dirs }).catch((error) => toast(String(error), "error"));
      },
    },
    {
      id: "LlamaPrompter.manage_skills",
      name: "Manage skills",
      category: [...CATEGORY_SKILLS, "Manage skills"],
      type: makeButton("開啟 Skill 管理器", openSkillManager),
    },

    {
      id: "LlamaPrompter.manage_presets",
      name: "System prompts",
      category: ["Llama Prompter", "System prompts", "Manage"],
      type: makeButton("開啟 System prompt 管理器", openPresetManager),
    },
    {
      id: "LlamaPrompter.dynamic_slots",
      name: "Grow AIO slots as you connect",
      category: ["Llama Prompter", "AIO", "Grow slots"],
      type: "boolean",
      defaultValue: true,
      tooltip: "AIO 節點只顯示已接的插槽加一個備用。關掉會一次顯示全部。",
    },
    setting("LlamaPrompter.max_images", "max_images", "Max images", "number", 9,
      ["Llama Prompter", "AIO"], { tooltip: "改完要按 R 重新整理節點定義。" }),
    setting("LlamaPrompter.max_videos", "max_videos", "Max videos", "number", 3,
      ["Llama Prompter", "AIO"]),
    setting("LlamaPrompter.max_audios", "max_audios", "Max audio clips", "number", 3,
      ["Llama Prompter", "AIO"]),
    setting("LlamaPrompter.max_skills", "max_skills", "Max skills", "number", 5,
      ["Llama Prompter", "AIO"]),
    setting("LlamaPrompter.include_references", "include_references",
      "Send skill references", "boolean", false, ["Llama Prompter", "AIO"],
      { tooltip: "把技能的 references/ 一起送出。更貼近原技能，但 prompt 會大很多也慢很多。" }),
    setting("LlamaPrompter.max_video_seconds", "max_video_seconds",
      "Max seconds per video", "number", 15, ["Llama Prompter", "AIO"]),
    setting("LlamaPrompter.max_audio_seconds_total", "max_audio_seconds_total",
      "Max audio seconds total", "number", 15, ["Llama Prompter", "AIO"]),
  ],

  commands: [
    {
      id: "LlamaPrompter.OpenSkillManager",
      label: "Llama Prompter: 開啟 Skill 管理器",
      function: openSkillManager,
    },
  ],

  menuCommands: [
    { path: ["Extensions"], commands: ["LlamaPrompter.OpenSkillManager"] },
  ],

  async setup() {
    // Pull the backend config into the settings store without re-posting it.
    try {
      const data = await getConfig();
      backendConfig = data.config;
      pushing = true;
      const settings = app.ui.settings;
      const map = {
        "LlamaPrompter.base_url": "base_url",
        "LlamaPrompter.model": "model",
        "LlamaPrompter.api_key": "api_key",
        "LlamaPrompter.timeout": "timeout",
        "LlamaPrompter.verify_ssl": "verify_ssl",
        "LlamaPrompter.stream": "stream",
        "LlamaPrompter.temperature": "temperature",
        "LlamaPrompter.top_p": "top_p",
        "LlamaPrompter.top_k": "top_k",
        "LlamaPrompter.min_p": "min_p",
        "LlamaPrompter.max_tokens": "max_tokens",
        "LlamaPrompter.max_frames": "max_frames",
        "LlamaPrompter.max_image_side": "max_image_side",
        "LlamaPrompter.strip_thinking": "strip_thinking",
        "LlamaPrompter.debug": "debug",
        "LlamaPrompter.default_skill": "default_skill",
        "LlamaPrompter.max_images": "max_images",
        "LlamaPrompter.max_videos": "max_videos",
        "LlamaPrompter.max_audios": "max_audios",
        "LlamaPrompter.max_skills": "max_skills",
        "LlamaPrompter.include_references": "include_references",
        "LlamaPrompter.max_video_seconds": "max_video_seconds",
        "LlamaPrompter.max_audio_seconds_total": "max_audio_seconds_total",
      };
      const put = async (id, value) => {
        if (value === undefined) return;
        if (typeof settings.setSettingValueAsync === "function") {
          await settings.setSettingValueAsync(id, value);
        } else {
          settings.setSettingValue(id, value);
        }
      };
      for (const [id, key] of Object.entries(map)) await put(id, backendConfig[key]);
      await put("LlamaPrompter.extra_skill_dirs",
        (backendConfig.extra_skill_dirs || []).join("; "));
    } catch (error) {
      console.warn("[LlamaPrompter] cannot load backend config:", error);
    } finally {
      pushing = false;
    }

    api.addEventListener("llama_prompter.stream", ({ detail }) => {
      const node = app.graph.getNodeById(Number(detail.node));
      if (node?.llamaPreview) {
        node.llamaPreview.value = detail.text;
        app.graph.setDirtyCanvas(true, false);
      }
    });

    api.addEventListener("llama_prompter.done", ({ detail }) => {
      const node = app.graph.getNodeById(Number(detail.node));
      if (node?.llamaPreview) {
        node.llamaPreview.value = detail.text;
        node.llamaInfo = detail.info;
        app.graph.setDirtyCanvas(true, false);
      }
    });
  },
});

/* ------------------------------------------------------------------ */
/* AIO node: slots that appear as you fill them                        */
/* ------------------------------------------------------------------ */
const GROWABLE_INPUTS = ["image_", "video_", "audio_"];
const GROWABLE_WIDGETS = ["skill_"];
const NONE_SKILL = "(none)";

function numbered(items, prefix) {
  return items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => new RegExp(`^${prefix}\\d+$`).test(item.name))
    .sort((a, b) => Number(a.item.name.slice(prefix.length)) - Number(b.item.name.slice(prefix.length)));
}

function growablePrefix(name) {
  return GROWABLE_INPUTS.find((prefix) => new RegExp(`^${prefix}\\d+$`).test(name)) || null;
}

function hideWidget(node, widget) {
  if (widget.llamaHidden) return;
  widget.llamaHidden = true;
  widget.llamaType = widget.type;
  widget.llamaCompute = widget.computeSize;
  widget.type = "llamaHidden";
  widget.computeSize = () => [0, -4];
}

function showWidget(widget) {
  if (!widget.llamaHidden) return;
  widget.llamaHidden = false;
  widget.type = widget.llamaType;
  widget.computeSize = widget.llamaCompute;
}

/** Keep every filled slot plus exactly one spare.
 *
 * Only unconnected slots are ever removed, and removal goes through
 * litegraph's own removeInput so link indices are fixed up for us. A connected
 * slot is never touched, so this can not rewire anything.
 */
function growSlots(node) {
  if (!node || node.llamaNoGrow) return;
  const catalogue = node.llamaAllInputs || [];
  if (!catalogue.length) return;

  const connected = new Set();
  for (const slot of node.inputs || []) {
    if (slot.link != null) connected.add(slot.name);
  }

  const wanted = new Set();
  for (const slot of catalogue) {
    if (!growablePrefix(slot.name)) wanted.add(slot.name);
  }
  for (const name of connected) wanted.add(name);
  for (const prefix of GROWABLE_INPUTS) {
    const names = catalogue
      .filter((slot) => new RegExp(`^${prefix}\\d+$`).test(slot.name))
      .map((slot) => slot.name);
    let lastUsed = -1;
    names.forEach((name, position) => { if (connected.has(name)) lastUsed = position; });
    const spare = names[lastUsed + 1];
    if (spare) wanted.add(spare);
  }

  for (let index = (node.inputs || []).length - 1; index >= 0; index--) {
    const slot = node.inputs[index];
    if (slot.link == null && growablePrefix(slot.name) && !wanted.has(slot.name)) {
      node.removeInput(index);
    }
  }
  const present = new Set((node.inputs || []).map((slot) => slot.name));
  for (const slot of catalogue) {
    if (wanted.has(slot.name) && !present.has(slot.name)) {
      node.addInput(slot.name, slot.type);
    }
  }

  for (const prefix of GROWABLE_WIDGETS) {
    const widgets = numbered(node.widgets || [], prefix);
    if (!widgets.length) continue;
    let lastUsed = -1;
    widgets.forEach(({ item }, position) => {
      if (item.value && item.value !== NONE_SKILL) lastUsed = position;
    });
    const keep = Math.min(lastUsed + 2, widgets.length);
    widgets.forEach(({ item }, position) => {
      if (position < keep) showWidget(item);
      else hideWidget(node, item);
    });
  }

  node.setSize(node.computeSize());
  node.setDirtyCanvas(true, true);
}

app.registerExtension({
  name: "LlamaPrompter.AIO",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== "LlamaPromptAIO") return;

    // Remember the full slot list so hidden ones can come back.
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onCreated?.apply(this, arguments);
      // The full slot list, so a removed spare can be added back later.
      this.llamaAllInputs = (this.inputs || []).map(({ name, type }) => ({ name, type }));
      this.llamaNoGrow = app.ui.settings.getSettingValue("LlamaPrompter.dynamic_slots") === false;
      for (const prefix of GROWABLE_WIDGETS) {
        for (const { item } of numbered(this.widgets || [], prefix)) {
          const node = this;
          const original = item.callback;
          item.callback = function () {
            const value = original?.apply(this, arguments);
            growSlots(node);
            return value;
          };
        }
      }
      requestAnimationFrame(() => growSlots(this));
      return result;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = onConfigure?.apply(this, arguments);
      requestAnimationFrame(() => growSlots(this));
      return result;
    };

    const onConnectionsChange = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function () {
      const result = onConnectionsChange?.apply(this, arguments);
      requestAnimationFrame(() => growSlots(this));
      return result;
    };
  },
});

/* ------------------------------------------------------------------ */
/* node UI: live output preview                                        */
/* ------------------------------------------------------------------ */
const PREVIEW_NODES = new Set([
  "LlamaPrompter", "LlamaVideoPrompter", "LlamaPreviewText", "LlamaTestConnection",
]);

app.registerExtension({
  name: "LlamaPrompter.NodeUI",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!PREVIEW_NODES.has(nodeData?.name)) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onCreated?.apply(this, arguments);
      const widget = ComfyWidgets.STRING(
        this, "output", ["STRING", { multiline: true }], app
      ).widget;
      widget.inputEl.readOnly = true;
      widget.inputEl.style.opacity = "0.8";
      widget.inputEl.placeholder = "（執行後顯示結果）";
      widget.serializeValue = () => undefined;
      this.llamaPreview = widget;
      if (nodeData.name === "LlamaPrompter") this.size = [460, 480];
      if (nodeData.name === "LlamaVideoPrompter") this.size = [500, 560];
      return result;
    };

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const text = message?.text;
      if (this.llamaPreview && text) {
        this.llamaPreview.value = Array.isArray(text) ? text.join("") : String(text);
      }
    };
  },
});
