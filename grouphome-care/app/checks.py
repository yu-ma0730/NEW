"""請求前・勤怠・実績チェック。

データベースの内容を照らし合わせて、問題を一覧にして返すだけです（データは変更しません）。
直したあとにもう一度呼べば「再チェック」になります。
"""
import datetime

from .ai import DAILY_REQUIRED_TYPES, FORM_DEFS

TOLERANCE_MIN = 15  # シフトと打刻の差がこれ以上なら知らせる（分）


def _dates(start, end):
    d = start
    while d <= end:
        yield d.isoformat()
        d += datetime.timedelta(days=1)


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def run_checks(conn, facility_id, start, end, today=None):
    today = today or datetime.date.today()
    end = min(end, today)
    issues = []

    def add(level, category, message, date=None, resident_id=None, link=None):
        issues.append({"level": level, "category": category, "message": message,
                       "date": date, "resident_id": resident_id, "link": link})

    residents = conn.execute("SELECT id,name FROM residents WHERE facility_id=? AND active=1",
                             (facility_id,)).fetchall()
    occ = {(r["resident_id"], r["date"]): r["status"] for r in conn.execute(
        "SELECT resident_id,date,status FROM occupancy WHERE facility_id=? AND date BETWEEN ? AND ?",
        (facility_id, start.isoformat(), end.isoformat()))}
    recs = {}
    for r in conn.execute("SELECT resident_id,date,type,status FROM records WHERE facility_id=? AND date BETWEEN ? AND ?",
                          (facility_id, start.isoformat(), end.isoformat())):
        recs.setdefault((r["resident_id"], r["date"]), []).append(r)

    for res in residents:
        for day in _dates(start, end):
            status = occ.get((res["id"], day))
            day_recs = recs.get((res["id"], day), [])
            if status is None:
                if day != today.isoformat():
                    add("error", "稼働・請求", f"{res['name']}さん：稼働表（在宅・外泊など）が未入力です。", day, res["id"], "occupancy")
                continue
            if status == "在宅":
                have = {r["type"] for r in day_recs}
                for t in DAILY_REQUIRED_TYPES:
                    if t not in have and day != today.isoformat():
                        add("error", "記録もれ", f"{res['name']}さん：{FORM_DEFS[t]['label']}の記録がありません。",
                            day, res["id"], "record")
            elif status in ("入院", "退去") and day_recs:
                add("warn", "稼働・請求", f"{res['name']}さん：稼働表は「{status}」ですが、生活の記録があります。どちらが正しいか確認してください。",
                    day, res["id"], "occupancy")

    pending = conn.execute(
        "SELECT COUNT(*) c FROM records WHERE facility_id=? AND date BETWEEN ? AND ? AND status IN ('submitted','returned')",
        (facility_id, start.isoformat(), end.isoformat())).fetchone()["c"]
    if pending:
        add("warn", "承認", f"まだ承認されていない記録が{pending}件あります。請求の前に確認・承認してください。", link="approval")

    users = {u["id"]: u["name"] for u in conn.execute("SELECT id,name FROM users WHERE facility_id=?", (facility_id,))}
    shifts = {(s["user_id"], s["date"]): s for s in conn.execute(
        "SELECT * FROM shifts WHERE facility_id=? AND date BETWEEN ? AND ?", (facility_id, start.isoformat(), end.isoformat()))}
    atts = {(a["user_id"], a["date"]): a for a in conn.execute(
        "SELECT * FROM attendance WHERE facility_id=? AND date BETWEEN ? AND ?", (facility_id, start.isoformat(), end.isoformat()))}
    for key, s in shifts.items():
        uid, day = key
        a = atts.get(key)
        name = users.get(uid, f"職員{uid}")
        if a is None:
            if day != today.isoformat():
                add("error", "勤怠", f"{name}さん：シフト（{s['start']}〜{s['end']}）がありますが、打刻がありません。", day, link="attendance")
            continue
        for label, plan, act in (("出勤", s["start"], a["clock_in"]), ("退勤", s["end"], a["clock_out"])):
            if not act:
                if day != today.isoformat():
                    add("error", "勤怠", f"{name}さん：{label}の打刻がありません。", day, link="attendance")
            elif abs(_minutes(plan) - _minutes(act)) >= TOLERANCE_MIN:
                add("warn", "勤怠", f"{name}さん：{label}がシフト {plan} と打刻 {act} で{TOLERANCE_MIN}分以上ちがいます。", day, link="attendance")
    for key, a in atts.items():
        if key not in shifts:
            add("warn", "勤怠", f"{users.get(key[0], key[0])}さん：シフトがない日に打刻があります。", key[1], link="attendance")

    soon = (today + datetime.timedelta(days=30)).isoformat()
    for p in conn.execute("SELECT p.*, r.name FROM plans p JOIN residents r ON r.id=p.resident_id "
                          "WHERE p.facility_id=? AND r.active=1", (facility_id,)):
        if p["end_date"] and p["end_date"] <= soon:
            add("warn", "個別支援計画", f"{p['name']}さん：個別支援計画の期間が {p['end_date']} で終わります。見直しの準備をしてください。",
                resident_id=p["resident_id"], link="plans")
        if p["next_monitoring"] and p["next_monitoring"] <= (today + datetime.timedelta(days=14)).isoformat():
            add("info", "個別支援計画", f"{p['name']}さん：モニタリング予定日は {p['next_monitoring']} です。",
                resident_id=p["resident_id"], link="plans")

    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: (order[i["level"]], i["date"] or "", i["category"]))
    summary = {lvl: sum(1 for i in issues if i["level"] == lvl) for lvl in order}
    return {"issues": issues, "summary": summary, "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "range": [start.isoformat(), end.isoformat()]}
