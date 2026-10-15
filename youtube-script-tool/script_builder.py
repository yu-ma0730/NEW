"""台本の構成・テンプレート・AI用プロンプトを組み立てるロジック（AI不要部分）"""
from typing import List, Optional
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 選択肢マスタ
# ---------------------------------------------------------------------------

CHARACTERS = {
    "reimu": {"name": "霊夢", "label": "ゆっくり霊夢", "tone": "落ち着いたツッコミ役。「〜なのよ」「〜じゃない？」"},
    "marisa": {"name": "魔理沙", "label": "ゆっくり魔理沙", "tone": "物知りで元気。「〜だぜ」「〜なんだぜ」"},
    "zundamon": {"name": "ずんだもん", "label": "ずんだもん", "tone": "素直で好奇心旺盛。語尾は「〜のだ」「〜なのだ」"},
    "metan": {"name": "めたん", "label": "四国めたん", "tone": "お嬢様口調で面倒見が良い。「〜ですわ」「〜わよ」"},
    "narrator": {"name": "ナレーター", "label": "ナレーター", "tone": "落ち着いた丁寧語。です・ます調"},
    "teacher": {"name": "先生", "label": "先生", "tone": "やさしく丁寧に教える。です・ます調"},
    "student": {"name": "生徒", "label": "生徒", "tone": "視聴者目線で素朴な疑問をぶつける。フランク"},
    "doctor": {"name": "博士", "label": "博士", "tone": "博識でややクセがある。「〜じゃ」「〜なのじゃ」"},
    "assistant": {"name": "助手", "label": "助手", "tone": "元気なリアクション役。です・ます調"},
    "custom": {"name": "", "label": "オリジナル（自分で入力）", "tone": ""},
}

# structure: どの構成テンプレートを使うか
GENRES = {
    "trivia": {"label": "雑学・豆知識", "structure": "explain"},
    "history": {"label": "歴史・人物", "structure": "explain"},
    "business": {"label": "ビジネス・お金", "structure": "explain"},
    "science": {"label": "科学・宇宙", "structure": "explain"},
    "psychology": {"label": "心理学・人間関係", "structure": "explain"},
    "news": {"label": "ニュース・時事解説", "structure": "explain"},
    "game": {"label": "ゲーム・アニメ解説", "structure": "explain"},
    "health": {"label": "健康・ライフハック", "structure": "explain"},
    "ranking": {"label": "ランキング", "structure": "ranking"},
    "review": {"label": "商品・サービスレビュー", "structure": "review"},
    "sukatto": {"label": "2ch・スカッと系", "structure": "story"},
    "horror": {"label": "ホラー・都市伝説", "structure": "horror"},
    "other": {"label": "その他", "structure": "explain"},
}

# 1分あたりの目安文字数（読み上げソフト・ナレーションの一般的な速さ）
CHARS_PER_MINUTE = {"dialogue": 330, "solo": 300}

# (セクション名, 時間の割合, 役割の説明)  ※ "{points}" は本題を複数に展開する印
STRUCTURES = {
    "explain": [
        ("つかみ", 0.05, "最初の15秒で離脱を防ぐ。意外な事実・問いかけ・結論のチラ見せ"),
        ("導入", 0.10, "今日のテーマと、見ると何が得られるかを伝える"),
        ("{points}", 0.70, "本題。受け手の疑問→語り手の解説→具体例の流れ"),
        ("まとめ", 0.10, "要点を短く振り返る"),
        ("エンディング", 0.05, "締めのひと言と行動の呼びかけ"),
    ],
    "ranking": [
        ("つかみ", 0.05, "1位をにおわせて最後まで見る理由を作る"),
        ("導入", 0.07, "ランキングの基準を説明する"),
        ("{points}", 0.78, "下位から順に紹介。順位ごとに理由とエピソード"),
        ("まとめ", 0.05, "全順位を振り返る"),
        ("エンディング", 0.05, "コメントで視聴者の順位を聞くなど"),
    ],
    "review": [
        ("つかみ", 0.05, "結論（買いかどうか）を先にチラ見せ"),
        ("商品紹介", 0.15, "価格・スペック・どんな人向けか"),
        ("良い点", 0.30, "実際に使って良かった点を具体的に"),
        ("気になる点", 0.20, "正直なデメリット。信頼感につながる"),
        ("おすすめな人・そうでない人", 0.15, "視聴者が自分ごと化できるように"),
        ("まとめ", 0.10, "最終評価"),
        ("エンディング", 0.05, "概要欄リンクなどの案内"),
    ],
    "story": [
        ("冒頭（結末のチラ見せ）", 0.06, "スカッとする場面を先に見せて引き込む"),
        ("登場人物・状況紹介", 0.10, "主人公と相手の関係、置かれた状況"),
        ("事件発生", 0.16, "理不尽な出来事が起きる"),
        ("エスカレート", 0.22, "相手の行動がさらにひどくなる。視聴者のイライラを溜める"),
        ("反撃の準備", 0.16, "主人公が証拠集め・味方づくりをする"),
        ("反撃・スカッと", 0.20, "一気に形勢逆転"),
        ("後日談", 0.07, "その後どうなったか"),
        ("エンディング", 0.03, "締めのひと言"),
    ],
    "horror": [
        ("つかみ", 0.06, "最も怖い場面や一言を先に出す"),
        ("導入・背景", 0.14, "舞台・言い伝え・登場人物"),
        ("異変の始まり", 0.20, "小さな違和感を積み重ねる"),
        ("恐怖の展開", 0.30, "緊張感を一段ずつ上げる"),
        ("クライマックス", 0.15, "恐怖の頂点"),
        ("結末・考察", 0.10, "真相や考察、余韻"),
        ("エンディング", 0.05, "締めのひと言"),
    ],
}


# ---------------------------------------------------------------------------
# 入力モデル
# ---------------------------------------------------------------------------

class Speaker(BaseModel):
    preset: str = "custom"
    name: str = ""
    tone: str = ""


class ScriptRequest(BaseModel):
    mode: str = Field("original", pattern="^(client|original)$")
    theme: str = Field(..., min_length=1, max_length=200)
    genre: str = "trivia"
    genre_other: str = Field("", max_length=50)
    minutes: float = Field(10, ge=0.5, le=60)
    teller: Speaker  # 語り手
    listener: Optional[Speaker] = None  # 受け手（None なら1人語り）
    target_audience: str = Field("", max_length=200)
    points: List[str] = Field(default_factory=list, max_length=20)
    with_directions: bool = True  # テロップ・演出指示を入れるか

    # クラウドワークス等の依頼用
    client_name: str = Field("", max_length=100)
    char_count: Optional[int] = Field(None, ge=100, le=50000)  # 指定文字数
    client_rules: str = Field("", max_length=5000)
    ng_words: str = Field("", max_length=1000)
    ai_allowed: bool = False

    # オリジナル用
    channel_name: str = Field("", max_length=100)
    channel_concept: str = Field("", max_length=500)
    cta: str = Field("", max_length=200)


# ---------------------------------------------------------------------------
# 組み立て
# ---------------------------------------------------------------------------

def resolve_speaker(sp: Optional[Speaker]) -> Optional[dict]:
    if sp is None:
        return None
    preset = CHARACTERS.get(sp.preset, CHARACTERS["custom"])
    name = sp.name.strip() or preset["name"] or "話者"
    tone = sp.tone.strip() or preset["tone"]
    return {"name": name, "tone": tone}


def genre_label(req: ScriptRequest) -> str:
    if req.genre == "other" and req.genre_other.strip():
        return req.genre_other.strip()
    return GENRES.get(req.genre, GENRES["other"])["label"]


def target_chars(req: ScriptRequest) -> int:
    """目標文字数。依頼で文字数指定があればそれを優先する"""
    if req.mode == "client" and req.char_count:
        return req.char_count
    kind = "dialogue" if req.listener else "solo"
    return int(round(req.minutes * CHARS_PER_MINUTE[kind], -1))


def _point_titles(req: ScriptRequest, structure: str) -> List[str]:
    points = [p.strip() for p in req.points if p.strip()]
    if points:
        return points
    # ポイント未入力なら尺から数を決める（約2.5分に1つ、2〜7個）
    n = max(2, min(7, round(req.minutes / 2.5)))
    if structure == "ranking":
        return [f"第{i}位" for i in range(n, 0, -1)]
    return [f"ポイント{i}" for i in range(1, n + 1)]


def _fmt_time(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def build_outline(req: ScriptRequest) -> List[dict]:
    structure = GENRES.get(req.genre, GENRES["other"])["structure"]
    total_sec = req.minutes * 60
    total_chars = target_chars(req)

    sections = []
    for title, ratio, purpose in STRUCTURES[structure]:
        if title == "{points}":
            pts = _point_titles(req, structure)
            label = "本題" if structure == "explain" else "ランキング"
            for p in pts:
                sections.append((f"{label}：{p}", ratio / len(pts), purpose))
        else:
            sections.append((title, ratio, purpose))

    outline, elapsed = [], 0.0
    for title, ratio, purpose in sections:
        sec = total_sec * ratio
        outline.append({
            "title": title,
            "start": _fmt_time(elapsed),
            "end": _fmt_time(elapsed + sec),
            "chars": int(round(total_chars * ratio, -1)) or 10,
            "purpose": purpose,
        })
        elapsed += sec
    return outline


def build_template(req: ScriptRequest, outline: List[dict]) -> str:
    """AIを使わずに、自分で書き込むための台本の骨組み"""
    teller = resolve_speaker(req.teller)
    listener = resolve_speaker(req.listener)
    lines = [f"■タイトル案：{req.theme}", f"■ジャンル：{genre_label(req)}",
             f"■尺：約{req.minutes:g}分 / 目標 約{target_chars(req)}文字", ""]

    for sec in outline:
        lines.append(f"【{sec['title']}】（{sec['start']}〜{sec['end']} / 約{sec['chars']}文字）")
        lines.append(f"※{sec['purpose']}")
        if req.with_directions:
            lines.append("【テロップ：】【画像：】")
        if listener:
            lines.append(f"{listener['name']}：（受け手の問いかけ・リアクション）")
            lines.append(f"{teller['name']}：（語り手の説明）")
            lines.append(f"{listener['name']}：（あいづち・疑問）")
            lines.append(f"{teller['name']}：（具体例・答え）")
        else:
            lines.append(f"{teller['name']}：")
            lines.append(f"{teller['name']}：")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_prompt(req: ScriptRequest, outline: List[dict]) -> str:
    """AIに台本の下書きを書かせるための指示文"""
    teller = resolve_speaker(req.teller)
    listener = resolve_speaker(req.listener)
    total = target_chars(req)

    p = ["あなたはYouTube動画の台本作家です。以下の条件で、動画の台本を書いてください。", ""]
    p.append("# 基本情報")
    p.append(f"- テーマ：{req.theme}")
    p.append(f"- ジャンル：{genre_label(req)}")
    p.append(f"- 尺：約{req.minutes:g}分（本文の目標は約{total}文字。±10%以内）")
    if req.target_audience.strip():
        p.append(f"- 想定視聴者：{req.target_audience.strip()}")
    if req.mode == "original":
        if req.channel_name.strip():
            p.append(f"- チャンネル名：{req.channel_name.strip()}")
        if req.channel_concept.strip():
            p.append(f"- チャンネルのコンセプト：{req.channel_concept.strip()}")
    p.append("")

    p.append("# 登場人物")
    if listener:
        p.append(f"- 語り手：{teller['name']}（{teller['tone']}）。解説・ストーリーを進める役")
        p.append(f"- 受け手：{listener['name']}（{listener['tone']}）。視聴者の代わりに疑問・驚き・ツッコミを入れる役")
        p.append("- 語り手が一方的に長く話し続けないよう、2〜4行ごとに受け手のセリフを挟むこと")
    else:
        p.append(f"- 語り手（1人語り）：{teller['name']}（{teller['tone']}）")
    p.append("")

    p.append("# 構成（この順番・文字数配分で書くこと）")
    for s in outline:
        p.append(f"- 【{s['title']}】約{s['chars']}文字：{s['purpose']}")
    pts = [x.strip() for x in req.points if x.strip()]
    if pts:
        p.append("")
        p.append("# 必ず入れる内容")
        p.extend(f"- {x}" for x in pts)
    p.append("")

    p.append("# 書き方のルール")
    p.append("- 耳で聞いてわかる話し言葉にする。1文は40文字以内を目安に短く")
    p.append("- 「前述の通り」「以下の」など、読み物向けの表現は使わない")
    p.append("- 最初の15秒で、視聴者が続きを見たくなる問いかけや意外な事実を出す")
    p.append("- 事実やデータを書く場合は、確認が必要な箇所の末尾に【要確認】と付ける")
    if req.with_directions:
        p.append("- 演出指示は独立した行に【テロップ：〜】【画像：〜】【効果音：〜】の形で入れる")
    if req.mode == "original" and req.cta.strip():
        p.append(f"- エンディングでは次の行動を呼びかける：{req.cta.strip()}")

    if req.mode == "client":
        if req.client_rules.strip():
            p.append("")
            p.append("# クライアントからの指定（最優先で守ること）")
            p.append(req.client_rules.strip())
        if req.ng_words.strip():
            p.append("")
            p.append(f"# NGワード（絶対に使わない）\n{req.ng_words.strip()}")
    p.append("")

    p.append("# 出力形式")
    p.append("- 各セクションの最初に【セクション名】の見出し行を入れる")
    p.append("- セリフは「話者名：セリフ」の形で1行ずつ書く")
    p.append("- 台本本文以外の前置きや説明は書かない")
    return "\n".join(p)


def options_payload() -> dict:
    return {
        "characters": [{"id": k, "label": v["label"], "name": v["name"], "tone": v["tone"]}
                       for k, v in CHARACTERS.items()],
        "genres": [{"id": k, "label": v["label"]} for k, v in GENRES.items()],
        "chars_per_minute": CHARS_PER_MINUTE,
    }
