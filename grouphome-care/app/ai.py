"""記録の「原案」をつくる機能（AI支援）。

大切な決まり：
  * 職員が入力した内容（選んだ項目・メモ・音声の文字）だけで文章をつくる。
  * 入力されていない事実は絶対に書き足さない（推測しない）。
  * 足りない項目や、気をつけるべき言葉は「確認事項」として職員に知らせる。
  * 外部のAIサービスへデータを送らない（この標準実装はサーバー内だけで動く）。

将来、生成AI（社内設置の大規模言語モデル等）に切り替える場合も、
draft() の入出力の形を変えずに中身だけ差し替えられるようにしています。
"""
import re

# 記録の種類と入力項目。画面（app.js）もこの定義を使うので、ここを直せば画面も変わる。
FORM_DEFS = {
    "vital": {"label": "バイタル", "icon": "🌡️", "required": ["temp"], "fields": [
        {"key": "temp", "label": "体温（℃）", "kind": "number", "step": "0.1"},
        {"key": "bp_high", "label": "血圧 上（mmHg）", "kind": "number"},
        {"key": "bp_low", "label": "血圧 下（mmHg）", "kind": "number"},
        {"key": "pulse", "label": "脈拍（回/分）", "kind": "number"},
        {"key": "spo2", "label": "SpO2（%）", "kind": "number"},
        {"key": "condition", "label": "様子", "kind": "choice", "options": ["いつもどおり", "元気がない", "ぐあいが悪そう"]},
    ], "phrases": ["測定を嫌がられたため、時間をおいて測定した", "看護師へ報告した"]},
    "meal": {"label": "食事", "icon": "🍚", "required": ["breakfast", "lunch", "dinner"], "fields": [
        {"key": "breakfast", "label": "朝ごはん", "kind": "choice", "options": ["全部", "8割", "半分", "少し", "食べない", "不在"]},
        {"key": "lunch", "label": "昼ごはん", "kind": "choice", "options": ["全部", "8割", "半分", "少し", "食べない", "不在"]},
        {"key": "dinner", "label": "夜ごはん", "kind": "choice", "options": ["全部", "8割", "半分", "少し", "食べない", "不在"]},
        {"key": "water", "label": "水分", "kind": "choice", "options": ["よく飲んだ", "ふつう", "少ない"]},
    ], "phrases": ["おかわりをされた", "嫌いな物を残された", "むせ込みがあった"]},
    "med": {"label": "服薬", "icon": "💊", "required": ["timing", "result"], "fields": [
        {"key": "timing", "label": "いつの薬", "kind": "multi", "options": ["朝", "昼", "夕", "寝る前", "頓服"]},
        {"key": "result", "label": "飲めた？", "kind": "choice", "options": ["飲んだ", "一部飲んだ", "飲まなかった"]},
    ], "phrases": ["声かけで服薬された", "服薬を拒否された", "看護師へ報告した"]},
    "excretion": {"label": "排泄", "icon": "🚻", "required": ["urine", "stool"], "fields": [
        {"key": "urine", "label": "おしっこ", "kind": "choice", "options": ["あり", "なし", "失禁あり"]},
        {"key": "stool", "label": "便", "kind": "choice", "options": ["ふつう", "やわらかい", "かたい", "なし"]},
    ], "phrases": ["トイレ誘導を行った", "パッド交換を行った"]},
    "case": {"label": "ケース記録", "icon": "📝", "required": ["mood"], "fields": [
        {"key": "mood", "label": "様子", "kind": "choice", "options": ["おだやか", "元気", "不安そう", "イライラ", "ねむそう"]},
        {"key": "activity", "label": "したこと", "kind": "multi", "options": ["日中活動", "通院", "外出", "入浴", "買い物", "家族の面会", "余暇"]},
    ], "phrases": ["笑顔で会話された", "落ち着いて過ごされていた", "日中活動へ出発された", "22時に就寝された"]},
    "handover": {"label": "申し送り", "icon": "📣", "required": [], "fields": [
        {"key": "priority", "label": "大事さ", "kind": "choice", "options": ["ふつう", "大事"]},
    ], "phrases": ["次の勤務者は様子を見てください", "家族へ連絡済み", "通院の予定あり"]},
    "diary": {"label": "業務日誌", "icon": "📒", "required": [], "resident_optional": True, "fields": [
        {"key": "weather", "label": "天気", "kind": "choice", "options": ["晴れ", "くもり", "雨", "雪"]},
        {"key": "events", "label": "できごと", "kind": "multi", "options": ["来客", "業者点検", "避難訓練", "会議", "研修"]},
    ], "phrases": ["特に変わりなし", "全員の帰宅を確認した"]},
}

DAILY_REQUIRED_TYPES = ["vital", "med", "case"]  # 在宅日に毎日必要な記録（設定で変更可）

# 気をつける言葉 → 確認事項
WATCH_WORDS = [
    (r"転倒|転ん|こけ|ころん|尻もち|しりもち", "転倒の言葉があります。事故・ヒヤリハット報告が必要か確認してください。", True),
    (r"ぶつけ|けが|怪我|出血|あざ|打撲|擦り傷|すり傷", "けが・出血の言葉があります。部位と処置、報告先を記録してください。", True),
    (r"誤薬|飲み忘れ|薬を落と|渡し間違", "服薬のトラブルの言葉があります。事故・ヒヤリハット報告が必要か確認してください。", True),
    (r"発熱|熱が|咳|せき|嘔吐|吐い|下痢", "体調不良の言葉があります。バイタル記録と感染症対策を確認してください。", False),
    (r"無断|いなくな|行方", "所在不明の言葉があります。管理者へすぐ報告してください。", True),
    (r"暴言|暴力|叩|たたい|けんか", "他害・トラブルの言葉があります。経過と対応を具体的に記録してください。", False),
    (r"拒否|嫌が", "拒否の言葉があります。どう対応したかを書いてください。", False),
]

FILLERS = re.compile(r"(えーっと|えっと|えー|あのー|あの、|あのう|まあ|なんか)、?")


def clean_memo(memo):
    """音声入力のメモから「えーと」等を取り、文の終わりに「。」を付ける。内容は変えない。"""
    if not memo:
        return ""
    text = FILLERS.sub("", memo).strip()
    text = re.sub(r"[ 　]+", " ", text)
    parts = [p.strip(" 、") for p in re.split(r"[。\n]+", text) if p.strip(" 、")]
    return "".join(p + "。" for p in parts)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def draft(rtype, fields, memo="", phrases=None):
    """入力から原案テキストと確認事項を返す。"""
    if rtype not in FORM_DEFS:
        raise ValueError("unknown record type")
    fields = fields or {}
    phrases = phrases or []
    d = FORM_DEFS[rtype]
    s = []
    checks = []
    filled = lambda k: fields.get(k) not in (None, "", [])

    if rtype == "vital":
        parts = []
        if filled("temp"):
            parts.append(f"体温{fields['temp']}℃")
        if filled("bp_high") and filled("bp_low"):
            parts.append(f"血圧{fields['bp_high']}/{fields['bp_low']}mmHg")
        elif filled("bp_high") or filled("bp_low"):
            checks.append("血圧の上と下の片方だけが入力されています。")
        if filled("pulse"):
            parts.append(f"脈拍{fields['pulse']}回/分")
        if filled("spo2"):
            parts.append(f"SpO2 {fields['spo2']}%")
        if parts:
            s.append("、".join(parts) + "。")
        if filled("condition"):
            s.append(f"様子は「{fields['condition']}」。")
        t, bh, sp, pl = (_num(fields.get(k)) for k in ("temp", "bp_high", "spo2", "pulse"))
        if t is not None and t >= 37.5:
            checks.append(f"体温が{fields['temp']}℃です（37.5℃以上）。看護師・管理者へ報告したか確認してください。")
        if t is not None and (t < 34 or t > 42):
            checks.append("体温の数字が正しいか確認してください。")
        if bh is not None and bh >= 160:
            checks.append(f"血圧（上）が{fields['bp_high']}です。報告が必要か確認してください。")
        if sp is not None and sp < 93:
            checks.append(f"SpO2が{fields['spo2']}%です。報告が必要か確認してください。")
        if pl is not None and (pl < 50 or pl > 110):
            checks.append(f"脈拍が{fields['pulse']}です。報告が必要か確認してください。")
    elif rtype == "meal":
        names = {"breakfast": "朝食", "lunch": "昼食", "dinner": "夕食"}
        parts = [f"{names[k]}は{fields[k]}" for k in names if filled(k)]
        if parts:
            s.append("、".join(parts) + "。")
        if filled("water"):
            s.append(f"水分は「{fields['water']}」。")
        if any(fields.get(k) == "食べない" for k in names):
            checks.append("食べなかった食事があります。理由や体調を書いてください。")
    elif rtype == "med":
        if filled("timing") and filled("result"):
            s.append(f"{'・'.join(fields['timing'])}の薬：{fields['result']}。")
        if fields.get("result") in ("飲まなかった", "一部飲んだ"):
            checks.append("薬を全部飲めていません。理由と、看護師・管理者への報告を書いてください。")
    elif rtype == "excretion":
        if filled("urine"):
            s.append(f"排尿：{fields['urine']}。")
        if filled("stool"):
            s.append(f"排便：{fields['stool']}。")
    elif rtype == "case":
        if filled("mood"):
            s.append(f"様子は「{fields['mood']}」。")
        if filled("activity"):
            s.append(f"{'、'.join(fields['activity'])}あり。")
    elif rtype == "handover":
        if fields.get("priority") == "大事":
            s.append("【大事】")
    elif rtype == "diary":
        if filled("weather"):
            s.append(f"天気：{fields['weather']}。")
        if filled("events"):
            s.append(f"{'、'.join(fields['events'])}あり。")

    for p in phrases:
        s.append(p.rstrip("。") + "。")
    cleaned = clean_memo(memo)
    if cleaned:
        s.append(cleaned)

    labels = {f["key"]: f["label"] for f in d["fields"]}
    missing = [labels[k] for k in d["required"] if not filled(k)]
    if missing:
        checks.insert(0, "まだ入力されていない項目：" + "、".join(missing))
    if rtype in ("handover", "diary") and not cleaned and not phrases:
        checks.insert(0, "内容（メモ）が入力されていません。")

    suggest_incident = False
    source = " ".join([memo or ""] + phrases)
    for pattern, message, incident in WATCH_WORDS:
        if re.search(pattern, source):
            checks.append(message)
            suggest_incident = suggest_incident or incident

    return {
        "text": "".join(s),
        "checks": checks,
        "suggest_incident": suggest_incident,
        "note": "入力された内容だけで文章をつくりました。事実と違うところは直してから保存してください。",
    }


def summarize_handovers(rows):
    """申し送りを利用者ごとにまとめる（並べ替えのみ。文章は書き換えない）。"""
    groups = {}
    for r in rows:
        key = r["resident_name"] or "事業所全体"
        g = groups.setdefault(key, {"resident": key, "important": False, "items": []})
        important = '"大事"' in (r["data_json"] or "")
        g["important"] = g["important"] or important
        g["items"].append({"id": r["id"], "date": r["date"], "time": r["time"], "type": r["type"],
                           "text": r["text"], "by": r["created_by_name"], "important": important})
    return sorted(groups.values(), key=lambda g: (not g["important"], g["resident"]))
