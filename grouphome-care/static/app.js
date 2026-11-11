/* ケアきろく 画面の動き（外部ライブラリなし） */
"use strict";

const S = { me: null, meta: null, residents: [], users: [], rec: null, doc: null };
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const app = () => $("#app");
const todayStr = () => S.me?.today || new Date().toISOString().slice(0, 10);
const nowTime = () => new Date().toTimeString().slice(0, 5);
const thisMonth = () => todayStr().slice(0, 7);
const isAdmin = () => (S.me?.level || 0) >= 2;
const isManager = () => (S.me?.level || 0) >= 3;
const STATUS = { draft: "下書き", submitted: "承認待ち", approved: "承認済み", returned: "差し戻し" };
const badge = (s) => `<span class="badge ${esc(s)}">${esc(STATUS[s] || s)}</span>`;
const typeLabel = (t) => S.meta?.forms[t]?.label || t;

async function api(method, path, body) {
  const opt = { method, headers: { "X-Requested-With": "carekiroku" }, credentials: "same-origin" };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const res = await fetch(path, opt);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/api/login") { S.me = null; renderLogin(); throw new Error(data.error || "ログインしてください"); }
  if (!res.ok) throw new Error(data.error || "エラーが起きました");
  return data;
}
const GET = (p) => api("GET", p);
const POST = (p, b) => api("POST", p, b || {});

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.className = "toast"), 3200);
}
async function safe(fn) { try { await fn(); } catch (e) { toast(e.message, true); } }
function modal(html) { $("#modal-body").innerHTML = html; $("#modal").classList.remove("hidden"); return $("#modal-body"); }
function closeModal() { $("#modal").classList.add("hidden"); $("#modal-body").innerHTML = ""; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal" || e.target.dataset.close !== undefined) closeModal(); });

/* ---------- 音声入力（ブラウザの音声認識） ---------- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
function bindMic(btn, textarea) {
  if (!btn) return;
  if (!SR) {
    btn.addEventListener("click", () => toast("この端末のブラウザは音声入力に未対応です。キーボードのマイクボタンを使ってください。", true));
    return;
  }
  let rec = null;
  btn.addEventListener("click", () => {
    if (rec) { rec.stop(); return; }
    rec = new SR(); rec.lang = "ja-JP"; rec.continuous = true; rec.interimResults = false;
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) {
          textarea.value += (textarea.value && !/[。\n]$/.test(textarea.value) ? "。" : "") + e.results[i][0].transcript;
          textarea.dispatchEvent(new Event("input"));
        }
      }
    };
    rec.onerror = (e) => toast("音声入力エラー：" + e.error, true);
    rec.onend = () => { rec = null; btn.classList.remove("rec"); btn.textContent = "🎤"; };
    rec.start(); btn.classList.add("rec"); btn.textContent = "■";
    toast("話してください。終わったら ■ を押します。");
  });
}
const VOICE_EXAMPLES = {
  vital: "体温36.8度、血圧120の80、脈72、サチュレーション97", meal: "朝ごはん全部、昼は半分、夜は食べなかった",
  med: "朝の薬は飲んだ", excretion: "おしっこあり、便はやわらかい", case: "穏やかに過ごされ、お風呂に入った",
  handover: "大事、夜中に何度か起きていた", diary: "晴れ、避難訓練をした",
};
function listenOnce(btn, onText) {
  if (!btn) return;
  if (!SR) {
    btn.addEventListener("click", () => toast("この端末のブラウザは音声入力に未対応です。キーボードのマイクボタンを使ってください。", true));
    return;
  }
  let rec = null;
  btn.addEventListener("click", () => {
    if (rec) { rec.stop(); return; }
    rec = new SR(); rec.lang = "ja-JP"; rec.continuous = false; rec.interimResults = false;
    rec.onresult = (e) => { const t = Array.from(e.results).filter((r) => r.isFinal).map((r) => r[0].transcript).join("、"); if (t) onText(t); };
    rec.onerror = (e) => toast("音声入力エラー：" + e.error, true);
    rec.onend = () => { rec = null; btn.classList.remove("rec"); btn.textContent = "🎤 話して入力"; };
    rec.start(); btn.classList.add("rec"); btn.textContent = "■ 聞いています…（押すと終わり）";
  });
}
const memoBox = (id, value = "", ph = "ここに書く、または 🎤 を押して話す") =>
  `<div class="memo-wrap"><textarea id="${id}" placeholder="${esc(ph)}">${esc(value)}</textarea>
   <button type="button" class="mic" data-mic="${id}" aria-label="音声入力">🎤</button></div>`;
const bindMics = (root = document) => $$("[data-mic]", root).forEach((b) => bindMic(b, $("#" + b.dataset.mic, root)));

/* ---------- ログイン ---------- */
function renderLogin() {
  $("#who").innerHTML = "";
  app().innerHTML = `<div class="card login">
    <h1>ログイン</h1>
    <form id="login-form">
      <label class="field" for="lid">ID</label><input id="lid" autocomplete="username" autocapitalize="off" required>
      <label class="field" for="lpw">パスワード</label><input id="lpw" type="password" autocomplete="current-password" required>
      <p></p><button class="primary big">ログイン</button>
    </form>
    <p class="sub">デモ用：manager（管理者）／ sabikan（サービス管理責任者）／ staff1・staff2（職員）、パスワードは demo1234</p>
  </div>`;
  $("#login-form").addEventListener("submit", (e) => {
    e.preventDefault();
    safe(async () => { await POST("/api/login", { login_id: $("#lid").value.trim(), password: $("#lpw").value }); await boot(); });
  });
}

async function boot() {
  try { S.me = await GET("/api/me"); } catch { return renderLogin(); }
  S.meta = await GET("/api/meta");
  await reloadMasters();
  $("#who").innerHTML = `<span class="uname">${esc(S.me.facility.name)}｜${esc(S.me.name)}（${esc(S.me.role_label)}）</span>
    <button id="logout">ログアウト</button>`;
  $("#logout").addEventListener("click", () => safe(async () => { await POST("/api/logout"); S.me = null; location.hash = "#/home"; renderLogin(); }));
  route();
}
async function reloadMasters() { [S.residents, S.users] = await Promise.all([GET("/api/residents"), GET("/api/users")]); }
const activeResidents = () => S.residents.filter((r) => r.active);
const residentName = (id) => S.residents.find((r) => r.id == id)?.name || "";

/* ---------- 画面の切りかえ ---------- */
const VIEWS = {};
window.addEventListener("hashchange", route);
function route() {
  if (!S.me) return;
  const [name, rawArg] = (location.hash.replace(/^#\//, "") || "home").split("/");
  const arg = rawArg ? rawArg.split("?")[0] : rawArg;
  const view = VIEWS[name] || VIEWS.home;
  window.scrollTo(0, 0);
  safe(() => view(arg));
}
const back = (to = "home", label = "← もどる") => `<a class="btn small no-print" href="#/${to}">${label}</a>`;

/* ---------- ホーム ---------- */
VIEWS.home = async () => {
  const notes = await GET("/api/notifications");
  const tiles = [
    ["record", "✏️", "きろくを書く", "バイタル・食事・服薬など", true],
    ["handover", "📣", "申し送り", "前の勤務からの連絡"],
    ["checklist", "✅", "毎日のチェック", "服薬・感染症・防災"],
    ["incidents", "⚠️", "事故・ヒヤリ", "報告・似た事例・分析"],
    ["search", "🔎", "さがす", "過去の記録を見る"],
    ["mine", "↩️", "自分の下書き・差し戻し", ""],
    ["docs", "📄", "書類をつくる", "報告書・議事録・研修"],
    ["deadlines", "📅", "期限・提出物", ""],
    ...(isAdmin() ? [
      ["approval", "🖊️", "確認・承認", "記録や報告をチェック"],
      ["checks", "🧮", "請求前チェック", "もれ・不一致をさがす"],
      ["occupancy", "🗓️", "稼働表", "在宅・外泊・入院"],
      ["attendance", "⏰", "シフト・勤怠", ""],
      ["master", "👥", "利用者・計画・職員", "基本情報の登録"],
      ["audit", "📜", "操作の履歴", "だれが・いつ・何を"],
    ] : [["attendance", "⏰", "シフト・勤怠", ""]]),
  ];
  app().innerHTML = `
    <h1>こんにちは、${esc(S.me.name)}さん</h1>
    <div class="row no-print"><button class="small" data-clock="in">🟢 出勤</button><button class="small" data-clock="out">🔴 退勤</button>
      <span class="sub">${esc(todayStr())}</span></div>
    <h2>お知らせ</h2>
    ${notes.length ? notes.map((n) => `<a class="notice ${esc(n.level)}" href="#/${esc(n.link)}">${esc(n.text)} ›</a>`).join("") : `<div class="notice ok">お知らせはありません</div>`}
    <h2>メニュー</h2>
    <div class="tiles">${tiles.map(([k, ic, t, s, main]) => `<a class="tile ${main ? "main" : ""}" href="#/${k}"><span class="ic">${ic}</span>${esc(t)}${s ? `<small>${esc(s)}</small>` : ""}</a>`).join("")}</div>`;
  $$("[data-clock]").forEach((b) => b.addEventListener("click", () => safe(async () => {
    const r = await POST("/api/clock", { kind: b.dataset.clock });
    toast(`${b.dataset.clock === "in" ? "出勤" : "退勤"}を記録しました（${r.time}）`);
  })));
};

/* ---------- 記録を書く（3ステップ） ---------- */
VIEWS.record = async (arg) => {
  const p = new URLSearchParams(arg || "");
  if (!S.rec || p.has("new") || p.has("resident")) {
    S.rec = { step: 1, resident_id: null, type: null, fields: {}, phrases: [], memo: "", text: "", checks: [], handover: false,
              date: p.get("date") || todayStr(), time: nowTime(), drafted: false, voiceKeys: [], heard: "", voiceOk: false };
    if (p.get("resident")) { S.rec.resident_id = Number(p.get("resident")) || null; S.rec.step = 2; }
    if (p.has("new") || p.has("resident")) history.replaceState(null, "", "#/record");
  }
  renderRecord();
};
const stepBar = (n) => `<div class="steps">${["① だれ？", "② なにを？", "③ 入力する"].map((s, i) => `<span class="${i + 1 === n ? "now" : ""}">${s}</span>`).join("")}</div>`;

async function renderRecord() {
  const R = S.rec;
  if (R.step === 1) {
    app().innerHTML = `${back()}<h1>だれの記録？</h1>${stepBar(1)}
      <label class="field">日付</label><input type="date" id="rdate" value="${esc(R.date)}" max="${esc(todayStr())}">
      <div class="tiles" style="margin-top:14px">
        ${activeResidents().map((r) => `<button class="tile" data-res="${r.id}"><span class="ic">🙂</span>${esc(r.name)}<small>${esc(r.room || "")}号室</small></button>`).join("")}
        <button class="tile" data-res="0"><span class="ic">🏠</span>事業所全体<small>業務日誌・全体の申し送り</small></button>
      </div>`;
    $("#rdate").addEventListener("change", (e) => (R.date = e.target.value));
    $$("[data-res]").forEach((b) => b.addEventListener("click", () => { R.resident_id = Number(b.dataset.res) || null; R.step = 2; renderRecord(); }));
    return;
  }
  if (R.step === 2) {
    let doneTypes = new Set();
    if (R.resident_id) {
      const recs = await GET(`/api/records?resident_id=${R.resident_id}&date_from=${R.date}&date_to=${R.date}`);
      doneTypes = new Set(recs.map((r) => r.type));
    }
    const types = Object.entries(S.meta.forms).filter(([k, d]) => R.resident_id ? k !== "diary" : (d.resident_optional || k === "handover"));
    app().innerHTML = `<button class="small" id="bk">← 人を選びなおす</button>
      <h1>${esc(R.resident_id ? residentName(R.resident_id) + "さん" : "事業所全体")}：なにを書く？</h1>${stepBar(2)}
      <p class="sub">${esc(R.date)}　✓ は今日もう書いた記録です</p>
      <div class="tiles">${types.map(([k, d]) => `<button class="tile ${doneTypes.has(k) ? "done" : ""}" data-type="${k}"><span class="ic">${d.icon}</span>${esc(d.label)}${doneTypes.has(k) ? "<small>✓ 記録済み</small>" : (S.meta.daily_required.includes(k) && R.resident_id ? "<small>毎日必要</small>" : "")}</button>`).join("")}</div>`;
    $("#bk").addEventListener("click", () => { R.step = 1; renderRecord(); });
    $$("[data-type]").forEach((b) => b.addEventListener("click", () => {
      Object.assign(R, { type: b.dataset.type, step: 3, fields: {}, phrases: [], memo: "", text: "", checks: [], drafted: false, handover: b.dataset.type === "handover", voiceKeys: [], heard: "", voiceOk: false });
      renderRecord();
    }));
    return;
  }
  const def = S.meta.forms[R.type];
  app().innerHTML = `<button class="small" id="bk">← 種類を選びなおす</button>
    <h1>${def.icon} ${esc(def.label)}｜${esc(R.resident_id ? residentName(R.resident_id) + "さん" : "事業所全体")}</h1>${stepBar(3)}
    <div class="card voice-card">
      <button class="primary big" id="vbtn">🎤 話して入力</button>
      <p class="sub">例：「${esc(VOICE_EXAMPLES[R.type] || "")}」　話し終わると、下の欄に自動で入ります。</p>
      ${R.heard ? `<div class="notice info">聞き取った言葉：「${esc(R.heard)}」<br>
        <button type="button" class="small" id="vcopy">この言葉をそのままメモに入れる</button></div>` : ""}
      ${R.voiceKeys.length ? `<div class="notice warn">🎤 色の付いた欄は音声で入れた値です。聞き間違いがないか必ず確認してください。</div>` : ""}
    </div>
    <div class="card">
      <div class="row"><div class="grow"><label class="field">日付</label><input type="date" id="f-date" value="${esc(R.date)}" max="${esc(todayStr())}"></div>
      <div class="grow"><label class="field">時刻</label><input type="time" id="f-time" value="${esc(R.time)}"></div></div>
      ${def.fields.map(fieldHtml).join("")}
      ${def.phrases.length ? `<label class="field">よく使う文（押すと入ります）</label><div class="choices">${def.phrases.map((ph) => `<button type="button" class="chip ${R.phrases.includes(ph) ? "on" : ""}" data-phrase="${esc(ph)}">${esc(ph)}</button>`).join("")}</div>` : ""}
      <label class="field" for="f-memo">メモ（話してもOK）</label>${memoBox("f-memo", R.memo)}
      ${R.type !== "handover" ? `<label class="check-line"><input type="checkbox" id="f-ho" ${R.handover ? "checked" : ""}> 申し送りにも出す</label>` : ""}
      <button class="primary big" id="mk">✨ 文章にする</button>
    </div>
    <div id="draft-area"></div>`;
  $("#bk").addEventListener("click", () => { R.step = 2; renderRecord(); });
  $("#f-date").addEventListener("change", (e) => (R.date = e.target.value));
  $("#f-time").addEventListener("change", (e) => (R.time = e.target.value));
  $("#f-memo").addEventListener("input", (e) => (R.memo = e.target.value));
  $("#f-ho")?.addEventListener("change", (e) => (R.handover = e.target.checked));
  bindMics(app());
  $$("[data-field]").forEach((el) => {
    const f = def.fields.find((x) => x.key === el.dataset.field);
    if (el.tagName === "INPUT") { el.addEventListener("input", () => (R.fields[f.key] = el.value)); return; }
    el.addEventListener("click", () => {
      const v = el.dataset.val;
      if (f.kind === "multi") {
        const cur = R.fields[f.key] || [];
        R.fields[f.key] = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
      } else if (f.kind === "choice") R.fields[f.key] = R.fields[f.key] === v ? "" : v;
      else { R.fields[f.key] = v; const inp = $(`input[data-field="${f.key}"]`); if (inp) inp.value = v; }
      $$(`[data-field="${f.key}"][data-val]`).forEach((b) => b.classList.toggle("on",
        f.kind === "multi" ? (R.fields[f.key] || []).includes(b.dataset.val) : R.fields[f.key] === b.dataset.val));
    });
  });
  $$("[data-phrase]").forEach((b) => b.addEventListener("click", () => {
    const ph = b.dataset.phrase;
    R.phrases = R.phrases.includes(ph) ? R.phrases.filter((x) => x !== ph) : [...R.phrases, ph];
    b.classList.toggle("on");
  }));
  $("#mk").addEventListener("click", () => safe(makeDraft));
  listenOnce($("#vbtn"), (heard) => safe(async () => {
    const r = await POST("/api/ai/parse", { type: R.type, text: heard });
    R.fields = { ...R.fields, ...r.fields };
    R.voiceKeys = [...new Set([...R.voiceKeys, ...r.filled])];
    if (r.rest) R.memo = R.memo ? R.memo.replace(/[。\s]*$/, "。") + r.rest : r.rest;
    R.heard = r.heard; R.voiceOk = false; R.drafted = false;
    renderRecord();
    toast(r.filled.length ? `${r.filled.length}個の欄に入れました。確認してください。` : "欄に入る値は見つかりませんでした。メモに入れました。");
  }));
  $("#vcopy")?.addEventListener("click", () => {
    R.memo = R.memo ? R.memo.replace(/[。\s]*$/, "。") + R.heard : R.heard;
    $("#f-memo").value = R.memo; toast("メモに入れました");
  });
  if (R.drafted) renderDraft();
}

function fieldHtml(f) {
  const v = S.rec.fields[f.key];
  const voice = S.rec.voiceKeys.includes(f.key);
  const vtag = voice ? ` <span class="badge submitted">🎤 確認してください</span>` : "";
  if (f.kind === "number") {
    return `<label class="field">${esc(f.label)}${vtag}</label>
      <input type="number" inputmode="decimal" step="${esc(f.step || "1")}" data-field="${f.key}" value="${esc(v || "")}" class="${voice ? "voice" : ""}">
      ${f.quick ? `<div class="choices" style="margin-top:6px">${f.quick.map((q) => `<button type="button" class="chip ${v === q ? "on" : ""}" data-field="${f.key}" data-val="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}`;
  }
  const on = (o) => (f.kind === "multi" ? (v || []).includes(o) : v === o);
  return `<label class="field">${esc(f.label)}${f.kind === "multi" ? "<span class='sub'>（いくつでも）</span>" : ""}${vtag}</label>
    <div class="choices ${voice ? "voice" : ""}">${f.options.map((o) => `<button type="button" class="chip ${on(o) ? "on" : ""}" data-field="${f.key}" data-val="${esc(o)}">${esc(o)}</button>`).join("")}</div>`;
}

async function makeDraft() {
  const R = S.rec;
  const r = await POST("/api/ai/draft", { type: R.type, fields: R.fields, memo: R.memo, phrases: R.phrases });
  Object.assign(R, { text: r.text, checks: r.checks, suggest: r.suggest_incident, note: r.note, drafted: true });
  renderDraft();
  $("#draft-area").scrollIntoView({ behavior: "smooth" });
}
function renderDraft() {
  const R = S.rec;
  $("#draft-area").innerHTML = `<div class="card">
    <h2 style="margin-top:0">できた文章（直してOK）</h2>
    <p class="sub">${esc(R.note || "")}</p>
    ${R.checks.map((c) => `<div class="notice warn">⚠️ ${esc(c)}</div>`).join("")}
    ${R.suggest ? `<a class="btn" href="#/incidents/new">⚠️ 事故・ヒヤリ報告を書く</a>` : ""}
    <textarea id="f-text" style="min-height:160px;margin-top:10px">${esc(R.text)}</textarea>
    ${R.voiceKeys.length ? `<label class="check-line notice warn"><input type="checkbox" id="f-vok" ${R.voiceOk ? "checked" : ""}> 🎤で入った値が正しいことを確認しました</label>` : ""}
    <div class="row" style="margin-top:12px"><button class="primary big grow" id="sv">💾 保存して提出（管理者が確認）</button></div>
    <div class="row" style="margin-top:8px"><button class="grow" id="sv-d">下書きで保存</button></div>
  </div>`;
  $("#f-text").addEventListener("input", (e) => (R.text = e.target.value));
  $("#f-vok")?.addEventListener("change", (e) => (R.voiceOk = e.target.checked));
  $("#sv").addEventListener("click", () => safe(() => saveRecord(false)));
  $("#sv-d").addEventListener("click", () => safe(() => saveRecord(true)));
}
async function saveRecord(draft) {
  const R = S.rec;
  if (!R.text.trim()) throw new Error("文章が空です。「文章にする」を押すか、直接書いてください。");
  if (R.voiceKeys.length && !R.voiceOk) throw new Error("🎤で入った値を確認して、「確認しました」にチェックを付けてください。");
  await POST("/api/records", { resident_id: R.resident_id, type: R.type, date: R.date, time: R.time, fields: R.fields, memo: R.memo,
    text: R.text, handover: R.handover, draft });
  const who = R.resident_id;
  app().innerHTML = `<div class="card" style="text-align:center"><div style="font-size:64px">✅</div>
    <h1>${draft ? "下書きを保存しました" : "保存しました"}</h1>
    <p class="sub">${esc(who ? residentName(who) + "さん" : "事業所全体")}／${esc(typeLabel(R.type))}／${esc(R.date)}</p>
    <div class="tiles">
      <a class="tile main" href="#/record/resident=${who || 0}&date=${R.date}"><span class="ic">✏️</span>同じ人の<br>別の記録</a>
      <a class="tile" href="#/record/new=1&date=${R.date}"><span class="ic">👥</span>別の人の記録</a>
      <a class="tile" href="#/home"><span class="ic">🏠</span>ホームへ</a></div></div>`;
  S.rec = null;
}

/* ---------- 申し送り ---------- */
VIEWS.handover = async (arg) => {
  const days = Number(arg) || 3;
  const d = await GET(`/api/handovers?days=${days}`);
  app().innerHTML = `${back()}<h1>📣 申し送り</h1>
    <div class="tabs">${[1, 3, 7].map((n) => `<a class="btn small ${n === days ? "primary" : ""}" href="#/handover/${n}">${n === 1 ? "今日" : n + "日分"}</a>`).join("")}
      <a class="btn small" href="#/record/new=1">＋ 申し送りを書く</a></div>
    ${d.groups.length ? d.groups.map((g) => `<div class="card"><h2 style="margin-top:0">${esc(g.resident)} ${g.important ? '<span class="badge imp">大事</span>' : ""}</h2>
      ${g.items.map((i) => `<div class="list-item"><div class="sub" style="min-width:120px">${esc(i.date.slice(5))} ${esc(i.time || "")}<br>${esc(typeLabel(i.type))}</div>
        <div class="grow">${i.important ? '<span class="badge imp">大事</span> ' : ""}${esc(i.text)}<div class="sub">記録：${esc(i.by || "")}</div></div></div>`).join("")}</div>`).join("")
      : `<div class="notice ok">この期間の申し送りはありません</div>`}
    <h2>利用者の特記事項（いつも気をつけること）</h2>
    <div class="card">${d.notes.map((n) => `<div class="list-item"><b style="min-width:120px">${esc(n.name)}</b><div>${esc(n.notes)}</div></div>`).join("") || "なし"}</div>`;
};

/* ---------- さがす ---------- */
VIEWS.search = async (arg) => {
  const p = new URLSearchParams(arg || "");
  const f = { date_from: p.get("date_from") || "", date_to: p.get("date_to") || "", resident_id: p.get("resident_id") || "", type: p.get("type") || "", status: p.get("status") || "", q: p.get("q") || "" };
  const recs = await GET("/api/records?" + new URLSearchParams(f));
  app().innerHTML = `${back()}<h1>🔎 記録をさがす</h1>
    <form class="card" id="sf"><div class="row">
      <div class="grow"><label class="field">ことば</label><input name="q" value="${esc(f.q)}" placeholder="例：転倒、熱、通院"></div>
      <div class="grow"><label class="field">利用者</label><select name="resident_id"><option value="">全員</option>${S.residents.map((r) => `<option value="${r.id}" ${f.resident_id == r.id ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select></div>
      <div class="grow"><label class="field">種類</label><select name="type"><option value="">全部</option>${Object.entries(S.meta.forms).map(([k, d]) => `<option value="${k}" ${f.type === k ? "selected" : ""}>${esc(d.label)}</option>`).join("")}</select></div>
    </div><div class="row">
      <div class="grow"><label class="field">いつから</label><input type="date" name="date_from" value="${esc(f.date_from)}"></div>
      <div class="grow"><label class="field">いつまで</label><input type="date" name="date_to" value="${esc(f.date_to)}"></div>
      <div class="grow"><label class="field">状態</label><select name="status"><option value="">全部</option>${Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${f.status === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
    </div><p></p><button class="primary big">さがす</button></form>
    <p class="sub">${recs.length}件${recs.length >= 500 ? "（最大500件まで表示）" : ""}</p>
    ${recordTable(recs)}`;
  $("#sf").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = new URLSearchParams([...new FormData(e.target)].filter(([, v]) => v));
    location.hash = "#/search/" + q.toString();
  });
  bindRecordRows();
};
function recordTable(recs) {
  if (!recs.length) return `<div class="notice info">記録はありません</div>`;
  return `<div class="table-wrap"><table><tr><th>日付</th><th>利用者</th><th>種類</th><th>内容</th><th>状態</th><th>記録者</th></tr>
    ${recs.map((r) => `<tr data-rec="${r.id}" style="cursor:pointer"><td>${esc(r.date)}<br><span class="sub">${esc(r.time || "")}</span></td><td>${esc(r.resident_name || "全体")}</td>
      <td>${esc(typeLabel(r.type))}</td><td>${esc(r.text)}${r.comment ? `<div class="notice error">差し戻し理由：${esc(r.comment)}</div>` : ""}</td><td>${badge(r.status)}</td><td>${esc(r.created_by_name || "")}</td></tr>`).join("")}
  </table></div>`;
}
function bindRecordRows() {
  $$("[data-rec]").forEach((tr) => tr.addEventListener("click", () => safe(() => openRecord(Number(tr.dataset.rec)))));
}
async function openRecord(id) {
  const rec = await GET(`/api/records/${id}`);
  const canEdit = isAdmin() || (rec.created_by === S.me.id && rec.status !== "approved");
  const hist = isAdmin() ? await GET(`/api/audit?target=records&target_id=${id}`) : [];
  const m = modal(`<h2 style="margin-top:0">${esc(rec.resident_name || "事業所全体")}｜${esc(typeLabel(rec.type))}</h2>
    <p class="sub">${esc(rec.date)} ${esc(rec.time || "")}　記録：${esc(rec.created_by_name || "")}　${badge(rec.status)}
      ${rec.approved_by_name ? `　確認：${esc(rec.approved_by_name)}（${esc(rec.approved_at)}）` : ""}</p>
    ${rec.comment ? `<div class="notice error">コメント：${esc(rec.comment)}</div>` : ""}
    <textarea id="ed-text" ${canEdit ? "" : "readonly"}>${esc(rec.text)}</textarea>
    ${rec.memo ? `<p class="sub">元のメモ：${esc(rec.memo)}</p>` : ""}
    ${canEdit ? `<p class="sub">直して保存すると「承認待ち」にもどり、もう一度確認されます。</p>` : `<p class="sub">承認済みの記録は職員は直せません。直す必要があれば管理者へ。</p>`}
    <div class="row">${canEdit ? `<button class="primary grow" id="ed-save">直して保存</button>` : ""}<button class="grow" data-close>閉じる</button></div>
    ${hist.length ? `<h3>変更の履歴</h3>${hist.map((h) => `<div class="list-item"><div class="sub" style="min-width:150px">${esc(h.at)}<br>${esc(h.user_name || "")}</div>
      <div><b>${esc(h.action)}</b>${h.before_json ? `<div class="sub">前：${esc(h.before_json)}</div>` : ""}${h.after_json ? `<div class="sub">後：${esc(h.after_json)}</div>` : ""}</div></div>`).join("")}` : ""}`);
  $("#ed-save", m)?.addEventListener("click", () => safe(async () => {
    await POST(`/api/records/${id}`, { text: $("#ed-text", m).value });
    closeModal(); toast("直しました"); route();
  }));
}

/* ---------- 自分の下書き・差し戻し ---------- */
VIEWS.mine = async () => {
  const recs = await GET("/api/mine");
  app().innerHTML = `${back()}<h1>↩️ 自分の下書き・差し戻し</h1>
    <p class="sub">押すと開いて直せます。直して保存すると管理者へ送られます。</p>${recordTable(recs)}`;
  bindRecordRows();
};

/* ---------- 事故・ヒヤリハット ---------- */
VIEWS.incidents = async (arg) => {
  const tab = arg || "list";
  const tabs = `<div class="tabs">${[["list", "一覧"], ["new", "＋ 報告する"], ["stats", "分析"]].map(([k, l]) => `<a class="btn small ${k === tab ? "primary" : ""}" href="#/incidents/${k}">${l}</a>`).join("")}</div>`;
  if (tab === "new") return incidentForm(tabs);
  if (tab === "stats") return incidentStats(tabs);
  const p = new URLSearchParams(location.hash.split("?")[1] || "");
  const list = await GET("/api/incidents?" + new URLSearchParams({ q: p.get("q") || "" }));
  app().innerHTML = `${back()}<h1>⚠️ 事故・ヒヤリハット</h1>${tabs}
    <form class="row card" id="iq"><input class="grow" name="q" placeholder="ことばでさがす（例：浴室、薬）" value="${esc(p.get("q") || "")}" style="flex:1 1 200px"><button class="primary">さがす</button></form>
    <div class="table-wrap"><table><tr><th>日付</th><th>種類</th><th>分類</th><th>利用者</th><th>場所</th><th>何があったか</th><th>再発防止策</th><th>状態</th><th></th></tr>
    ${list.map((i) => `<tr><td>${esc(i.date)}</td><td>${esc(i.kind)}</td><td>${esc(i.category)}</td><td>${esc(i.resident_name || "")}</td><td>${esc(i.place || "")}</td>
      <td>${esc(i.description)}</td><td>${esc(i.prevention || "（未記入）")}</td><td>${badge(i.status)}</td>
      <td><a class="btn small" href="#/docs/incident_report=${i.id}">報告書</a></td></tr>`).join("")}</table></div>`;
  $("#iq").addEventListener("submit", (e) => { e.preventDefault(); location.hash = "#/incidents/list?q=" + encodeURIComponent(e.target.q.value); });
};
function incidentForm(tabs) {
  const cats = S.meta.incident_categories;
  const places = ["居室", "廊下", "浴室", "トイレ", "食堂", "階段", "玄関", "外出先"];
  const st = { kind: "ヒヤリハット", category: "", place: "" };
  app().innerHTML = `${back()}<h1>⚠️ 事故・ヒヤリを報告</h1>${tabs}
    <div class="card">
      <label class="field">どちら？</label><div class="choices">${["ヒヤリハット", "事故"].map((k) => `<button type="button" class="chip ${k === st.kind ? "on" : ""}" data-k="kind" data-val="${k}">${k}</button>`).join("")}</div>
      <p class="sub">ヒヤリハット＝けがなどにならなかったが「ヒヤッ」とした。事故＝けが・誤薬などが起きた。</p>
      <label class="field">分類</label><div class="choices">${cats.map((c) => `<button type="button" class="chip" data-k="category" data-val="${c}">${c}</button>`).join("")}</div>
      <div class="row"><div class="grow"><label class="field">利用者</label><select id="i-res"><option value="">（なし）</option>${activeResidents().map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join("")}</select></div>
        <div class="grow"><label class="field">日付</label><input type="date" id="i-date" value="${esc(todayStr())}" max="${esc(todayStr())}"></div>
        <div class="grow"><label class="field">時刻</label><input type="time" id="i-time" value="${esc(nowTime())}"></div></div>
      <label class="field">場所</label><div class="choices">${places.map((c) => `<button type="button" class="chip" data-k="place" data-val="${c}">${c}</button>`).join("")}</div>
      <label class="field">何があったか（見たこと・聞いたことだけ）</label>${memoBox("i-desc")}
      <button type="button" class="small" id="i-sim" style="margin-top:8px">🔎 似ている過去の事例を見る</button><div id="sim"></div>
      <label class="field">原因と思われること</label>${memoBox("i-cause", "", "わからなければ空でOK")}
      <label class="field">その場でした対応・処置</label>${memoBox("i-act")}
      <label class="field">これからの再発防止策</label>${memoBox("i-prev", "", "例：床が濡れたらすぐ拭く")}
      <p></p><button class="primary big" id="i-save">💾 報告する（管理者が確認）</button>
    </div>`;
  bindMics(app());
  $$("[data-k]").forEach((b) => b.addEventListener("click", () => {
    st[b.dataset.k] = st[b.dataset.k] === b.dataset.val && b.dataset.k !== "kind" ? "" : b.dataset.val;
    $$(`[data-k="${b.dataset.k}"]`).forEach((x) => x.classList.toggle("on", x.dataset.val === st[b.dataset.k]));
  }));
  $("#i-sim").addEventListener("click", () => safe(async () => {
    const q = [st.place, $("#i-desc").value].join(" ");
    const sim = await GET("/api/incidents/similar?" + new URLSearchParams({ q, category: st.category }));
    $("#sim").innerHTML = sim.length ? sim.map((s) => `<div class="notice info"><b>${esc(s.date)} ${esc(s.kind)}／${esc(s.category)}／${esc(s.place || "")}</b><br>${esc(s.description)}<br>→ 対策：${esc(s.prevention || "（未記入）")}</div>`).join("")
      : `<div class="notice ok">似ている事例は見つかりませんでした</div>`;
  }));
  $("#i-save").addEventListener("click", () => safe(async () => {
    if (!st.category) throw new Error("分類を選んでください");
    await POST("/api/incidents", { kind: st.kind, category: st.category, place: st.place, resident_id: $("#i-res").value || null,
      date: $("#i-date").value, time: $("#i-time").value, description: $("#i-desc").value, cause: $("#i-cause").value,
      action_taken: $("#i-act").value, prevention: $("#i-prev").value });
    toast("報告しました。管理者が確認します。"); location.hash = "#/incidents/list";
  }));
}
async function incidentStats(tabs) {
  const p = new URLSearchParams(location.hash.split("?")[1] || "");
  const st = await GET("/api/incidents/stats?" + new URLSearchParams({ start: p.get("start") || "", end: p.get("end") || "" }));
  const bars = (title, pairs) => {
    const max = Math.max(1, ...pairs.map((x) => x[1]));
    return `<div class="card"><h3 style="margin-top:0">${title}</h3>${pairs.map(([k, v]) => `<div class="bar-row"><span>${esc(k)}</span><div class="bar" style="width:${(v / max) * 100}%"></div><b>${v}件</b></div>`).join("") || "なし"}</div>`;
  };
  app().innerHTML = `${back()}<h1>⚠️ 事故・ヒヤリの分析</h1>${tabs}
    <form class="row card" id="sq"><div class="grow"><label class="field">いつから</label><input type="date" name="start" value="${esc(st.start)}"></div>
      <div class="grow"><label class="field">いつまで</label><input type="date" name="end" value="${esc(st.end)}"></div><button class="primary">表示</button></form>
    <div class="notice info">合計 ${st.total}件（事故 ${st.by_kind["事故"] || 0}件／ヒヤリハット ${st.by_kind["ヒヤリハット"] || 0}件）</div>
    ${bars("分類別", st.by_category)}${bars("場所別", st.by_place)}${bars("時間帯別", st.by_time)}${bars("利用者別", st.by_resident)}
    <a class="btn primary big" href="#/docs/incident_meeting=${st.start}_${st.end}">📄 改善会議・研修用の資料をつくる</a>`;
  $("#sq").addEventListener("submit", (e) => { e.preventDefault(); location.hash = `#/incidents/stats?start=${e.target.start.value}&end=${e.target.end.value}`; });
}

/* ---------- 書類をつくる ---------- */
VIEWS.docs = async (arg) => {
  const p = new URLSearchParams(arg || "");
  const kinds = S.meta.doc_kinds;
  if (p.get("incident_report")) return docEditor("incident_report", { incident_id: Number(p.get("incident_report")) });
  if (p.get("incident_meeting")) { const [s, e] = p.get("incident_meeting").split("_"); return docEditor("incident_meeting", { start: s, end: e }); }
  if (p.get("kind")) return docParams(p.get("kind"));
  const docs = await GET("/api/documents");
  app().innerHTML = `${back()}<h1>📄 書類をつくる</h1>
    <p class="sub">記録や報告に入っている内容だけで原案をつくります。空いている欄は赤くなるので、書き足してください。</p>
    <div class="tiles">${Object.entries(kinds).map(([k, l]) => `<a class="tile" href="#/docs/kind=${k}"><span class="ic">📄</span>${esc(l)}</a>`).join("")}</div>
    <h2>保存した書類</h2>
    <div class="card">${docs.map((d) => `<div class="list-item"><div class="grow"><b>${esc(d.title)}</b><div class="sub">${esc(d.created_at)} ${esc(d.created_by_name || "")}</div></div>${badge(d.status)}<button class="small" data-doc="${d.id}">開く</button></div>`).join("") || "まだありません"}</div>`;
  $$("[data-doc]").forEach((b) => b.addEventListener("click", () => {
    const d = docs.find((x) => x.id == b.dataset.doc);
    S.doc = { kind: d.kind, title: d.title, sections: JSON.parse(d.content_json).sections, saved: true };
    renderDoc();
  }));
};
async function docParams(kind) {
  const inc = kind === "incident_report" ? await GET("/api/incidents") : [];
  const t = todayStr();
  const ago = new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10);
  const forms = {
    incident_report: `<label class="field">どの報告？</label><select id="p-inc">${inc.map((i) => `<option value="${i.id}">${esc(i.date)} ${esc(i.kind)}／${esc(i.category)}／${esc(i.resident_name || "")}</option>`).join("")}</select>`,
    incident_meeting: `<label class="field">いつから</label><input type="date" id="p-start" value="${ago}"><label class="field">いつまで</label><input type="date" id="p-end" value="${t}">`,
    minutes: `<label class="field">日時</label><input id="p-date" value="${t} 14:00"><label class="field">場所</label><input id="p-place" value="事業所 会議室">
      <label class="field">出席者</label><input id="p-attendees" placeholder="例：管理 花子、職員 太郎"><label class="field">議題</label><input id="p-agenda">
      <label class="field">内容（メモ・録音を文字にしたもの）</label>${memoBox("p-memo")}<label class="field">決定事項</label>${memoBox("p-decisions")}<label class="field">宿題（担当・期限）</label><input id="p-todo">`,
    training: `<label class="field">研修名</label><input id="p-title" placeholder="例：感染症対策研修"><label class="field">日時</label><input id="p-date" value="${t}">
      <label class="field">講師</label><input id="p-lecturer"><label class="field">参加者</label><input id="p-attendees"><label class="field">内容</label>${memoBox("p-memo")}<label class="field">感想・理解度</label>${memoBox("p-feedback")}`,
    monitoring: `<label class="field">利用者</label><select id="p-res">${activeResidents().map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join("")}</select>
      <label class="field">いつから</label><input type="date" id="p-start" value="${ago}"><label class="field">いつまで</label><input type="date" id="p-end" value="${t}">`,
  };
  app().innerHTML = `${back("docs")}<h1>📄 ${esc(S.meta.doc_kinds[kind])}</h1><div class="card">${forms[kind]}<p></p><button class="primary big" id="p-go">✨ 原案をつくる</button></div>`;
  bindMics(app());
  $("#p-go").addEventListener("click", () => safe(() => {
    const v = (id) => $("#" + id)?.value || "";
    const params = {
      incident_report: { incident_id: Number(v("p-inc")) }, incident_meeting: { start: v("p-start"), end: v("p-end") },
      minutes: { date: v("p-date"), place: v("p-place"), attendees: v("p-attendees"), agenda: v("p-agenda"), memo: v("p-memo"), decisions: v("p-decisions"), todo: v("p-todo") },
      training: { title: v("p-title"), date: v("p-date"), lecturer: v("p-lecturer"), attendees: v("p-attendees"), memo: v("p-memo"), feedback: v("p-feedback") },
      monitoring: { resident_id: Number(v("p-res")), start: v("p-start"), end: v("p-end") },
    }[kind];
    return docEditor(kind, params);
  }));
}
async function docEditor(kind, params) {
  const d = await POST("/api/documents/draft", { kind, params });
  S.doc = { kind, ...d, saved: false };
  renderDoc();
}
function renderDoc() {
  const D = S.doc;
  app().innerHTML = `${back("docs", "← 書類の一覧")}
    <div class="card"><h1 id="d-title">${esc(D.title)}</h1>
    <div id="d-miss"></div>
    ${D.sections.map((s, i) => `<div class="doc-sec"><label class="field">${esc(s.heading)}${s.required ? " <span class='sub'>（必須）</span>" : ""}</label>
      <textarea data-sec="${i}" ${D.saved ? "readonly" : ""} style="min-height:${Math.max(60, Math.min(320, (s.body || "").split("\n").length * 30 + 30))}px">${esc(s.body)}</textarea></div>`).join("")}
    <div class="row no-print" style="margin-top:12px">
      ${D.saved ? "" : `<button class="primary grow" id="d-save">💾 保存して承認へ</button>`}
      <button class="grow" id="d-print">🖨️ 印刷・PDF</button><button class="grow" id="d-word">Word形式(.doc)で保存</button></div></div>`;
  const check = () => {
    const miss = D.sections.filter((s) => s.required && !(s.body || "").trim()).map((s) => s.heading);
    $$("[data-sec]").forEach((t) => t.classList.toggle("missing", D.sections[t.dataset.sec].required && !t.value.trim()));
    $("#d-miss").innerHTML = miss.length ? `<div class="notice error">記入もれ：${esc(miss.join("、"))}</div>` : `<div class="notice ok">必須の欄はすべて書けています</div>`;
    return miss;
  };
  $$("[data-sec]").forEach((t) => t.addEventListener("input", () => { D.sections[t.dataset.sec].body = t.value; check(); }));
  check();
  $("#d-save")?.addEventListener("click", () => safe(async () => {
    if (check().length) throw new Error("記入もれがあります。赤い欄を書いてください。");
    await POST("/api/documents", { kind: D.kind, title: D.title, sections: D.sections });
    toast("保存しました。管理者が確認します。"); location.hash = "#/docs"; route();
  }));
  $("#d-print").addEventListener("click", () => window.print());
  $("#d-word").addEventListener("click", () => {
    const body = D.sections.map((s) => `<h3>${esc(s.heading)}</h3><p>${esc(s.body).replace(/\n/g, "<br>")}</p>`).join("");
    const html = `<html><head><meta charset="utf-8"><title>${esc(D.title)}</title></head><body><h1>${esc(D.title)}</h1>${body}</body></html>`;
    download(new Blob(["﻿" + html], { type: "application/msword" }), `${D.title}.doc`);
  });
}
function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

/* ---------- 毎日のチェック ---------- */
VIEWS.checklist = async (arg) => {
  const date = arg || todayStr();
  const items = await GET(`/api/checklist?date=${date}`);
  const done = items.filter((i) => i.done_at).length;
  const cats = [...new Set(items.map((i) => i.category))];
  app().innerHTML = `${back()}<h1>✅ 毎日のチェック</h1>
    <div class="row"><input type="date" id="c-date" value="${esc(date)}" max="${esc(todayStr())}" style="max-width:220px"><b>${done} / ${items.length} 完了</b></div>
    <div class="progress" style="margin:10px 0"><div style="width:${items.length ? (done / items.length) * 100 : 0}%"></div></div>
    ${done < items.length ? `<div class="notice warn">まだの項目：${items.filter((i) => !i.done_at).length}件</div>` : `<div class="notice ok">全部できました 👍</div>`}
    ${cats.map((c) => `<div class="card"><h2 style="margin-top:0">${esc(c)}</h2>${items.filter((i) => i.category === c).map((i) => `
      <div class="list-item"><button class="chip ${i.done_at ? "on" : ""}" data-item="${i.id}" data-done="${i.done_at ? 1 : 0}" style="min-width:110px">${i.done_at ? "できた" : "まだ"}</button>
      <div class="grow"><b>${esc(i.name)}</b>${i.done_at ? `<div class="sub">${esc(i.done_by)}　${esc(i.done_at.slice(11, 16))}</div>` : ""}</div></div>`).join("")}</div>`).join("")}`;
  $("#c-date").addEventListener("change", (e) => (location.hash = "#/checklist/" + e.target.value));
  $$("[data-item]").forEach((b) => b.addEventListener("click", () => safe(async () => {
    await POST("/api/checklist/done", { item_id: Number(b.dataset.item), date, done: b.dataset.done !== "1" });
    VIEWS.checklist(date);
  })));
};

/* ---------- 期限・提出物 ---------- */
VIEWS.deadlines = async () => {
  const list = await GET("/api/deadlines");
  const t = todayStr();
  app().innerHTML = `${back()}<h1>📅 期限・提出物</h1>
    <div class="card">${list.map((d) => {
      const late = !d.done && d.due_date < t;
      return `<div class="list-item"><div class="grow"><b>${esc(d.title)}</b><div class="sub">期限 ${esc(d.due_date)}　担当 ${esc(d.assignee || "未定")}</div>
        ${late ? '<span class="badge returned">期限切れ</span>' : ""}</div>${d.done ? '<span class="badge approved">完了</span>' : ""}
        ${isAdmin() ? `<button class="small" data-dl="${d.id}" data-done="${d.done}">${d.done ? "未完了にもどす" : "完了にする"}</button>` : ""}</div>`;
    }).join("") || "なし"}</div>
    ${isAdmin() ? `<h2>追加する</h2><div class="card"><label class="field">内容</label><input id="dl-t" placeholder="例：運営指導の資料提出">
      <div class="row"><div class="grow"><label class="field">期限</label><input type="date" id="dl-d" value="${esc(t)}"></div>
      <div class="grow"><label class="field">担当</label><select id="dl-a"><option value="">未定</option>${S.users.filter((u) => u.active).map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("")}</select></div></div>
      <p></p><button class="primary big" id="dl-add">追加</button></div>` : ""}`;
  $$("[data-dl]").forEach((b) => b.addEventListener("click", () => safe(async () => { await POST("/api/deadlines", { id: Number(b.dataset.dl), done: b.dataset.done !== "1" }); route(); })));
  $("#dl-add")?.addEventListener("click", () => safe(async () => {
    await POST("/api/deadlines", { title: $("#dl-t").value, due_date: $("#dl-d").value, assignee_id: $("#dl-a").value || null });
    toast("追加しました"); route();
  }));
};

/* ---------- 確認・承認 ---------- */
VIEWS.approval = async (arg) => {
  if (!isAdmin()) return VIEWS.home();
  const tab = arg || "records";
  const a = await GET("/api/approvals");
  const labels = { records: "記録", incidents: "事故・ヒヤリ", documents: "書類", plans: "個別支援計画" };
  const list = a[tab];
  const line = {
    records: (r) => `<b>${esc(r.date)} ${esc(r.resident_name || "全体")}｜${esc(typeLabel(r.type))}</b><div>${esc(r.text)}</div><div class="sub">記録：${esc(r.created_by_name || "")}</div>`,
    incidents: (r) => `<b>${esc(r.date)} ${esc(r.kind)}／${esc(r.category)}｜${esc(r.resident_name || "")}</b><div>${esc(r.description)}</div><div class="sub">対策：${esc(r.prevention || "（未記入）")}　報告：${esc(r.created_by_name || "")}</div>`,
    documents: (r) => `<b>${esc(r.title)}</b><div class="sub">${esc(r.created_at)} ${esc(r.created_by_name || "")}</div><details><summary>中身を見る</summary>${JSON.parse(r.content_json).sections.map((s) => `<p><b>${esc(s.heading)}</b><br><span class="pre">${esc(s.body)}</span></p>`).join("")}</details>`,
    plans: (r) => `<b>${esc(r.resident_name)}</b><div>目標：${esc(r.goal)}</div><div class="sub">支援：${esc(r.support)}　期間：${esc(r.start_date)}〜${esc(r.end_date)}</div>`,
  }[tab];
  app().innerHTML = `${back()}<h1>🖊️ 確認・承認</h1>
    <div class="tabs">${Object.entries(labels).map(([k, l]) => `<a class="btn small ${k === tab ? "primary" : ""}" href="#/approval/${k}">${l}（${a[k].length}）</a>`).join("")}</div>
    ${list.length ? `<div class="row"><label class="check-line"><input type="checkbox" id="ap-all"> 全部選ぶ</label><button class="primary" id="ap-ok">選んだものを承認</button></div>
    <div class="card">${list.map((r) => `<div class="list-item"><input type="checkbox" data-ap="${r.id}"><div class="grow">${line(r)}</div>
      <button class="small danger" data-ret="${r.id}">差し戻し</button></div>`).join("")}</div>` : `<div class="notice ok">承認待ちはありません</div>`}`;
  $("#ap-all")?.addEventListener("change", (e) => $$("[data-ap]").forEach((c) => (c.checked = e.target.checked)));
  $("#ap-ok")?.addEventListener("click", () => safe(async () => {
    const ids = $$("[data-ap]").filter((c) => c.checked).map((c) => Number(c.dataset.ap));
    if (!ids.length) throw new Error("承認するものを選んでください");
    const r = await POST("/api/approve", { target: tab, ids, action: "approve" });
    toast(`${r.updated}件 承認しました`); route();
  }));
  $$("[data-ret]").forEach((b) => b.addEventListener("click", () => {
    const m = modal(`<h2 style="margin-top:0">差し戻す理由</h2><p class="sub">記録した職員に表示されます。何を直せばよいか具体的に書いてください。</p>
      <textarea id="ret-c" placeholder="例：体温の数字を確認してください"></textarea><div class="row" style="margin-top:10px"><button class="primary grow" id="ret-go">差し戻す</button><button class="grow" data-close>やめる</button></div>`);
    $("#ret-go", m).addEventListener("click", () => safe(async () => {
      await POST("/api/approve", { target: tab, id: Number(b.dataset.ret), action: "return", comment: $("#ret-c", m).value });
      closeModal(); toast("差し戻しました"); route();
    }));
  }));
};

/* ---------- 請求前チェック ---------- */
VIEWS.checks = async (arg) => {
  if (!isAdmin()) return VIEWS.home();
  const month = arg || thisMonth();
  app().innerHTML = `${back()}<h1>🧮 請求前チェック</h1>
    <div class="card row"><div class="grow"><label class="field">対象の月</label><input type="month" id="ck-m" value="${esc(month)}"></div>
      <button class="primary big" id="ck-go" style="flex:1 1 200px">チェックする</button></div>
    <div class="row no-print"><a class="btn small" href="/api/export/records.csv?month=${esc(month)}">記録をExcel(CSV)で出す</a>
      <a class="btn small" href="/api/export/occupancy.csv?month=${esc(month)}">稼働表をExcel(CSV)で出す</a>
      ${isManager() ? `<a class="btn small" href="/api/export/attendance.csv?month=${esc(month)}">勤務実績をExcel(CSV)で出す</a>` : ""}</div>
    <div id="ck-res"><p class="sub">「チェックする」を押すと、記録もれ・稼働表・シフトと打刻のちがい・未承認などを調べます。</p></div>`;
  $("#ck-m").addEventListener("change", (e) => (location.hash = "#/checks/" + e.target.value));
  const run = async () => {
    const r = await GET(`/api/checks?month=${month}`);
    const lv = { error: "要修正", warn: "要確認", info: "お知らせ" };
    const fixLink = (i) => ({
      record: `#/record/resident=${i.resident_id || 0}&date=${i.date || ""}`, occupancy: `#/occupancy/${month}`,
      attendance: `#/attendance/${month}`, approval: "#/approval", plans: "#/master/plans",
    }[i.link]);
    $("#ck-res").innerHTML = `<div class="row" style="margin:12px 0">
        <span class="badge returned">要修正 ${r.summary.error}</span><span class="badge submitted">要確認 ${r.summary.warn}</span><span class="badge draft">お知らせ ${r.summary.info}</span>
        <span class="sub">チェック日時 ${esc(r.checked_at)}（${esc(r.range[0])}〜${esc(r.range[1])}）</span><button class="small" id="ck-again">🔁 もう一度チェック</button></div>
      ${r.issues.length ? r.issues.map((i) => `<div class="notice ${i.level}"><b>[${lv[i.level]}｜${esc(i.category)}]</b> ${i.date ? esc(i.date) + "　" : ""}${esc(i.message)}
        ${fixLink(i) ? ` <a href="${fixLink(i)}">直す ›</a>` : ""}</div>`).join("") : `<div class="notice ok">問題は見つかりませんでした 👍</div>`}`;
    $("#ck-again").addEventListener("click", () => safe(run));
  };
  $("#ck-go").addEventListener("click", () => safe(run));
};

/* ---------- 稼働表 ---------- */
VIEWS.occupancy = async (arg) => {
  if (!isAdmin()) return VIEWS.home();
  const month = arg || thisMonth();
  const o = await GET(`/api/occupancy?month=${month}`);
  const cycle = ["在宅", "外泊", "入院", "退去", ""];
  const mark = { 在宅: "○", 外泊: "外", 入院: "入", 退去: "退" };
  app().innerHTML = `${back()}<h1>🗓️ 稼働表（在宅・外泊・入院）</h1>
    <div class="row"><input type="month" id="oc-m" value="${esc(month)}" style="max-width:220px"><a class="btn small" href="/api/export/occupancy.csv?month=${esc(month)}">Excel(CSV)で出す</a></div>
    <p class="sub">マスを押すたびに ○在宅 → 外泊 → 入院 → 退去 → 空 に変わります。</p>
    <div class="table-wrap"><table class="matrix"><tr><th>利用者</th>${o.days.map((d) => `<th>${Number(d.slice(8))}</th>`).join("")}<th>在宅</th></tr>
    ${o.residents.map((r) => `<tr><th>${esc(r.name)}</th>${o.days.map((d) => { const s = o.data[`${r.id}|${d}`] || ""; return `<td class="cell st-${s}" data-r="${r.id}" data-d="${d}" data-s="${s}">${mark[s] || ""}</td>`; }).join("")}
      <td>${o.days.filter((d) => o.data[`${r.id}|${d}`] === "在宅").length}</td></tr>`).join("")}</table></div>`;
  $("#oc-m").addEventListener("change", (e) => (location.hash = "#/occupancy/" + e.target.value));
  $$("td.cell").forEach((td) => td.addEventListener("click", () => safe(async () => {
    const next = cycle[(cycle.indexOf(td.dataset.s) + 1) % cycle.length];
    await POST("/api/occupancy", { resident_id: Number(td.dataset.r), date: td.dataset.d, status: next });
    td.dataset.s = next; td.className = `cell st-${next}`; td.textContent = mark[next] || "";
  })));
};

/* ---------- シフト・勤怠 ---------- */
VIEWS.attendance = async (arg) => {
  const month = arg || thisMonth();
  const s = await GET(`/api/shifts?month=${month}`);
  const att = Object.fromEntries(s.attendance.map((a) => [`${a.user_id}|${a.date}`, a]));
  const mine = isManager() ? s.shifts : s.shifts.filter((x) => x.user_id === S.me.id);
  const diff = (a, b) => { if (!a || !b) return true; const m = (t) => +t.slice(0, 2) * 60 + +t.slice(3); return Math.abs(m(a) - m(b)) >= 15; };
  app().innerHTML = `${back()}<h1>⏰ シフト・勤怠</h1>
    <div class="row"><button class="primary" data-clock="in">🟢 出勤</button><button data-clock="out">🔴 退勤</button>
      <input type="month" id="at-m" value="${esc(month)}" style="max-width:220px"></div>
    <p class="sub">赤い行はシフトと打刻が15分以上ちがう、または打刻がない日です。</p>
    <div class="table-wrap"><table><tr><th>日付</th><th>職員</th><th>シフト</th><th>出勤</th><th>退勤</th></tr>
    ${mine.map((x) => { const a = att[`${x.user_id}|${x.date}`] || {}; const bad = diff(x.start, a.clock_in) || diff(x.end, a.clock_out);
      return `<tr class="${bad ? "missing" : ""}"><td>${esc(x.date)}</td><td>${esc(x.user_name)}</td><td>${esc(x.start)}〜${esc(x.end)}</td><td>${esc(a.clock_in || "なし")}</td><td>${esc(a.clock_out || "なし")}</td></tr>`; }).join("")}</table></div>
    ${isManager() ? `<h2>シフト登録・打刻の修正（管理者）</h2><div class="card">
      <div class="row"><div class="grow"><label class="field">職員</label><select id="at-u">${S.users.filter((u) => u.active).map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("")}</select></div>
      <div class="grow"><label class="field">日付</label><input type="date" id="at-d" value="${esc(todayStr())}"></div></div>
      <div class="row"><div class="grow"><label class="field">開始／出勤</label><input type="time" id="at-s" value="09:00"></div><div class="grow"><label class="field">終了／退勤</label><input type="time" id="at-e" value="18:00"></div></div>
      <p></p><div class="row"><button class="primary grow" id="at-shift">シフトとして登録</button><button class="grow" id="at-att">打刻を修正</button></div>
      <p class="sub">打刻の修正は操作履歴に「だれが・いつ・前→後」が残ります。</p></div>` : ""}`;
  $("#at-m").addEventListener("change", (e) => (location.hash = "#/attendance/" + e.target.value));
  $$("[data-clock]").forEach((b) => b.addEventListener("click", () => safe(async () => {
    const r = await POST("/api/clock", { kind: b.dataset.clock }); toast(`記録しました（${r.time}）`); route();
  })));
  const vals = () => ({ user_id: Number($("#at-u").value), date: $("#at-d").value });
  $("#at-shift")?.addEventListener("click", () => safe(async () => { await POST("/api/shifts", { ...vals(), start: $("#at-s").value, end: $("#at-e").value }); toast("登録しました"); route(); }));
  $("#at-att")?.addEventListener("click", () => safe(async () => { await POST("/api/attendance", { ...vals(), clock_in: $("#at-s").value, clock_out: $("#at-e").value }); toast("修正しました"); route(); }));
};

/* ---------- 利用者・計画・職員 ---------- */
VIEWS.master = async (arg) => {
  if (!isAdmin()) return VIEWS.home();
  const tab = arg || "residents";
  const tabs = `<div class="tabs">${[["residents", "利用者"], ["plans", "個別支援計画"], ...(isManager() ? [["users", "職員"], ["items", "チェック項目"]] : [])]
    .map(([k, l]) => `<a class="btn small ${k === tab ? "primary" : ""}" href="#/master/${k}">${l}</a>`).join("")}</div>`;
  const form = (fields, id = "mf") => `<div class="card" id="${id}">${fields.map(([k, l, type, opts]) => type === "select"
    ? `<label class="field">${l}</label><select name="${k}">${opts}</select>`
    : type === "area" ? `<label class="field">${l}</label><textarea name="${k}"></textarea>` : `<label class="field">${l}</label><input name="${k}" type="${type || "text"}">`).join("")}
    <p></p><div class="row"><button class="primary grow" data-save>保存</button><button class="grow" data-clear>新しく入力</button></div></div>`;
  const fill = (root, obj) => $$("[name]", root).forEach((el) => (el.value = obj?.[el.name] ?? (el.tagName === "SELECT" ? el.options[0]?.value ?? "" : "")));
  const read = (root) => Object.fromEntries($$("[name]", root).map((el) => [el.name, el.value]));
  let list = [], save = null;
  if (tab === "residents") {
    await reloadMasters(); list = S.residents;
    app().innerHTML = `${back()}<h1>👥 利用者</h1>${tabs}
      <div class="card">${list.map((r) => `<div class="list-item"><div class="grow"><b>${esc(r.name)}</b>（${esc(r.kana || "")}）${esc(r.room || "")}号室 ${r.active ? "" : '<span class="badge draft">退去</span>'}<div class="sub">${esc(r.notes || "")}</div></div><button class="small" data-edit="${r.id}">直す</button></div>`).join("")}</div>
      <h2 id="ft">新しく登録</h2>${form([["name", "名前"], ["kana", "ふりがな"], ["room", "部屋"], ["birth_date", "生年月日", "date"], ["notes", "特記事項（申し送りに出ます）", "area"], ["active", "状態", "select", '<option value="1">入居中</option><option value="0">退去</option>']])}`;
    save = async (v) => { await POST("/api/residents", { ...v, active: v.active === "1" }); await reloadMasters(); };
  } else if (tab === "plans") {
    list = await GET("/api/plans");
    app().innerHTML = `${back()}<h1>👥 個別支援計画</h1>${tabs}
      <div class="card">${list.map((p) => `<div class="list-item"><div class="grow"><b>${esc(p.resident_name)}</b> ${badge(p.status)}<div>目標：${esc(p.goal)}</div><div class="sub">支援：${esc(p.support)}／期間 ${esc(p.start_date)}〜${esc(p.end_date)}／次のモニタリング ${esc(p.next_monitoring)}</div></div><button class="small" data-edit="${p.id}">直す</button></div>`).join("")}</div>
      <h2 id="ft">新しく登録</h2>${form([["resident_id", "利用者", "select", activeResidents().map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join("")], ["goal", "目標", "area"], ["support", "支援内容", "area"], ["start_date", "開始日", "date"], ["end_date", "終了日", "date"], ["next_monitoring", "次のモニタリング日", "date"]])}`;
    save = (v) => POST("/api/plans", { ...v, resident_id: Number(v.resident_id) });
  } else if (tab === "users" && isManager()) {
    await reloadMasters(); list = S.users;
    const roles = '<option value="staff">職員</option><option value="sabikan">サービス管理責任者</option><option value="manager">管理者</option>';
    app().innerHTML = `${back()}<h1>👥 職員</h1>${tabs}
      <div class="card">${list.map((u) => `<div class="list-item"><div class="grow"><b>${esc(u.name)}</b>　ID：${esc(u.login_id)}　${esc({ staff: "職員", sabikan: "サビ管", manager: "管理者" }[u.role])} ${u.active ? "" : '<span class="badge draft">停止中</span>'}</div><button class="small" data-edit="${u.id}">直す</button></div>`).join("")}</div>
      <h2 id="ft">新しく登録</h2>${form([["name", "名前"], ["login_id", "ログインID（新規のときだけ）"], ["password", "パスワード（8文字以上。変えるときだけ）", "password"], ["role", "役割", "select", roles], ["active", "状態", "select", '<option value="1">利用中</option><option value="0">停止（退職など）</option>']])}`;
    save = async (v) => { await POST("/api/users", { ...v, active: v.active === "1" }); await reloadMasters(); };
  } else if (tab === "items" && isManager()) {
    const items = await GET(`/api/checklist?date=${todayStr()}`);
    app().innerHTML = `${back()}<h1>👥 チェック項目</h1>${tabs}<div class="card">${items.map((i) => `<div class="list-item"><b style="min-width:120px">${esc(i.category)}</b>${esc(i.name)}</div>`).join("")}</div>
      <h2>追加</h2>${form([["category", "分類（例：服薬、感染症対策、防災、事故防止）"], ["name", "項目"]])}`;
    save = (v) => POST("/api/checklist/items", v);
  } else return VIEWS.home();
  const root = $("#mf");
  fill(root, null);
  $$("[data-edit]").forEach((b) => b.addEventListener("click", () => {
    const obj = list.find((x) => x.id == b.dataset.edit);
    fill(root, { ...obj, active: obj.active === undefined ? undefined : String(obj.active), password: "" });
    root.dataset.id = obj.id; $("#ft").textContent = "直す：" + (obj.name || obj.resident_name);
    const lid = $("[name=login_id]", root); if (lid) lid.disabled = true;
    root.scrollIntoView({ behavior: "smooth" });
  }));
  $("[data-clear]", root).addEventListener("click", () => route());
  $("[data-save]", root).addEventListener("click", () => safe(async () => {
    const v = read(root); if (root.dataset.id) v.id = Number(root.dataset.id);
    await save(v); toast("保存しました"); route();
  }));
};

/* ---------- 操作の履歴 ---------- */
VIEWS.audit = async () => {
  if (!isAdmin()) return VIEWS.home();
  const list = await GET("/api/audit");
  app().innerHTML = `${back()}<h1>📜 操作の履歴</h1><p class="sub">だれが・いつ・何をしたかが自動で残ります（最新300件）。消したり直したりはできません。</p>
    <div class="table-wrap"><table><tr><th>日時</th><th>職員</th><th>操作</th><th>対象</th><th>変更前</th><th>変更後</th></tr>
    ${list.map((a) => `<tr><td>${esc(a.at)}</td><td>${esc(a.user_name || "")}</td><td>${esc(a.action)}</td><td>${esc(a.target || "")} ${esc(a.target_id ?? "")}</td>
      <td class="sub">${esc(a.before_json || "")}</td><td class="sub">${esc(a.after_json || "")}</td></tr>`).join("")}</table></div>`;
};

boot();
