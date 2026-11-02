/* =========================================================
   設定（公開する前にここを確認してください）
   ========================================================= */
const CONFIG = {
  // フォームの送信先URL（例：Formspree などのフォームサービスのURL）
  // 空のままだと「デモモード」になり、実際には送信されません。
  FORM_ENDPOINT: "",
};

/* =========================================================
   ジャンルの一覧（ヘッダーのリンクと、トップページのカードに使われます）
   ・ジャンルを増やすとき：
       1. 既存のジャンルページ（例：data.html）をコピーして名前を変える
       2. 中の文章を書き換える
       3. 下の一覧に { ... } を1つ追加する
   ・id はページの <body data-genre="..."> と同じにしてください
   ========================================================= */
const GENRES = [
  { id: "web-design", href: "web-design.html", icon: "🎨", title: "AI × Webデザイン",
    summary: "AIを使って、早く・低コストでWebサイトやLPを形にします。" },
  { id: "data", href: "data.html", icon: "📊", title: "AI × データ",
    summary: "手元のデータを、AIで「見える化」して判断に使える形にします。" },
  { id: "automation", href: "automation.html", icon: "⚙️", title: "AI × 業務効率化",
    summary: "毎日のくり返し作業を、AIやツールで自動化・時短します。" },
  { id: "marketing", href: "marketing.html", icon: "📣", title: "AI × マーケティング・SNS",
    summary: "SNS投稿や広告文づくりにAIを取り入れ、発信を続けやすくします。" },
  { id: "writing", href: "writing.html", icon: "📝", title: "AI × 文章・資料作成",
    summary: "企画書、提案資料、マニュアルなどをAIで効率よく作ります。" },
  { id: "training", href: "training.html", icon: "🎓", title: "AI × 社内研修・活用サポート",
    summary: "AIツールの使い方を、チームで使えるレベルまでサポートします。" },
];

/* =========================================================
   チャットボットの回答
   ・q：質問ボタンに表示される文
   ・keys：この言葉が質問に含まれていたら、この回答を返す
   ・a：回答
   ========================================================= */
const CHAT_FAQ = {
  "web-design": [
    { q: "どんなサイトが作れますか？", keys: ["サイト", "作れ", "どんな"], a: "会社紹介サイト、サービス紹介のLP（1ページの宣伝ページ）、ポートフォリオなどを想定しています。内容によって進め方を一緒に決めます。" },
    { q: "デザインの知識がなくても大丈夫？", keys: ["知識", "初心者", "分からない", "わからない"], a: "大丈夫です。「こんな雰囲気にしたい」というイメージや、参考にしたいサイトを教えていただければ、そこから形にしていきます。" },
  ],
  "data": [
    { q: "どんなデータでも扱えますか？", keys: ["データ", "扱え", "どんな"], a: "Excel、CSV、スプレッドシートなどが中心です。まずはどんなデータがあるか教えてください。個人情報を含む場合は、取り扱い方法を事前にご相談します。" },
    { q: "データが整理されていなくても大丈夫？", keys: ["整理", "バラバラ", "汚い"], a: "はい。データの整理から一緒に進めることもできます。" },
  ],
  "automation": [
    { q: "どんな作業が自動化できますか？", keys: ["自動化", "作業", "どんな"], a: "決まった手順のくり返し作業（データの転記、定型メール、集計など）が向いています。まずは今の業務の流れをお聞かせください。" },
    { q: "社内にITに詳しい人がいません", keys: ["詳しい", "IT", "社内", "いない"], a: "その前提で、使い方の説明や手順書づくりまでサポートします。" },
  ],
  "marketing": [
    { q: "どのSNSに対応していますか？", keys: ["SNS", "インスタ", "X", "対応"], a: "Instagram、X（旧Twitter）、ブログなど、お使いの媒体に合わせてご提案します。" },
  ],
  "writing": [
    { q: "AIが作った文章をそのまま使えますか？", keys: ["そのまま", "使え", "AIが"], a: "AIの文章には誤りが含まれることがあるため、人の目で事実確認・調整をする前提で進めます。そのチェック方法もお伝えします。" },
  ],
  "training": [
    { q: "何人から対応できますか？", keys: ["何人", "人数", "1人", "一人"], a: "お一人からチーム単位まで、人数に合わせて内容を調整します。" },
  ],
  // 全ページ共通の回答
  common: [
    { q: "料金はいくらですか？", keys: ["料金", "費用", "値段", "いくら", "価格"], a: "ご相談内容によって変わるため、お話をうかがってからお見積もりします。まずはこのページのフォームからお名前とメールアドレスをお送りください。" },
    { q: "相談の流れは？", keys: ["流れ", "進め", "手順", "どうやって"], a: "① フォームからご連絡 → ② メールで日程調整 → ③ オンラインでヒアリング → ④ ご提案・お見積もり、という流れです。" },
    { q: "オンラインで相談できますか？", keys: ["オンライン", "zoom", "Zoom", "リモート", "対面"], a: "はい、オンラインでのご相談を基本としています。" },
  ],
};

/* =========================================================
   ここから下はページを動かすためのプログラムです
   （ふだんは編集しなくて大丈夫です）
   ========================================================= */

const currentId = document.body.dataset.genre || "";   // トップページは空
const currentGenre = GENRES.find((g) => g.id === currentId) || null;

// --- ヘッダーのリンクを作る ---
const navList = document.getElementById("genre-nav-list");
if (navList) {
  GENRES.forEach((g) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = g.href;
    a.textContent = g.title;
    if (g.id === currentId) a.setAttribute("aria-current", "page"); // 今いるページに印
    li.appendChild(a);
    navList.appendChild(li);
  });
}

// --- トップページのジャンルカードを作る ---
const cardList = document.getElementById("genre-list");
if (cardList) {
  GENRES.forEach((g) => {
    const a = document.createElement("a");
    a.className = "genre-card";
    a.href = g.href;
    a.innerHTML = '<span class="genre-icon" aria-hidden="true"></span><h3></h3><p class="genre-summary"></p><span class="genre-more">詳しく見る →</span>';
    a.querySelector(".genre-icon").textContent = g.icon;
    a.querySelector("h3").textContent = g.title;
    a.querySelector(".genre-summary").textContent = g.summary;
    cardList.appendChild(a);
  });
}

// --- フッターの年 ---
const yearEl = document.getElementById("year");
if (yearEl) yearEl.textContent = new Date().getFullYear();

// --- 相談フォーム ---
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const genreLabel = currentGenre ? currentGenre.title : "（ジャンル未選択）";

document.querySelectorAll(".consult-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const nameInput = form.querySelector('input[name="name"]');
    const emailInput = form.querySelector('input[name="email"]');
    const name = nameInput.value.trim();
    const email = emailInput.value.trim();
    const errorEl = form.querySelector(".form-error");
    const doneEl = form.querySelector(".form-done");
    errorEl.textContent = "";
    doneEl.textContent = "";

    // 入力チェック
    if (!name) { errorEl.textContent = "お名前を入力してください。"; nameInput.focus(); return; }
    if (!EMAIL_RE.test(email)) { errorEl.textContent = "メールアドレスの形式が正しくありません。"; emailInput.focus(); return; }

    // 送信先が未設定のときはデモモード（実際には送らない）
    if (!CONFIG.FORM_ENDPOINT) {
      doneEl.textContent = `【デモ表示】${name} 様、「${genreLabel}」のご相談を受け付けました。※送信先が未設定のため、実際には送信されていません。`;
      form.reset();
      return;
    }

    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const res = await fetch(CONFIG.FORM_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ name, email, genre: genreLabel }),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      doneEl.textContent = `${name} 様、ありがとうございます。「${genreLabel}」のご相談を受け付けました。追ってメールでご連絡します。`;
      form.reset();
    } catch (err) {
      errorEl.textContent = "送信に失敗しました。時間をおいて、もう一度お試しください。";
      console.error(err);
    } finally {
      button.disabled = false;
    }
  });
});

// --- チャットボット（あらかじめ用意した回答を返すタイプ） ---
const openButtons = document.querySelectorAll(".chat-open");
if (openButtons.length) {
  // チャット画面をページに追加
  const panel = document.createElement("div");
  panel.id = "chat-panel";
  panel.className = "chat-panel";
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-labelledby", "chat-title");
  panel.innerHTML = `
    <div class="chat-header">
      <div>
        <p class="chat-sub">チャットで質問する</p>
        <p id="chat-title" class="chat-title"></p>
      </div>
      <button type="button" class="chat-close" aria-label="チャットを閉じる">×</button>
    </div>
    <div class="chat-messages" aria-live="polite"></div>
    <div class="chat-quick"></div>
    <form class="chat-form">
      <input type="text" placeholder="質問を入力（例：料金は？）" autocomplete="off" aria-label="チャットへの質問">
      <button type="submit">送信</button>
    </form>`;
  document.body.appendChild(panel);

  const msgBox = panel.querySelector(".chat-messages");
  const quickBox = panel.querySelector(".chat-quick");
  const input = panel.querySelector(".chat-form input");
  const faq = [...(CHAT_FAQ[currentId] || []), ...CHAT_FAQ.common];
  panel.querySelector("#chat-title").textContent = genreLabel;

  const addMessage = (text, who) => {
    const div = document.createElement("div");
    div.className = `msg msg-${who}`;
    div.textContent = text;
    msgBox.appendChild(div);
    msgBox.scrollTop = msgBox.scrollHeight;
  };
  const answer = (text) => {
    const hit = faq.find((f) => f.keys.some((k) => text.includes(k)));
    return hit ? hit.a : "ご質問ありがとうございます。その内容は直接お話しした方が正確にお答えできます。お名前とメールアドレスをフォームからお送りいただければ、こちらからご連絡します。";
  };
  const ask = (text) => {
    addMessage(text, "user");
    setTimeout(() => addMessage(answer(text), "bot"), 300);
  };

  faq.forEach((f) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = f.q;
    b.addEventListener("click", () => ask(f.q));
    quickBox.appendChild(b);
  });

  const open = () => {
    if (!msgBox.children.length) {
      addMessage(`こんにちは！「${genreLabel}」についてのご質問にお答えします。下のボタンを押すか、質問を入力してください。`, "bot");
    }
    panel.hidden = false;
    input.focus();
  };
  openButtons.forEach((b) => b.addEventListener("click", open));
  panel.querySelector(".chat-close").addEventListener("click", () => { panel.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") panel.hidden = true; });
  panel.querySelector(".chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    ask(text);
  });
}
