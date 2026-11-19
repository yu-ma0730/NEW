// Book Explorer
// web-scraper/scraper.py が出力した books.json を読み込み、検索・絞り込み・グラフ表示を行う。
// 外部ライブラリは使わず、ブラウザ標準の機能だけで動く。

(() => {
  "use strict";

  const PAGE_SIZE = 24;
  const $ = (id) => document.getElementById(id);

  const state = { books: [], page: 1 };
  const el = {
    q: $("q"), cat: $("cat"), rating: $("rating"), pmin: $("pmin"), pmax: $("pmax"), sort: $("sort"),
  };

  // ---------- データ読み込み ----------

  function validate(data) {
    // scraper.py の出力形式（{ books: [...] }）か、本の配列そのものを受け付ける
    const books = Array.isArray(data) ? data : data && data.books;
    if (!Array.isArray(books)) throw new Error("books の配列が見つかりません");
    return books
      .filter((b) => b && typeof b.title === "string")
      .map((b) => ({
        title: b.title,
        category: String(b.category || "Unknown"),
        price: Number(b.price) || 0,
        rating: Number(b.rating) || 0,
        in_stock: b.in_stock === true || b.in_stock === "True",
        url: safeUrl(b.url),
        image_url: safeUrl(b.image_url),
      }));
  }

  // http(s) 以外の URL（javascript: など）は危険なので使わない
  function safeUrl(u) {
    try {
      const url = new URL(String(u || ""), location.href);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
    } catch {
      return "";
    }
  }

  function load(data, label) {
    state.books = validate(data);
    $("source").textContent = `${label}・${state.books.length.toLocaleString()} 冊` +
      (data && data.scraped_at ? `・取得日時 ${fmtDate(data.scraped_at)}` : "");
    const cats = [...new Set(state.books.map((b) => b.category))].sort((a, b) => a.localeCompare(b));
    el.cat.replaceChildren(new Option("すべて", ""), ...cats.map((c) => new Option(c, c)));
    state.page = 1;
    render();
  }

  // ISO 形式の日時を、見ている人の地域の時刻で表示する
  function fmtDate(iso) {
    const d = new Date(iso);
    return isNaN(d) ? String(iso) : d.toLocaleString("ja-JP", { dateStyle: "medium", timeStyle: "short" });
  }

  function showNotice(msg) {
    $("notice").textContent = msg;
    $("notice").hidden = !msg;
  }

  fetch("data/books.json")
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => { load(d, "data/books.json"); showNotice(""); })
    .catch(() => {
      $("source").textContent = "データ未読み込み";
      showNotice("data/books.json を自動で読み込めませんでした（ファイルを直接開いた場合に起こります）。" +
        "右上の「JSONを読み込む」から books.json を選ぶか、README の手順でローカルサーバーを起動してください。");
    });

  $("file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      load(JSON.parse(await file.text()), file.name);
      showNotice("");
    } catch (err) {
      showNotice(`読み込みに失敗しました: ${err.message}`);
    }
    e.target.value = "";
  });

  // ---------- 絞り込み ----------

  function filtered() {
    const q = el.q.value.trim().toLowerCase();
    const cat = el.cat.value;
    const minRating = Number(el.rating.value);
    const pmin = el.pmin.value === "" ? -Infinity : Number(el.pmin.value);
    const pmax = el.pmax.value === "" ? Infinity : Number(el.pmax.value);
    const list = state.books.filter((b) =>
      (!q || b.title.toLowerCase().includes(q)) &&
      (!cat || b.category === cat) &&
      (minRating === 5 ? b.rating === 5 : b.rating >= minRating) &&
      b.price >= pmin && b.price <= pmax
    );
    const sorters = {
      "title": (a, b) => a.title.localeCompare(b.title),
      "price-asc": (a, b) => a.price - b.price,
      "price-desc": (a, b) => b.price - a.price,
      "rating-desc": (a, b) => b.rating - a.rating || a.price - b.price,
    };
    return list.sort(sorters[el.sort.value] || sorters.title);
  }

  // ---------- 描画 ----------

  const fmtPrice = (n) => `£${n.toFixed(2)}`;
  const stars = (n) => "★".repeat(n) + "☆".repeat(5 - n);

  function render() {
    const list = filtered();
    renderKpis(list);
    renderCategoryChart(list);
    renderPriceChart(list);
    renderRatingChart(list);
    renderGrid(list);
  }

  function renderKpis(list) {
    const avg = (f) => list.reduce((s, b) => s + f(b), 0) / list.length;
    $("k-count").textContent = list.length.toLocaleString();
    $("k-price").textContent = list.length ? fmtPrice(avg((b) => b.price)) : "–";
    $("k-rating").textContent = list.length ? `★${avg((b) => b.rating).toFixed(2)}` : "–";
    $("k-cats").textContent = new Set(list.map((b) => b.category)).size;
  }

  function barRow(label, value, max, { clickable = false, active = false, title = "" } = {}) {
    const row = document.createElement(clickable ? "button" : "div");
    row.className = "bar-row" + (active ? " active" : "");
    if (clickable) row.type = "button";
    if (title) row.title = title;
    const lab = document.createElement("span");
    lab.className = "bar-label";
    lab.textContent = label;
    const track = document.createElement("span");
    track.className = "bar-track";
    const fill = document.createElement("span");
    fill.className = "bar-fill";
    fill.style.display = "block";
    fill.style.width = max ? `${(value / max) * 100}%` : "0";
    track.append(fill);
    const num = document.createElement("span");
    num.className = "bar-num";
    num.textContent = value;
    row.append(lab, track, num);
    return row;
  }

  function renderCategoryChart(list) {
    const counts = new Map();
    list.forEach((b) => counts.set(b.category, (counts.get(b.category) || 0) + 1));
    const top = [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 10);
    const max = top.length ? top[0][1] : 0;
    const rows = top.map(([name, n]) => {
      const row = barRow(name, n, max, {
        clickable: true, active: el.cat.value === name, title: `${name} で絞り込む（もう一度押すと解除）`,
      });
      row.addEventListener("click", () => {
        el.cat.value = el.cat.value === name ? "" : name;
        state.page = 1;
        render();
      });
      return row;
    });
    $("chart-cat").replaceChildren(...rows);
  }

  function renderPriceChart(list) {
    // £10〜£60 を £5 刻みで集計（サイトの価格はこの範囲に収まる）。範囲外は両端に含める
    const edges = [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60];
    const bins = new Array(edges.length - 1).fill(0);
    list.forEach((b) => {
      let i = Math.floor((b.price - edges[0]) / 5);
      i = Math.min(Math.max(i, 0), bins.length - 1);
      bins[i]++;
    });
    const max = Math.max(1, ...bins);
    const cols = bins.map((n, i) => {
      const col = document.createElement("div");
      col.className = "hist-col";
      col.title = `£${edges[i]}〜£${edges[i + 1]}: ${n} 冊`;
      const num = document.createElement("span");
      num.className = "hist-num";
      num.textContent = n || "";
      const bar = document.createElement("div");
      bar.className = "hist-bar";
      bar.style.height = `${(n / max) * 100}%`;
      const lab = document.createElement("span");
      lab.className = "hist-label";
      lab.textContent = i % 2 === 0 ? `£${edges[i]}` : "";
      const area = document.createElement("div");
      area.className = "hist-area";
      area.append(bar);
      col.append(num, area, lab);
      return col;
    });
    $("chart-price").replaceChildren(...cols);
  }

  function renderRatingChart(list) {
    const counts = [5, 4, 3, 2, 1].map((r) => [r, list.filter((b) => b.rating === r).length]);
    const max = Math.max(0, ...counts.map((c) => c[1]));
    $("chart-rating").replaceChildren(...counts.map(([r, n]) => barRow(stars(r), n, max)));
  }

  function renderGrid(list) {
    const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    state.page = Math.min(state.page, pages);
    const start = (state.page - 1) * PAGE_SIZE;
    const slice = list.slice(start, start + PAGE_SIZE);

    const cards = slice.map((b) => {
      const a = document.createElement("a");
      a.className = "card";
      if (b.url) { a.href = b.url; a.target = "_blank"; a.rel = "noopener"; }
      if (b.image_url) {
        const img = document.createElement("img");
        img.src = b.image_url;
        img.alt = "";
        img.loading = "lazy";
        a.append(img);
      }
      const body = document.createElement("div");
      body.className = "card-body";
      const t = document.createElement("span");
      t.className = "card-title";
      t.textContent = b.title;
      t.title = b.title;
      const c = document.createElement("span");
      c.className = "card-cat";
      c.textContent = b.category;
      const foot = document.createElement("div");
      foot.className = "card-foot";
      const p = document.createElement("span");
      p.className = "price";
      p.textContent = fmtPrice(b.price);
      const s = document.createElement("span");
      s.className = "stars";
      s.textContent = stars(b.rating);
      s.setAttribute("aria-label", `評価 ${b.rating} / 5`);
      foot.append(p, s);
      body.append(t, c, foot);
      a.append(body);
      return a;
    });
    $("grid").replaceChildren(...cards);
    $("empty").hidden = list.length > 0 || state.books.length === 0;
    $("page-info").textContent = list.length
      ? `${start + 1}–${start + slice.length} 件目 / ${list.length} 件（${state.page} / ${pages} ページ）`
      : "";
    $("prev").disabled = state.page <= 1;
    $("next").disabled = state.page >= pages;
  }

  // ---------- 操作 ----------

  const rerender = () => { state.page = 1; render(); };
  let timer;
  el.q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(rerender, 150); });
  [el.cat, el.rating, el.sort].forEach((x) => x.addEventListener("change", rerender));
  [el.pmin, el.pmax].forEach((x) => x.addEventListener("input", rerender));

  $("reset").addEventListener("click", () => {
    el.q.value = ""; el.cat.value = ""; el.rating.value = "0"; el.pmin.value = ""; el.pmax.value = ""; el.sort.value = "title";
    rerender();
  });

  const scrollToList = () => $("grid").scrollIntoView({ behavior: "smooth", block: "start" });
  $("prev").addEventListener("click", () => { state.page--; render(); scrollToList(); });
  $("next").addEventListener("click", () => { state.page++; render(); scrollToList(); });

  // 絞り込み結果を CSV で書き出す（Excel で文字化けしないよう BOM を付ける）
  $("download").addEventListener("click", () => {
    const list = filtered();
    if (!list.length) { showNotice("書き出す本がありません"); return; }
    const cols = ["title", "category", "price", "rating", "in_stock", "url", "image_url"];
    const esc = (v) => {
      const s = String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csv = [cols.join(","), ...list.map((b) => cols.map((c) => esc(b[c])).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "books_filtered.csv" });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });
})();
