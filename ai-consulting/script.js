/* =========================================================
   設定（公開する前にここを確認してください）
   ========================================================= */
const CONFIG = {
  // フォームの送信先URL（例：Formspree などのフォームサービスのURL）
  // 空のままだと「デモモード」になり、実際には送信されません。
  FORM_ENDPOINT: "",
};

/* =========================================================
   ご相談ジャンルの一覧
   ・ジャンルを増やしたいときは { ... } のかたまりをコピーして追加
   ・並び順を変えたいときは、かたまりごと入れ替え
   ・id は英数字で、他と重ならない名前にしてください
   ========================================================= */
const GENRES = [
  {
    id: "web-design",
    icon: "🎨",
    title: "AI × Webデザイン",
    summary: "AIを使って、早く・低コストでWebサイトやLPを形にします。",
    points: [
      "画像生成AIでのビジュアル・バナー制作",
      "AIを使ったサイト構成案・文章のたたき台づくり",
      "既存サイトの改善ポイントの洗い出し",
    ],
    faq: [
      { q: "どんなサイトが作れますか？", keys: ["サイト", "作れ", "どんな"], a: "会社紹介サイト、サービス紹介のLP（1ページの宣伝ページ）、ポートフォリオなどを想定しています。内容によって進め方を一緒に決めます。" },
      { q: "デザインの知識がなくても大丈夫？", keys: ["知識", "初心者", "分からない", "わからない"], a: "大丈夫です。「こんな雰囲気にしたい」というイメージや、参考にしたいサイトを教えていただければ、そこから形にしていきます。" },
    ],
  },
  {
    id: "data",
    icon: "📊",
    title: "AI × データ",
    summary: "手元のデータを、AIで「見える化」して判断に使える形にします。",
    points: [
      "Excel・スプレッドシートの集計の自動化",
      "売上やアクセスデータのグラフ化・ダッシュボード作成",
      "AIによるデータの傾向分析のサポート",
    ],
    faq: [
      { q: "どんなデータでも扱えますか？", keys: ["データ", "扱え", "どんな"], a: "Excel、CSV、スプレッドシートなどが中心です。まずはどんなデータがあるか教えてください。個人情報を含む場合は、取り扱い方法を事前にご相談します。" },
      { q: "データが整理されていなくても大丈夫？", keys: ["整理", "バラバラ", "汚い"], a: "はい。データの整理から一緒に進めることもできます。" },
    ],
  },
  {
    id: "automation",
    icon: "⚙️",
    title: "AI × 業務効率化",
    summary: "毎日のくり返し作業を、AIやツールで自動化・時短します。",
    points: [
      "メール返信・議事録・日報のAI活用",
      "定型作業の自動化（転記・集計・通知など）",
      "どの業務をAI化すべきかの整理",
    ],
    faq: [
      { q: "どんな作業が自動化できますか？", keys: ["自動化", "作業", "どんな"], a: "決まった手順のくり返し作業（データの転記、定型メール、集計など）が向いています。まずは今の業務の流れをお聞かせください。" },
      { q: "社内にITに詳しい人がいません", keys: ["詳しい", "IT", "社内", "いない"], a: "その前提で、使い方の説明や手順書づくりまでサポートします。" },
    ],
  },
  {
    id: "marketing",
    icon: "📣",
    title: "AI × マーケティング・SNS",
    summary: "SNS投稿や広告文づくりにAIを取り入れ、発信を続けやすくします。",
    points: [
      "SNS投稿の企画・文章のたたき台づくり",
      "広告文・キャッチコピーの案出し",
      "投稿作業のルール化・時短",
    ],
    faq: [
      { q: "どのSNSに対応していますか？", keys: ["SNS", "インスタ", "X", "対応"], a: "Instagram、X（旧Twitter）、ブログなど、お使いの媒体に合わせてご提案します。" },
    ],
  },
  {
    id: "writing",
    icon: "📝",
    title: "AI × 文章・資料作成",
    summary: "企画書、提案資料、マニュアルなどをAIで効率よく作ります。",
    points: [
      "提案書・企画書の構成づくり",
      "社内マニュアル・手順書の作成",
      "文章の校正・言い換え",
    ],
    faq: [
      { q: "AIが作った文章をそのまま使えますか？", keys: ["そのまま", "使え", "AIが"], a: "AIの文章には誤りが含まれることがあるため、人の目で事実確認・調整をする前提で進めます。そのチェック方法もお伝えします。" },
    ],
  },
  {
    id: "training",
    icon: "🎓",
    title: "AI × 社内研修・活用サポート",
    summary: "AIツールの使い方を、チームで使えるレベルまでサポートします。",
    points: [
      "ChatGPT・Claudeなど生成AIの基本の使い方",
      "業務に合わせたプロンプト（AIへの指示文）づくり",
      "社内でのAI利用ルールの整理",
    ],
    faq: [
      { q: "何人から対応できますか？", keys: ["何人", "人数", "1人", "一人"], a: "お一人からチーム単位まで、人数に合わせて内容を調整します。" },
    ],
  },
];

/* =========================================================
   全ジャンル共通のチャット回答
   ========================================================= */
const COMMON_FAQ = [
  { q: "料金はいくらですか？", keys: ["料金", "費用", "値段", "いくら", "価格"], a: "ご相談内容によって変わるため、お話をうかがってからお見積もりします。まずはこのページのフォームからお名前とメールアドレスをお送りください。" },
  { q: "相談の流れは？", keys: ["流れ", "進め", "手順", "どうやって"], a: "① フォームからご連絡 → ② メールで日程調整 → ③ オンラインでヒアリング → ④ ご提案・お見積もり、という流れです。" },
  { q: "オンラインで相談できますか？", keys: ["オンライン", "zoom", "Zoom", "リモート", "対面"], a: "はい、オンラインでのご相談を基本としています。" },
];

/* =========================================================
   ここから下はページを動かすためのプログラムです
   （ふだんは編集しなくて大丈夫です）
   ========================================================= */

document.getElementById("year").textContent = new Date().getFullYear();

// --- ヘッダーのジャンルメニューを作る ---
const navList = document.getElementById("genre-nav-list");
GENRES.forEach((g) => {
  const li = document.createElement("li");
  const a = document.createElement("a");
  a.href = `#genre-${g.id}`;
  a.textContent = g.title;
  li.appendChild(a);
  navList.appendChild(li);
});

// --- ジャンルカードを作る ---
const list = document.getElementById("genre-list");
GENRES.forEach((g) => {
  const card = document.createElement("article");
  card.className = "genre-card";
  card.id = `genre-${g.id}`;
  card.innerHTML = `
    <div class="genre-info">
      <div class="genre-icon" aria-hidden="true"></div>
      <h3></h3>
      <p class="genre-summary"></p>
      <ul class="genre-points"></ul>
    </div>
    <form class="genre-form" novalidate>
      <p class="form-title">一度お話をうかがいたいです</p>
      <label><span>お名前<span class="req">必須</span></span>
        <input type="text" name="name" autocomplete="name" placeholder="山田 太郎" required>
      </label>
      <label><span>メールアドレス<span class="req">必須</span></span>
        <input type="email" name="email" autocomplete="email" placeholder="example@mail.com" required>
      </label>
      <input type="hidden" name="genre">
      <p class="form-error" role="alert"></p>
      <button type="submit" class="btn btn-primary">相談を申し込む</button>
      <button type="button" class="btn btn-ghost chat-open">💬 チャットで質問する</button>
      <p class="form-done" role="status"></p>
    </form>
  `;
  // 文字は textContent で入れる（安全のため）
  card.querySelector(".genre-icon").textContent = g.icon;
  card.querySelector("h3").textContent = g.title;
  card.querySelector(".genre-summary").textContent = g.summary;
  const ul = card.querySelector(".genre-points");
  g.points.forEach((p) => {
    const li = document.createElement("li");
    li.textContent = p;
    ul.appendChild(li);
  });
  card.querySelector('input[name="genre"]').value = g.title;
  card.querySelector(".chat-open").addEventListener("click", () => openChat(g));
  card.querySelector(".genre-form").addEventListener("submit", (e) => handleSubmit(e, g));
  list.appendChild(card);
});

// --- フォーム送信 ---
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

async function handleSubmit(e, genre) {
  e.preventDefault();
  const form = e.currentTarget;
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

  const button = form.querySelector('button[type="submit"]');

  // 送信先が未設定のときはデモモード（実際には送らない）
  if (!CONFIG.FORM_ENDPOINT) {
    doneEl.textContent = `【デモ表示】${name} 様、「${genre.title}」のご相談を受け付けました。※送信先が未設定のため、実際には送信されていません。`;
    form.reset();
    return;
  }

  button.disabled = true;
  try {
    const res = await fetch(CONFIG.FORM_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ name, email, genre: genre.title }),
    });
    if (!res.ok) throw new Error(`status ${res.status}`);
    doneEl.textContent = `${name} 様、ありがとうございます。「${genre.title}」のご相談を受け付けました。追ってメールでご連絡します。`;
    form.reset();
  } catch (err) {
    errorEl.textContent = "送信に失敗しました。時間をおいて、もう一度お試しください。";
    console.error(err);
  } finally {
    button.disabled = false;
  }
}

// --- チャットボット（あらかじめ用意した回答を返すタイプ） ---
const panel = document.getElementById("chat-panel");
const msgBox = document.getElementById("chat-messages");
const quickBox = document.getElementById("chat-quick");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
let currentGenre = null;

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = `msg msg-${who}`;
  div.textContent = text;
  msgBox.appendChild(div);
  msgBox.scrollTop = msgBox.scrollHeight;
}

function faqFor(genre) {
  return [...genre.faq, ...COMMON_FAQ];
}

function openChat(genre) {
  currentGenre = genre;
  document.getElementById("chat-title").textContent = genre.title;
  msgBox.innerHTML = "";
  quickBox.innerHTML = "";
  addMessage(`こんにちは！「${genre.title}」についてのご質問にお答えします。下のボタンを押すか、質問を入力してください。`, "bot");
  faqFor(genre).forEach((f) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = f.q;
    b.addEventListener("click", () => ask(f.q));
    quickBox.appendChild(b);
  });
  panel.hidden = false;
  chatInput.focus();
}

function answer(text) {
  const hit = faqFor(currentGenre).find((f) => f.keys.some((k) => text.includes(k)));
  if (hit) return hit.a;
  return "ご質問ありがとうございます。その内容は直接お話しした方が正確にお答えできます。お名前とメールアドレスをフォームからお送りいただければ、こちらからご連絡します。";
}

function ask(text) {
  addMessage(text, "user");
  setTimeout(() => addMessage(answer(text), "bot"), 300);
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text || !currentGenre) return;
  chatInput.value = "";
  ask(text);
});

document.getElementById("chat-close").addEventListener("click", () => { panel.hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") panel.hidden = true; });
