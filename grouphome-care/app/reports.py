"""事故・ヒヤリハット分析と、各種書類の原案づくり。

原案は、データベースに入っている内容と、職員が入力した内容だけで組み立てます。
空いている欄は空欄のまま残し「記入もれ」として知らせます（勝手に埋めません）。
"""
import re
from collections import Counter


def _tokens(text):
    """似ている事例を探すための簡単な単語分け（漢字・カタカナのかたまり＋2文字ずつ）。"""
    text = text or ""
    words = set(re.findall(r"[一-龥ァ-ヴー]{2,}", text))
    plain = re.sub(r"\s", "", text)
    words |= {plain[i:i + 2] for i in range(len(plain) - 1)}
    return words


def similar_incidents(conn, facility_id, query, category=None, exclude_id=None, limit=5):
    q = _tokens(query)
    out = []
    for r in conn.execute("SELECT i.*, res.name resident_name FROM incidents i LEFT JOIN residents res ON res.id=i.resident_id "
                          "WHERE i.facility_id=?", (facility_id,)):
        if exclude_id and r["id"] == exclude_id:
            continue
        t = _tokens(" ".join(filter(None, [r["category"], r["place"], r["description"], r["cause"]])))
        score = len(q & t) / (len(q) or 1)
        if category and r["category"] == category:
            score += 0.5
        if score > 0.1:
            item = dict(r)
            item["score"] = round(score, 2)
            out.append(item)
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def incident_stats(conn, facility_id, start, end):
    rows = [dict(r) for r in conn.execute(
        "SELECT i.*, res.name resident_name FROM incidents i LEFT JOIN residents res ON res.id=i.resident_id "
        "WHERE i.facility_id=? AND i.date BETWEEN ? AND ? ORDER BY i.date", (facility_id, start, end))]

    def band(t):
        if not t:
            return "不明"
        h = int(t.split(":")[0])
        return "朝(6-10時)" if 6 <= h < 10 else "日中(10-17時)" if 10 <= h < 17 else "夕方(17-22時)" if 17 <= h < 22 else "夜間(22-6時)"

    return {
        "total": len(rows),
        "by_kind": Counter(r["kind"] for r in rows),
        "by_category": Counter(r["category"] for r in rows).most_common(),
        "by_place": Counter(r["place"] or "不明" for r in rows).most_common(),
        "by_time": Counter(band(r["time"]) for r in rows).most_common(),
        "by_resident": Counter(r["resident_name"] or "なし" for r in rows).most_common(),
        "rows": rows,
    }


def _doc(title, sections):
    missing = [s["heading"] for s in sections if s.get("required") and not (s.get("body") or "").strip()]
    return {"title": title, "sections": sections, "missing": missing}


def build(conn, facility, kind, params):
    fid = facility["id"]
    p = params or {}
    if kind == "incident_report":
        r = conn.execute("SELECT i.*, res.name resident_name, u.name author FROM incidents i "
                         "LEFT JOIN residents res ON res.id=i.resident_id LEFT JOIN users u ON u.id=i.created_by "
                         "WHERE i.id=? AND i.facility_id=?", (p.get("incident_id"), fid)).fetchone()
        if not r:
            raise ValueError("事故・ヒヤリハットが見つかりません")
        sim = similar_incidents(conn, fid, r["description"] or "", r["category"], exclude_id=r["id"], limit=3)
        past = "\n".join(f"・{s['date']} {s['category']}：{s['prevention'] or '（再発防止策の記入なし）'}" for s in sim)
        return _doc(f"{r['kind']}報告書（{r['date']}）", [
            {"heading": "事業所名", "body": facility["name"], "required": True},
            {"heading": "発生日時", "body": f"{r['date']} {r['time'] or ''}".strip(), "required": True},
            {"heading": "利用者", "body": r["resident_name"] or "", "required": True},
            {"heading": "種類・分類", "body": f"{r['kind']}／{r['category']}", "required": True},
            {"heading": "発生場所", "body": r["place"] or "", "required": True},
            {"heading": "発生状況", "body": r["description"] or "", "required": True},
            {"heading": "原因", "body": r["cause"] or "", "required": True},
            {"heading": "対応・処置", "body": r["action_taken"] or "", "required": True},
            {"heading": "再発防止策", "body": r["prevention"] or "", "required": True},
            {"heading": "家族・関係機関への連絡", "body": "", "required": r["kind"] == "事故"},
            {"heading": "参考：似ている過去の事例と対策", "body": past or "なし", "required": False},
            {"heading": "報告者", "body": r["author"] or "", "required": True},
        ])
    if kind == "incident_meeting":
        st = incident_stats(conn, fid, p.get("start"), p.get("end"))
        fmt = lambda pairs: "\n".join(f"・{k}：{v}件" for k, v in pairs) or "なし"
        lines = "\n".join(f"・{r['date']} {r['kind']}／{r['category']}／{r['place'] or ''}：{r['description'] or ''}"
                          f"\n　→ 対策：{r['prevention'] or '（未記入）'}" for r in st["rows"])
        no_prev = [r for r in st["rows"] if not r["prevention"]]
        return _doc(f"事故・ヒヤリハット 改善会議資料（{p.get('start')}〜{p.get('end')}）", [
            {"heading": "件数", "body": f"合計{st['total']}件（事故{st['by_kind'].get('事故', 0)}件、ヒヤリハット{st['by_kind'].get('ヒヤリハット', 0)}件）"},
            {"heading": "分類別", "body": fmt(st["by_category"])},
            {"heading": "場所別", "body": fmt(st["by_place"])},
            {"heading": "時間帯別", "body": fmt(st["by_time"])},
            {"heading": "利用者別", "body": fmt(st["by_resident"])},
            {"heading": "一覧と再発防止策", "body": lines or "なし"},
            {"heading": "再発防止策が未記入のもの", "body": "\n".join(f"・{r['date']} {r['category']}" for r in no_prev) or "なし"},
            {"heading": "会議で決めたこと（記入してください）", "body": "", "required": True},
        ])
    if kind == "minutes":
        return _doc(f"会議議事録（{p.get('date', '')}）", [
            {"heading": "日時", "body": p.get("date", ""), "required": True},
            {"heading": "場所", "body": p.get("place", ""), "required": True},
            {"heading": "出席者", "body": p.get("attendees", ""), "required": True},
            {"heading": "議題", "body": p.get("agenda", ""), "required": True},
            {"heading": "内容（メモ・音声の文字）", "body": p.get("memo", ""), "required": True},
            {"heading": "決定事項", "body": p.get("decisions", ""), "required": True},
            {"heading": "次回までの宿題（担当・期限）", "body": p.get("todo", ""), "required": False},
        ])
    if kind == "training":
        return _doc(f"研修記録（{p.get('date', '')}）", [
            {"heading": "研修名", "body": p.get("title", ""), "required": True},
            {"heading": "日時", "body": p.get("date", ""), "required": True},
            {"heading": "講師", "body": p.get("lecturer", ""), "required": True},
            {"heading": "参加者", "body": p.get("attendees", ""), "required": True},
            {"heading": "内容", "body": p.get("memo", ""), "required": True},
            {"heading": "参加者の感想・理解度", "body": p.get("feedback", ""), "required": False},
        ])
    if kind == "monitoring":
        rid = p.get("resident_id")
        res = conn.execute("SELECT * FROM residents WHERE id=? AND facility_id=?", (rid, fid)).fetchone()
        if not res:
            raise ValueError("利用者が見つかりません")
        plan = conn.execute("SELECT * FROM plans WHERE resident_id=? ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
        recs = conn.execute("SELECT date,type,text FROM records WHERE resident_id=? AND date BETWEEN ? AND ? "
                            "AND type IN ('case','handover') ORDER BY date", (rid, p.get("start"), p.get("end"))).fetchall()
        inc = conn.execute("SELECT date,kind,category FROM incidents WHERE resident_id=? AND date BETWEEN ? AND ?",
                           (rid, p.get("start"), p.get("end"))).fetchall()
        return _doc(f"モニタリング記録 原案（{res['name']}さん）", [
            {"heading": "対象期間", "body": f"{p.get('start')}〜{p.get('end')}", "required": True},
            {"heading": "個別支援計画の目標", "body": plan["goal"] if plan else "", "required": True},
            {"heading": "期間中の記録（抜き出し）", "body": "\n".join(f"・{r['date']} {r['text']}" for r in recs) or "なし"},
            {"heading": "期間中の事故・ヒヤリハット", "body": "\n".join(f"・{r['date']} {r['kind']}／{r['category']}" for r in inc) or "なし"},
            {"heading": "目標の達成状況（サービス管理責任者が記入）", "body": "", "required": True},
            {"heading": "本人・家族の意向（聞き取って記入）", "body": "", "required": True},
            {"heading": "今後の方針", "body": "", "required": True},
        ])
    raise ValueError("unknown document kind")


DOC_KINDS = {
    "incident_report": "事故・ヒヤリハット報告書",
    "incident_meeting": "改善会議・研修用 事故分析資料",
    "minutes": "会議議事録",
    "training": "研修記録",
    "monitoring": "モニタリング記録",
}
