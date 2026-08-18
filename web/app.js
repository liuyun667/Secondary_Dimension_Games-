// 二游毕业指导 · 前端逻辑（纯中文界面）
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const USER = "本机";        // 本机账户标识
let games = [];             // 游戏列表（含武器/装备称谓）
let gameId = null;          // 当前游戏
let assets = [];            // 识别/加载的资产
let characters = [];        // 当前游戏角色
let recSelected = new Set();// 配装推荐选中的角色
let teams = [];             // 队伍列表 [{members:Set, weights:{}}]
let standardCharId = null;
let customStats = [];        // 自定义词条列表 [{name, value}]

const getGame = () => games.find((g) => g.id === gameId) || {};

// ── 基础请求 ───────────────────────────────────────
async function api(path, method = "GET", body = null) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const resp = await fetch(path, opt);
  if (!resp.ok) {
    let msg = "请求失败，请稍后重试";
    try { const e = await resp.json(); if (e && e.detail) msg = e.detail; } catch (_) {}
    throw new Error(msg);
  }
  return resp.json();
}

// ── 面板切换 ───────────────────────────────────────
function initNav() {
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".nav-btn").forEach((b) => b.classList.remove("active"));
      $$(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $("#panel-" + btn.dataset.section.replace("panel-", "")).classList.add("active");
      // 进入「毕业标准」时按当前角色刷新置灰（无用属性变灰）
      if (btn.dataset.section === "panel-standard") {
        standardCharId = Number($("#stdChar").value) || null;
        refreshKeyStats();
      }
    });
  });
}

// ── 开局选游戏 ─────────────────────────────────────
function showOnboarding() {
  const wrap = $("#gameCards");
  wrap.innerHTML = "";
  games.forEach((g) => {
    const card = document.createElement("button");
    card.className = "game-card";
    card.innerHTML = `<b>${g.name}</b><span>${g.weapon_name} · ${g.equipment_name}</span>`;
    card.addEventListener("click", () => setGame(g.id));
    wrap.appendChild(card);
  });
  $("#onboarding").classList.remove("hidden");
}

function setGame(id) {
  gameId = id;
  localStorage.setItem("gyz_game", String(id));
  $("#onboarding").classList.add("hidden");
  applyGame();
}

async function loadGames() {
  games = await api("/api/v1/games");
  const sel = $("#gameSelect");
  sel.innerHTML = "";
  games.forEach((g) => {
    const o = document.createElement("option");
    o.value = g.id; o.textContent = g.name;
    sel.appendChild(o);
  });
  sel.addEventListener("change", () => setGame(Number(sel.value)));
}

async function applyGame() {
  if (gameId == null) return;
  $("#gameSelect").value = gameId;
  recSelected.clear();
  teams = [];
  try { await loadCharacters(); } catch (e) { console.error("加载角色失败：", e); }
  renderTeams();
  // 游戏切换后同步毕业标准选中角色与置灰状态
  standardCharId = Number($("#stdChar").value) || null;
  refreshKeyStats();
}

async function loadCharacters() {
  characters = await api("/api/v1/characters?game_id=" + gameId);
  ["gradChar", "stdChar"].forEach((id) => {
    const s = $("#" + id);
    s.innerHTML = "";
    characters.forEach((c) => {
      const o = document.createElement("option");
      o.value = c.id; o.textContent = c.name;
      s.appendChild(o);
    });
  });
  renderRecChars();
}

// ── 资产识别 ───────────────────────────────────────
function initAssets() {
  $(".mode-switch").addEventListener("click", (e) => {
    const btn = e.target.closest(".mode-btn");
    if (!btn) return;
    $$(".mode-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $("#mode-screen").classList.toggle("hidden", btn.dataset.mode !== "screen");
    $("#mode-text").classList.toggle("hidden", btn.dataset.mode !== "text");
    $("#mode-image").classList.toggle("hidden", btn.dataset.mode !== "image");
    $("#mode-auto").classList.toggle("hidden", btn.dataset.mode !== "auto");
  });

  $("#btnFillSample").addEventListener("click", () => {
    $("#assetText").value = [
      "胡桃 Lv.90 ★5", "护摩之杖 Lv.90 ★5", "祭礼剑 Lv.80 ★4", "和璞鸢 Lv.80 ★5",
      "炽烈的炎之魔女（生命值）花 暴击率+7.8% 暴击伤害+14.0%",
      "炽烈的炎之魔女（火元素伤害加成）杯", "炽烈的炎之魔女（暴击率）头",
      "绝缘之旗印（攻击力）沙", "摩拉 x999999",
    ].join("\n");
  });

  $("#btnAnalyzeText").addEventListener("click", async () => {
    const lines = $("#assetText").value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!lines.length) return alert("请先粘贴要识别的文本");
    await runAnalyze({ game_id: gameId, text_lines: lines });
  });

  $("#btnAnalyzeImage").addEventListener("click", () => {
    const f = $("#fileInput").files[0];
    if (!f) return alert("请先选择截图");
    const reader = new FileReader();
    reader.onload = async () => {
      const image = String(reader.result).split(",")[1];
      try { await runAnalyze({ game_id: gameId, image }, true); }
      catch (e) { showAssetError(e.message + "，可改用「粘贴文本」。"); }    };
    reader.readAsDataURL(f);
  });

  const dz = $(".drop-zone");
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.style.borderColor = "#3b82f6"; });
  dz.addEventListener("dragleave", () => { dz.style.borderColor = ""; });
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files[0]) { $("#fileInput").files = e.dataTransfer.files; $("#dropText").textContent = e.dataTransfer.files[0].name; }
  });
  $("#fileInput").addEventListener("change", () => {
    $("#dropText").textContent = $("#fileInput").files[0] ? $("#fileInput").files[0].name : "点击选择截图，或拖拽到此处";
  });

  // ── 自动导入（导出文件 / 粘贴数据，采集插件）──────────
  const cf = $("#collectFile");
  cf.addEventListener("change", () => {
    $("#collectFileText").textContent = cf.files[0] ? cf.files[0].name : "选择导出文件（JSON），或拖拽到此处";
  });
  const cfZone = cf.closest(".drop-zone");
  cfZone.addEventListener("dragover", (e) => { e.preventDefault(); cfZone.style.borderColor = "#3b82f6"; });
  cfZone.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files[0]) { cf.files = e.dataTransfer.files; $("#collectFileText").textContent = cf.files[0].name; }
  });

  $("#btnCollectFile").addEventListener("click", () => {
    const f = cf.files[0];
    if (!f) return alert("请先选择导出文件");
    const reader = new FileReader();
    reader.onload = async () => {
      try { await runCollect({ method: "file", payload: { content: String(reader.result) } }); }
      catch (e) { showAssetError(e.message); }
    };
    reader.readAsText(f, "utf-8");
  });

  $("#btnCollectText").addEventListener("click", async () => {
    const text = $("#collectText").value.trim();
    if (!text) return alert("请先粘贴导出数据");
    try { await runCollect({ method: "clipboard", payload: { text } }); }
    catch (e) { showAssetError(e.message); }
  });

  // 导入测试数据：点击时后端实时生成（66 角色/150 武器/1000 圣遗物/400 材料）
  $("#btnTestData").addEventListener("click", async () => {
    const btn = $("#btnTestData");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "正在生成测试数据…（约几秒）";
    try {
      const r = await api("/api/v1/test-data/generate", "POST",
        { session: "test_demo", game_id: gameId });
      const list = (await api(`/api/v1/assets?user_id=${encodeURIComponent(r.session)}&game_id=${gameId}`)).assets || [];
      assets = list;
      renderAssets(assets, []);
      try { await api("/api/v1/assets", "POST", { user_id: USER, game_id: gameId, assets }); } catch (e) {}
      alert(`已生成并载入 ${r.generated} 项测试数据（${r.created_at ? new Date(r.created_at).toLocaleString() : ""}）`);
    } catch (e) { showAssetError(e.message); }
    finally { btn.disabled = false; btn.textContent = orig; }
  });

  $("#btnSaveAssets").addEventListener("click", async () => {
    if (!assets.length) return alert("还没有可保存的资产，请先识别");
    await api("/api/v1/assets", "POST", { user_id: USER, game_id: gameId, assets });
    alert("已保存 " + assets.length + " 项资产");
  });

  $("#btnClearAssets").addEventListener("click", () => {
    assets = [];
    renderAssets([], []);
  });

  $("#btnDeleteAssets").addEventListener("click", async () => {
    if (!confirm("确定删除已保存的该游戏账户数据吗？此操作不可恢复。")) return;
    const r = await api(`/api/v1/assets?user_id=${encodeURIComponent(USER)}&game_id=${gameId}`, "DELETE");
    assets = [];
    renderAssets([], []);
    alert("已删除 " + r.deleted + " 条记录");
  });
}

function showAssetError(msg) {
  $("#assetResult").innerHTML = `<div class="card"><span class="tag bad">识别失败</span> ${msg}</div>`;
  $("#assetResult").classList.remove("hidden");
}

async function runAnalyze(payload, merge = false) {
  $("#assetResult").classList.remove("hidden");
  $("#assetResult").innerHTML = `<div class="loading">正在识别…</div>`;
  const r = await api("/api/v1/analyze", "POST", payload);
  applyAssets(r.assets || [], merge, r.unresolved || []);
}

async function runCollect(body) {
  $("#assetResult").classList.remove("hidden");
  $("#assetResult").innerHTML = `<div class="loading">正在导入…</div>`;
  const r = await api("/api/v1/collect", "POST", { game_id: gameId, ...body });
  applyAssets(r.assets || [], true, r.unresolved || []);
}

function applyAssets(list, merge, unresolved) {
  if (merge) {
    // 追加/刷新模式（组D2）：重复项刷新数据（更新等级/数值），新项追加
    const idx = new Map(assets.map((a, i) => [a.type + "|" + a.name, i]));
    for (const a of list) {
      const k = a.type + "|" + a.name;
      if (idx.has(k)) {
        const old = assets[idx.get(k)];
        assets[idx.get(k)] = Object.assign({}, old, a, {
          level: a.level != null ? a.level : old.level,
        });
      } else {
        idx.set(k, assets.length);
        assets.push(a);
      }
    }
  } else {
    assets = list;  // 替换模式（粘贴文本/导入示例账户用）
  }
  renderAssets(assets, unresolved || []);
}

async function loadSavedAssets() {
  const r = await api(`/api/v1/assets?user_id=${encodeURIComponent(USER)}&game_id=${gameId}`);
  assets = r.assets || [];
  if (assets.length) renderAssets(assets, []);
}

// 副词条达标度（启发式质量初判，非角色标准判定）：
// 达标 = ≥3 条且全部有数值、含暴击率/暴击伤害之一；部分 = ≥2 条有数值；其余未达标
function substatGrade(a) {
  const subs = a.substats || [];
  const named = subs.filter((s) => s && typeof s === "object" && s.name);
  const valued = named.filter((s) => s.value != null);
  const names = new Set(named.map((s) => s.name));
  const hasCrit = names.has("暴击率") || names.has("暴击伤害");
  if (valued.length >= 3 && hasCrit && valued.length === named.length) {
    return { grade: "达标", text: `${valued.length} 条有效副词条且含双暴词条` };
  }
  if (valued.length >= 2) {
    return { grade: "部分", text: `${valued.length} 条有数值` };
  }
  if (named.length && valued.length < named.length) {
    return { grade: "未达标", text: "部分副词条数值未识别" };
  }
  return { grade: "未达标", text: "副词条不足或无数值" };
}

function renderAssets(list, unresolved) {
  updateAssetSummary();   // 侧边栏账户资产统计（四类 + 空状态）
  const g = getGame();
  const wName = g.weapon_name || "武器";
  const eName = g.equipment_name || "装备";
  const groups = {};
  list.forEach((a) => {
    let k = a.type;
    if (k === "武器") k = wName;
    else if (k === "装备") k = eName;
    (groups[k] = groups[k] || []).push(a);
  });

  let html = "";
  Object.entries(groups).forEach(([k, arr]) => {
    html += `<div class="card"><div class="card-title">${k}（${arr.length}）</div>`;
    arr.forEach((a) => {
      const bits = [`<b>${a.name}</b>`];
      if (a.rarity) bits.push("★".repeat(a.rarity));
      if (a.type === "角色") {
        if (a.level) bits.push(`等级 ${a.level}`);
        if (a.constellation != null) bits.push(`命座 ${a.constellation}`);
        if (a.talents && a.talents.length) bits.push(`技能 普攻${a.talents[0]}/战绩${a.talents[1]}/爆发${a.talents[2]}`);
      } else if (a.type === "武器") {
        if (a.weapon_type) bits.push(`类型 ${a.weapon_type}`);
        if (a.level) bits.push(`等级 ${a.level}`);
        if (a.refinement != null) bits.push(`精炼 ${a.refinement}`);
        if (a.base_atk) bits.push(`基础攻击 ${a.base_atk}`);
        if (a.main_stat) {
          bits.push(`主词条 ${a.main_stat}${a.main_stat_value != null ? " " + a.main_stat_value + "%" : ""}`);
        }
        if (a.passive) bits.push(`被动：${a.passive}`);
      } else if (a.type === "装备") {
        if (a.set) bits.push(`套装 ${a.set}`);
        if (a.slot) bits.push(`${a.slot}位`);
        if (a.level != null) bits.push(`等级 ${a.level}`);
        if (a.artifact_level) bits.push(`强化 +${a.artifact_level}`);
        if (a.main_stat) {
          let ms = `主词条 ${a.main_stat}`;
          if (a.main_stat_value != null && a.main_stat_value !== "") ms += ` ${a.main_stat_value}`;
          bits.push(ms);
        }
        if (a.substats && a.substats.length) {
          bits.push("副词条：" + a.substats.map((s) => {
            if (s && typeof s === "object" && s.name) {
              return s.value != null ? `${s.name} +${s.value}${s.percent ? "%" : ""}` : s.name;
            }
            return s;
          }).join("、"));
        }
        const g = substatGrade(a);
        const cls = g.grade === "达标" ? "ok" : g.grade === "部分" ? "warn" : "bad";
        bits.push(`<span class="tag ${cls}" title="${g.text}">副词条${g.grade}</span>`);
      } else if (a.type === "材料") {
        if (a.material_qty != null) bits.push(`数量 ${a.material_qty}`);
        if (a.source) bits.push(`来源 ${a.source}`);
      }
      html += `<div class="asset-item" data-idx="${assets.indexOf(a)}" title="点击查看详情" style="padding:5px 8px;border-top:1px solid #f0f1f3">${bits.join("　")}</div>`;
    });
    html += "</div>";
  });
  if (unresolved && unresolved.length) {
    html += `<div class="card"><div class="card-title"><span class="tag warn">未识别</span></div><ul class="list">`;
    unresolved.forEach((u) => { html += `<li>${u}</li>`; });
    html += "</ul></div>";
  }
  if (!html) html = `<div class="card">暂无资产，请先识别或读取已保存数据。</div>`;
  $("#assetResult").innerHTML = html;
  $("#assetResult").classList.remove("hidden");
}

// ── 资产详情弹窗（点击资产项查看完整信息）────────────
function showAssetDetail(a) {
  if (!a) return;
  const g = getGame() || {};
  const rows = [];
  const add = (k, v) => { if (v != null && v !== "") rows.push(`<div class="detail-row"><span class="k">${k}</span><span class="v">${v}</span></div>`); };
  const star = (n) => "★".repeat(n || 0);
  if (a.type === "角色") {
    add("星级", star(a.rarity));
    add("等级", a.level != null ? `Lv.${a.level}` : null);
    add("命座", a.constellation != null ? `${a.constellation} 命` : null);
    if (a.talents && a.talents.length === 3) {
      add("技能等级", `普通攻击 ${a.talents[0]} ／ 元素战绩 ${a.talents[1]} ／ 元素爆发 ${a.talents[2]}`);
    }
  } else if (a.type === "武器") {
    add("星级", star(a.rarity));
    add("武器类型", a.weapon_type);
    add("等级", a.level != null ? `Lv.${a.level}` : null);
    add("精炼等级", a.refinement != null ? `${a.refinement} 阶` : null);
    add("基础攻击力", a.base_atk);
    add("主词条", a.main_stat ? `${a.main_stat} ${a.main_stat_value != null ? a.main_stat_value + "%" : ""}` : null);
    add("被动", a.passive);
  } else if (a.type === "装备") {
    add("套装名称", a.set || a.name);
    add("部位", a.slot);
    add("星级", star(a.rarity));
    add("等级", a.level != null ? `Lv.${a.level}` : null);
    add("强化等级", a.artifact_level != null ? `+${a.artifact_level}` : null);
    add("主属性", a.main_stat ? `${a.main_stat} ${a.main_stat_value != null ? a.main_stat_value : ""}` : null);
    if (a.substats && a.substats.length) {
      add("副属性", `<span class="detail-sub">${a.substats.map((s) => {
        if (s && typeof s === "object" && s.name) {
          return s.value != null ? `${s.name} +${s.value}${s.percent ? "%" : ""}` : s.name;
        }
        return s;
      }).join("</span><span class='detail-sub'>")}</span>`);
    }
    const gr = substatGrade(a);
    add("副词条评价", gr.text);
  } else if (a.type === "材料") {
    add("数量", a.material_qty != null ? String(a.material_qty) : null);
    add("来源", a.source);
  }
  const meta = [];
  if (a.conf != null) meta.push(`识别置信度 ${a.conf}`);
  if (a.raw_text) meta.push(`原文：${a.raw_text}`);
  const eName = g.equipment_name || "装备";
  const typeLabel = a.type === "装备" ? eName : a.type;
  $("#detailBody").innerHTML =
    `<div class="detail-title">${typeLabel} ｜ ${a.name || "未知"}</div>${rows.join("")}` +
    (meta.length ? `<div class="detail-meta">${meta.join(" ｜ ")}</div>` : "");
  $("#detailOverlay").classList.remove("hidden");
}

function initDetailOverlay() {
  $("#btnCloseDetail").addEventListener("click", () => $("#detailOverlay").classList.add("hidden"));
  $("#detailOverlay").addEventListener("click", (e) => {
    if (e.target === $("#detailOverlay")) $("#detailOverlay").classList.add("hidden");
  });
  // 事件委托：点击资产项打开详情
  $("#assetResult").addEventListener("click", (e) => {
    const el = e.target.closest("[data-idx]");
    if (el) showAssetDetail(assets[Number(el.dataset.idx)]);
  });
}

// ── 读屏扫描（浏览器窗口捕获）────────────────────────
let captureStream = null;
let autoTimer = null;
let analyzing = false;   // 防止定时采集时上一帧还没识别完就发下一帧

function initCapture() {
  $("#btnStartCapture").addEventListener("click", async () => {
    try {
      captureStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const v = $("#captureVideo");
      v.srcObject = captureStream; v.classList.remove("hidden");
      $("#btnStartCapture").classList.add("hidden");
      $("#btnCaptureOnce").classList.remove("hidden");
      $("#btnAutoCapture").classList.remove("hidden");
      $("#btnStopCapture").classList.remove("hidden");
      captureStream.getVideoTracks()[0].addEventListener("ended", stopCapture);
    } catch (e) { alert("未能获取屏幕画面，请允许共享窗口后重试。"); }
  });
  $("#btnCaptureOnce").addEventListener("click", () => captureFrame());
  $("#btnAutoCapture").addEventListener("click", () => {
    if (autoTimer) { clearInterval(autoTimer); autoTimer = null; $("#btnAutoCapture").textContent = "定时采集"; return; }
    autoTimer = setInterval(captureFrame, 3000);
    $("#btnAutoCapture").textContent = "停止定时";
  });
  $("#btnStopCapture").addEventListener("click", stopCapture);
}

function stopCapture() {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  if (captureStream) { captureStream.getTracks().forEach((t) => t.stop()); captureStream = null; }
  const v = $("#captureVideo");
  v.srcObject = null; v.classList.add("hidden");
  $("#btnStartCapture").classList.remove("hidden");
  $("#btnCaptureOnce").classList.add("hidden");
  $("#btnAutoCapture").classList.add("hidden"); $("#btnAutoCapture").textContent = "定时采集";
  $("#btnStopCapture").classList.add("hidden");
}

function captureFrame() {
  const v = $("#captureVideo");
  if (!v.videoWidth || analyzing) return;
  analyzing = true;
  const c = document.createElement("canvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);
  c.toBlob((blob) => {
    const reader = new FileReader();
    reader.onload = async () => {
      const image = String(reader.result).split(",")[1];
      try { await runAnalyze({ game_id: gameId, image }, true); }
      catch (e) { showAssetError(e.message); }
      finally { analyzing = false; }
    };
    reader.readAsDataURL(blob);
  }, "image/jpeg", 0.9);
}

// ── 伴生工具自动点击（网页一键开启 + 进度 + 断点续采 + 载入结果）──
function initAutoClick() {
  let pollTimer = null;
  const $st = $("#acStatus");
  const setStatus = (html) => { $st.innerHTML = html; };

  function windowDefault() {
    const code = (getGame() && getGame().code) || "genshin";
    return { genshin: "原神", wuthering: "鸣潮", zzz: "绝区零" }[code] || "原神";
  }
  $("#acWindow").placeholder = windowDefault();

  function setBusy(busy) {
    $("#btnAcStart").disabled = busy;
    $("#btnAcStop").disabled = !busy;
  }

  async function poll() {
    try {
      const s = await api("/api/v1/auto-click/status", "GET");
      const prog = s.progress
        ? `进度 ${s.progress.current}/${s.progress.total}`
        : (s.collected != null ? `已收集 ${s.collected} 条` : "启动中…");
      if (s.running) {
        setStatus(`⏳ 采集中｜${prog}\n输出：${s.output || "-"}\n每 10 件打印一次进度，中断可点「停止」后勾选「断点续采」重开。`);
      } else if (s.started && s.done) {
        stopPoll();
        setBusy(false);
        $("#btnAcLoad").disabled = false;
        const ok = !s.error;
        const logTail = (s.log && s.log.slice(-8).join("\n")) || "";
        setStatus(`${ok ? "✅ 采集完成" : "⚠️ 采集已停止（" + (s.error || "连续未识别") + "）"}\n` +
          `已收集 ${s.collected ?? 0} 条 → ${s.output}\n点击「载入采集结果」导入到资产清单。` +
          (logTail && !ok ? `\n── 日志（含可见窗口列表）──\n${logTail}` : ""));
      } else if (s.started) {
        stopPoll();
        setBusy(false);
        setStatus("⏹ 采集已停止（可勾选「断点续采」后重新开启，从断点继续）。");
      } else {
        setStatus("未启动。");
      }
    } catch (e) { setStatus("状态查询失败：" + (e.message || e)); }
  }
  function startPoll() { if (pollTimer) clearInterval(pollTimer); pollTimer = setInterval(poll, 2000); }
  function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

  $("#btnAcStart").addEventListener("click", async () => {
    const code = (getGame() && getGame().code) || "genshin";
    const windowTitle = $("#acWindow").value.trim() || windowDefault();
    const output = $("#acOutput").value.trim() || "data/artifacts_auto.json";
    const maxItems = Math.min(2000, Math.max(1, Number($("#acMaxItems").value) || 200));
    const resume = $("#acResume").checked;
    const viewport = $("#acViewport").value.trim() || null;
    try {
      const r = await api("/api/v1/auto-click/start", "POST",
        { game: code, window: windowTitle, output, max_items: maxItems, resume, viewport });
      setBusy(true);
      $("#btnAcLoad").disabled = true;
      setStatus(`🚀 已启动（${resume ? "断点续采" : "全新采集"}）｜PID ${r.pid}\n` +
        `请把游戏切到背包列表页（武器/圣遗物/材料页都行），工具会自动点击扫描。`);
      startPoll();
    } catch (e) { setStatus("启动失败：" + (e.message || e)); }
  });

  $("#btnAcStop").addEventListener("click", async () => {
    try { await api("/api/v1/auto-click/stop", "POST"); setStatus("⏹ 已请求停止，正在收尾…"); }
    catch (e) { setStatus("停止失败：" + (e.message || e)); }
  });

  $("#btnAcLoad").addEventListener("click", async () => {
    const path = $("#acOutput").value.trim() || "data/artifacts_auto.json";
    try {
      await runCollect({ method: "auto", payload: { path } });
      setStatus("✅ 已载入 " + assets.length + " 项资产（可去「毕业度评估/配装推荐」继续）。");
    } catch (e) {
      showAssetError(e.message);
      let extra = "";
      try { const s = await api("/api/v1/auto-click/status", "GET"); extra = (s.log && s.log.slice(-6).join("\n")) || ""; } catch (_) {}
      setStatus("载入失败：" + (e.message || e)
        + (extra ? "\n── 上次自动点击日志 ──\n" + extra : ""));
    }
  });

  window.addEventListener("beforeunload", stopPoll);
}

// 侧边栏账户资产汇总：角色/武器/圣遗物/材料 四类数量；空时提示导入
function updateAssetSummary() {
  const g = getGame() || {};
  const eName = g.equipment_name || "装备";
  const counts = { "角色": 0, "武器": 0, "装备": 0, "材料": 0 };
  assets.forEach((a) => { if (counts[a.type] != null) counts[a.type]++; });
  const total = assets.length;
  const body = $("#assetSummaryBody");
  if (!body) return;
  if (!total) {
    body.innerHTML = `<div class="side-summary-empty">暂时没有任何资料，请导入</div>`;
    return;
  }
  body.innerHTML =
    `<div class="side-summary-row"><span>角色</span><b>${counts["角色"]}</b></div>` +
    `<div class="side-summary-row"><span>武器</span><b>${counts["武器"]}</b></div>` +
    `<div class="side-summary-row"><span>${eName}</span><b>${counts["装备"]}</b></div>` +
    `<div class="side-summary-row"><span>材料</span><b>${counts["材料"]}</b></div>` +
    `<div class="side-summary-total"><span>合计</span><b>${total}</b></div>`;
}

// ── 毕业度评估 ───────────────────────────────────────
function initGraduate() {
  $("#btnGraduate").addEventListener("click", async () => {
    if (!assets.length) return alert("请先在「资产识别」里获取资产");
    const character_id = Number($("#gradChar").value);
    const r = await api("/api/v1/graduate", "POST", { game_id: gameId, character_id, assets });
    renderGraduate(r);
  });
}

function renderSubstatTags(detail) {
  if (!detail || !detail.length) return "";
  return detail.map((d) => {
    const cls = d.status === "达标" ? "ok" : d.status === "未达标" ? "bad" : "warn";
    const t = d.ok_count != null
      ? `达标词条 ${d.ok_count} 件 / 面板目标 ${d.target}`
      : `面板目标 ${d.target}`;
    return `<span class="tag ${cls}" title="${t}">${d.name} ${d.status}</span>`;
  }).join(" ");
}

function renderGraduate(r) {
  const bd = r.breakdown || {};
  let bdHtml = "";
  Object.entries(bd).forEach(([k, v]) => {
    const name = { level: "等级", weapon: "武器", artifact_set: "套装", main_stats: "主词条", substats: "副词条", talent: "天赋" }[k] || k;
    bdHtml += `<div class="bd"><span>${name}</span><span>${v.score} 分</span></div>`;
  });
  const gaps = (r.gaps || []).map((g) => `<li>${g}</li>`).join("");
  const subTags = renderSubstatTags(r.substat_detail);
  $("#gradResult").innerHTML = `
    <div class="card">
      <div class="big-score"><span>毕业度</span> <b>${r.score}</b></div>
      <div class="bar"><i style="width:${r.score}%"></i></div>
      <div class="breakdown">${bdHtml}</div>
    </div>
    ${subTags ? `<div class="card"><div class="card-title">副词条达标（按该角色毕业标准）</div>${subTags}</div>` : ""}
    ${gaps ? `<div class="card"><div class="card-title">还差这些</div><ul class="list">${gaps}</ul></div>` : `<div class="card"><span class="tag ok">已达标</span></div>`}
  `;
  $("#gradResult").classList.remove("hidden");
}

// ── 配装推荐（多人 1~9）───────────────────────────────
function renderRecChars() {
  const wrap = $("#recChars");
  wrap.innerHTML = "";
  characters.forEach((c) => {
    const el = document.createElement("span");
    el.className = "chip" + (recSelected.has(c.id) ? " on" : "");
    el.textContent = c.name;
    el.addEventListener("click", () => {
      if (recSelected.has(c.id)) recSelected.delete(c.id);
      else if (recSelected.size < 9) recSelected.add(c.id);
      else alert("最多同时选择 9 人");
      renderRecChars();
    });
    wrap.appendChild(el);
  });
}

function initRecommend() {
  $("#btnRecommend").addEventListener("click", async () => {
    if (!recSelected.size) return alert("请先选择角色");
    if (!assets.length) return alert("请先在「资产识别」里获取资产");
    const r = await api("/api/v1/recommend/batch", "POST",
      { game_id: gameId, character_ids: [...recSelected], assets });
    renderRecommendBatch(r.results || []);
  });

  // 培养建议（可复制文本）：按所选角色 + 毕业档位
  $("#btnAdvice").addEventListener("click", async () => {
    if (!recSelected.size) return alert("请先选择角色");
    if (!assets.length) return alert("请先在「资产识别」里获取资产");
    const tier = $("#adviceTier").value;
    const r = await api("/api/v1/advice", "POST",
      { game_id: gameId, character_ids: [...recSelected], assets, tier });
    renderAdvice(r.advice || "");
  });
}

function renderAdvice(text) {
  $("#adviceResult").innerHTML = `
    <div class="card">
      <div class="card-title">培养建议（可复制）</div>
      <pre style="white-space:pre-wrap;font-family:inherit;background:#f6f7f9;
        border-radius:8px;padding:12px;margin:8px 0;max-height:420px;overflow:auto">${text}</pre>
      <div class="action-row">
        <button class="ghost" id="btnCopyAdvice">复制全文</button>
      </div>
    </div>`;
  $("#btnCopyAdvice").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      alert("已复制培养建议");
    } catch (e) {
      alert("复制失败，请手动选择文本复制");
    }
  });
  $("#adviceResult").classList.remove("hidden");
}

function renderRecommendBatch(results) {
  let html = "";
  results.forEach((r) => {
    html += `<div class="card"><div class="card-title">${r.character}</div>`;
    (r.builds || []).forEach((b, i) => {
      const gaps = (b.gaps || []).map((g) => `<li>${g}</li>`).join("");
      const ms = Object.entries(b.main_stats || {}).map(([k, v]) => `${k}：${v}`).join("　");
      html += `<div style="padding:6px 0;border-top:1px solid #f0f1f3">
        方案 ${i + 1}　<span class="tag ok">匹配度 ${b.hit_rate}%</span>
        <div>武器：${b.weapons.join(" / ")}</div>
        <div>套装：${b.sets.join(" / ")}</div>
        <div>主词条：${ms}</div>
        ${gaps ? `<ul class="list">${gaps}</ul>` : `<span class="tag ok">已达标</span>`}
      </div>`;
    });
    const subTags = renderSubstatTags(r.substat_detail);
    html += `${subTags ? `<div style="padding:4px 0">副词条达标（按该角色标准）：${subTags}</div>` : ""}`;
    html += `<p style="color:#6b7280;margin-top:6px">${r.explanation}</p></div>`;
  });
  $("#recResult").innerHTML = html;
  $("#recResult").classList.remove("hidden");
}

// ── 队伍配置（多队 1~4）───────────────────────────────
function renderTeams() {
  const wrap = $("#teamBlocks");
  wrap.innerHTML = "";
  teams.forEach((t, i) => {
    const block = document.createElement("div");
    block.className = "card";
    const head = document.createElement("div");
    head.className = "team-head";
    head.innerHTML = `<b>队伍 ${i + 1}</b>`;
    const rm = document.createElement("button");
    rm.className = "ghost"; rm.textContent = "移除本队";
    rm.addEventListener("click", () => { teams.splice(i, 1); renderTeams(); });
    head.appendChild(rm);
    block.appendChild(head);

    const chips = document.createElement("div");
    chips.className = "chips";
    characters.forEach((c) => {
      const el = document.createElement("span");
      el.className = "chip" + (t.members.has(c.id) ? " on" : "");
      el.textContent = c.name;
      el.addEventListener("click", () => {
        if (t.members.has(c.id)) t.members.delete(c.id);
        else {
          const maxT = getGame().max_team_size || 4;   // 原神/鸣潮=4，绝区零=3
          if (t.members.size < maxT) t.members.add(c.id);
          else alert(`该游戏每队最多 ${maxT} 人`);
        }
        renderTeams();
      });
      chips.appendChild(el);
    });
    block.appendChild(chips);

    const wrow = document.createElement("div");
    wrow.className = "member-weight-row";
    [...t.members].forEach((id) => {
      const c = characters.find((x) => x.id === id);
      const box = document.createElement("div");
      box.className = "member-weight";
      box.innerHTML = `<span style="min-width:48px">${c.name}</span>`;
      const inp = document.createElement("input");
      inp.type = "number"; inp.min = "0.1"; inp.max = "3"; inp.step = "0.1";
      inp.value = t.weights[c.name] ?? 1;
      inp.addEventListener("change", () => { t.weights[c.name] = Number(inp.value) || 1; });
      box.appendChild(inp);
      wrow.appendChild(box);
    });
    block.appendChild(wrow);
    wrap.appendChild(block);
  });
}

function initTeam() {
  $("#btnAddTeam").addEventListener("click", () => {
    if (teams.length >= 4) return alert("最多 4 队");
    teams.push({ members: new Set(), weights: {} });
    renderTeams();
  });
  $("#btnTeams").addEventListener("click", async () => {
    const valid = teams.filter((t) => t.members.size >= 2);
    if (!valid.length) return alert("请先添加队伍，并每队选择至少 2 名成员");
    if (!assets.length) return alert("请先在「资产识别」里获取资产");
    const payload = {
      game_id: gameId,
      teams: valid.map((t) => ({ members: [...t.members], weights: t.weights })),
      assets,
    };
    const r = await api("/api/v1/teams/recommend", "POST", payload);
    renderTeamsResult(r.teams || []);
  });
}

function renderTeamsResult(list) {
  let html = "";
  list.forEach((t) => {
    const m = t.members.map((x) => `<div class="bd"><span>${x.char}</span><span>${x.score} 分</span></div>`).join("");
    const a = Object.entries(t.assignment || {}).map(([k, v]) => `<li>${k} → ${v}</li>`).join("");
    html += `<div class="card">
      <div class="card-title">队伍 ${t.team_index + 1}　<span class="tag ok">队伍毕业度 ${t.team_score}</span></div>
      <div class="breakdown">${m}</div>
      <div>武器分配：<ul class="list">${a || "<li>暂无武器资产</li>"}</ul></div>
      <p>培养顺序：${(t.priority || []).join(" → ")}</p>
    </div>`;
  });
  $("#teamResult").innerHTML = html;
  $("#teamResult").classList.remove("hidden");
}

// ── 主题切换（4 套配色，localStorage 记忆）────────────
function initTheme() {
  const sel = $("#themeSelect");
  const saved = localStorage.getItem("gyz_theme") || "blue";
  document.body.dataset.theme = saved;
  sel.value = saved;
  sel.addEventListener("change", () => {
    document.body.dataset.theme = sel.value;
    localStorage.setItem("gyz_theme", sel.value);
  });
}

// ── 毕业标准 ───────────────────────────────────────
// 滑块 id → 词条名（用于按角色主要属性置灰）
const STD_KEY_MAP = {
  "stdCr": "暴击率", "stdCd": "暴击伤害", "stdEr": "元素充能效率",
  "stdEm": "元素精通", "stdAtk": "攻击力", "stdDef": "防御力", "stdHp": "生命值",
};

function applyKeyStats(keyStats) {
  // 只要求当前角色的主要属性：非主要属性置灰（不可调、不参与评估）
  const keys = new Set(keyStats || []);
  Object.entries(STD_KEY_MAP).forEach(([id, stat]) => {
    const el = $("#" + id);            // 注意 # 前缀：querySelector 按 id 查找
    if (!el) return;
    const item = el.closest(".std-item");
    const gray = !keys.has(stat);
    el.disabled = gray;
    if (item) item.classList.toggle("gray", gray);
  });
}

async function refreshKeyStats() {
  // 从系统标准拿该角色主要属性（不需要用户资产，evaluate 仍会返回 key_stats）
  if (!standardCharId) { console.warn("refreshKeyStats: standardCharId 为空"); return; }
  try {
    const r = await api("/api/v1/graduate", "POST",
      { game_id: gameId, character_id: standardCharId, assets: [] });
    applyKeyStats(r.key_stats || []);
    console.log("refreshKeyStats OK:", r.key_stats);
  } catch (e) { console.error("refreshKeyStats 失败：", e.message); }
}
function initStandard() {
  const preview = debounce(previewStandard, 350);

  $("#stdChar").addEventListener("change", () => {
    standardCharId = Number($("#stdChar").value);
    refreshKeyStats();
    preview();
  });
  $("#stdLevel").addEventListener("input", (e) => { $("#stdLevelVal").textContent = e.target.value; preview(); });
  $("#stdWeapon").addEventListener("input", (e) => { $("#stdWeaponVal").textContent = e.target.value; preview(); });
  $("#stdTalentNormal").addEventListener("input", (e) => { $("#stdTalentNormalVal").textContent = e.target.value; preview(); });
  $("#stdTalentSkill").addEventListener("input", (e) => { $("#stdTalentSkillVal").textContent = e.target.value; preview(); });
  $("#stdTalentBurst").addEventListener("input", (e) => { $("#stdTalentBurstVal").textContent = e.target.value; preview(); });
  $("#stdCr").addEventListener("input", (e) => { $("#stdCrVal").textContent = e.target.value; preview(); });
  $("#stdCd").addEventListener("input", (e) => { $("#stdCdVal").textContent = e.target.value; preview(); });
  $("#stdEr").addEventListener("input", (e) => { $("#stdErVal").textContent = e.target.value; preview(); });
  $("#stdEm").addEventListener("input", (e) => { $("#stdEmVal").textContent = e.target.value; preview(); });
  $("#stdAtk").addEventListener("input", (e) => { $("#stdAtkVal").textContent = e.target.value; preview(); });
  $("#stdDef").addEventListener("input", (e) => { $("#stdDefVal").textContent = e.target.value; preview(); });
  $("#stdHp").addEventListener("input", (e) => { $("#stdHpVal").textContent = e.target.value; preview(); });

  // 自定义词条：自由输入任意词条名 + 目标数值
  function renderCustomStats() {
    const wrap = $("#customStatList");
    wrap.innerHTML = "";
    customStats.forEach((s, i) => {
      const el = document.createElement("span");
      el.className = "chip on";
      el.innerHTML = `${s.name} ${s.value}`;
      const rm = document.createElement("span");
      rm.style.cssText = "margin-left:6px;cursor:pointer;color:#dc2626";
      rm.textContent = "✕";
      rm.addEventListener("click", () => { customStats.splice(i, 1); renderCustomStats(); preview(); });
      el.appendChild(rm);
      wrap.appendChild(el);
    });
  }

  $("#btnAddCustomStat").addEventListener("click", () => {
    const name = $("#customStatName").value.trim();
    const value = Number($("#customStatValue").value);
    if (!name) return alert("请输入词条名");
    if (!(value >= 0)) return alert("请输入非负的目标数值");
    const idx = customStats.findIndex((s) => s.name === name);
    if (idx >= 0) customStats[idx].value = value;
    else customStats.push({ name, value });
    $("#customStatName").value = ""; $("#customStatValue").value = "";
    renderCustomStats(); preview();
  });

  renderCustomStats();

  $("#stdSetToggle").addEventListener("click", () => {
    const t = $("#stdSetToggle");
    t.classList.toggle("on"); t.classList.toggle("off");
    t.textContent = t.classList.contains("on") ? "需要套装" : "不要求套装";
    preview();
  });

  $$(".tier-btn").forEach((b) => b.addEventListener("click", () => {
    $$(".tier-btn").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    preview();
  }));

  $("#btnSaveStandard").addEventListener("click", async () => {
    if (!standardCharId) standardCharId = Number($("#stdChar").value);
    const tier = document.querySelector(".tier-btn.active").dataset.tier;
    await api("/api/v1/standards", "PUT",
      { user_id: USER, game_id: gameId, character_id: standardCharId, tier, overrides: collectOverrides() });
    $("#stdResult").innerHTML = `<div class="card"><span class="tag ok">已保存</span> 你的标准已记住。</div>`;
    $("#stdResult").classList.remove("hidden");
  });

  $("#btnResetStandard").addEventListener("click", () => {
    $("#stdLevel").value = 90; $("#stdWeapon").value = 90; $("#stdCr").value = 60; $("#stdCd").value = 200;
    $("#stdEr").value = 200; $("#stdEm").value = 300;
    $("#stdAtk").value = 2500; $("#stdDef").value = 1500; $("#stdHp").value = 30000;
    $("#stdTalentNormal").value = 9; $("#stdTalentSkill").value = 9; $("#stdTalentBurst").value = 9;
    $("#stdLevelVal").textContent = 90; $("#stdWeaponVal").textContent = 90;
    $("#stdCrVal").textContent = 60; $("#stdCdVal").textContent = 200;
    $("#stdErVal").textContent = 200; $("#stdEmVal").textContent = 300;
    $("#stdAtkVal").textContent = 2500; $("#stdDefVal").textContent = 1500; $("#stdHpVal").textContent = 30000;
    $("#stdTalentNormalVal").textContent = 9; $("#stdTalentSkillVal").textContent = 9; $("#stdTalentBurstVal").textContent = 9;
    customStats = []; renderCustomStats();
    const t = $("#stdSetToggle"); t.classList.add("on"); t.classList.remove("off"); t.textContent = "需要套装";
    previewStandard();
  });
}

function collectOverrides() {
  // 只提交当前角色主要属性（置灰项不参与评估）
  const substats = {};
  const add = (id, stat) => { if (!$("#" + id).disabled) substats[stat] = Number($("#" + id).value); };
  add("stdCr", "暴击率"); add("stdCd", "暴击伤害"); add("stdEr", "元素充能效率");
  add("stdEm", "元素精通"); add("stdAtk", "攻击力"); add("stdDef", "防御力"); add("stdHp", "生命值");
  customStats.forEach((s) => { substats[s.name] = s.value; });   // 自定义词条合并进来
  const o = {
    level: Number($("#stdLevel").value),
    weapon: { min_level: Number($("#stdWeapon").value) },
    talents: {
      normal: Number($("#stdTalentNormal").value),     // 普通攻击
      skill: Number($("#stdTalentSkill").value),       // 元素战绩
      burst: Number($("#stdTalentBurst").value),       // 元素爆发
    },
    substat_targets: substats,
  };
  if (!$("#stdSetToggle").classList.contains("on")) o.artifact_set = "off";
  return o;
}

async function previewStandard() {
  if (!standardCharId) standardCharId = Number($("#stdChar").value);
  if (!assets.length) { $("#sysScore").textContent = "—"; $("#myScore").textContent = "—"; return; }
  const tier = document.querySelector(".tier-btn.active").dataset.tier;
  const overrides = collectOverrides();
  const sys = await api("/api/v1/graduate", "POST", { game_id: gameId, character_id: standardCharId, assets });
  const mine = await api("/api/v1/graduate", "POST",
    { game_id: gameId, character_id: standardCharId, assets, standard: { tier, overrides } });
  $("#sysScore").textContent = sys.score;
  $("#myScore").textContent = mine.score;
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ── 启动 ───────────────────────────────────────────
(async function boot() {
  window.addEventListener("error", (e) => console.error("页面脚本错误：", e.message));
  window.addEventListener("unhandledrejection", (e) => {
    const msg = (e.reason && (e.reason.message || String(e.reason))) || "未知错误";
    console.error("接口错误：", msg);
    alert("操作失败：" + msg);
  });
  initNav();
  initAssets();
  initCapture();
  initAutoClick();
  initTheme();
  initDetailOverlay();
  try {
    await loadGames();
    const saved = localStorage.getItem("gyz_game");
    if (saved && games.some((g) => g.id === Number(saved))) gameId = Number(saved);
    else if (games.length) gameId = games[0].id;
    if (!saved || !games.some((g) => g.id === Number(saved))) showOnboarding();
    await loadCharacters();
  } catch (e) { console.error("初始化失败：", e); }
  // 面板事件绑定不依赖数据加载结果，保证按钮始终可用
  initGraduate();
  initRecommend();
  initTeam();
  initStandard();
  standardCharId = Number($("#stdChar").value) || null;
  refreshKeyStats();   // 按当前角色主要属性置灰滑块
  // 注意：启动时不自动加载已保存资产——进入页面应为空，
  // 数据通过「导入测试数据 / 保存我的资产」等操作显式获取。
})();
