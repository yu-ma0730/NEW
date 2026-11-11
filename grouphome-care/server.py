#!/usr/bin/env python3
"""グループホーム記録システム（ケアきろく）のサーバー。

起動:  python3 server.py            → http://localhost:8000 をブラウザで開く
HTTPS: python3 server.py --cert cert.pem --key key.pem

外部ライブラリ不要（Python 3.9以上の標準機能だけで動きます）。
外部のAIサービスやクラウドへ、記録データを送信する処理はありません。
"""
import argparse
import csv
import datetime
import io
import json
import mimetypes
import os
import re
import secrets
import ssl
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app import ai, checks, db, reports

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
ROLE_LEVEL = {"staff": 1, "sabikan": 2, "manager": 3}
ROLE_LABEL = {"staff": "職員", "sabikan": "サービス管理責任者", "manager": "管理者"}
SESSION_HOURS = 12
MAX_BODY = 2 * 1024 * 1024
APPROVABLE = {"records", "incidents", "documents", "plans"}

_failed = {}
_failed_lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def today():
    return datetime.date.today()


def parse_date(s, default=None):
    if not s:
        return default
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise ApiError(400, "日付の形式が正しくありません（例: 2026-01-31）")


def month_range(month):
    if not month:
        t = today()
        month = f"{t.year}-{t.month:02d}"
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ApiError(400, "月の形式が正しくありません（例: 2026-01）")
    y, m = map(int, month.split("-"))
    start = datetime.date(y, m, 1)
    end = (datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1))
    return start, end


ROUTES = []


def route(method, pattern, min_role=None, public=False):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, min_role, public))
        return fn
    return deco


def rows(cur):
    return [dict(r) for r in cur]


# ---------------- 認証 ----------------
@route("POST", "/api/login", public=True)
def login(h, conn, user, body, q):
    login_id = (body.get("login_id") or "").strip()
    with _failed_lock:
        fails = [t for t in _failed.get(login_id, []) if time.time() - t < 300]
        _failed[login_id] = fails
        if len(fails) >= 5:
            raise ApiError(429, "失敗が続いたため5分間ログインできません。")
    u = conn.execute("SELECT * FROM users WHERE login_id=? AND active=1", (login_id,)).fetchone()
    if not u or not db.verify_password(body.get("password") or "", u["pw_hash"], u["salt"]):
        with _failed_lock:
            _failed.setdefault(login_id, []).append(time.time())
        raise ApiError(401, "IDかパスワードがちがいます。")
    token = secrets.token_urlsafe(32)
    exp = (datetime.datetime.now() + datetime.timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)", (token, u["id"], exp))
    db.audit(conn, u["facility_id"], u["id"], "ログイン")
    h.set_cookie = f"sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_HOURS * 3600}" + ("; Secure" if h.server.tls else "")
    return {"ok": True}


@route("POST", "/api/logout")
def logout(h, conn, user, body, q):
    conn.execute("DELETE FROM sessions WHERE token=?", (h.token,))
    db.audit(conn, user["facility_id"], user["id"], "ログアウト")
    h.set_cookie = "sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
    return {"ok": True}


@route("GET", "/api/me")
def me(h, conn, user, body, q):
    fac = conn.execute("SELECT * FROM facilities WHERE id=?", (user["facility_id"],)).fetchone()
    return {"id": user["id"], "name": user["name"], "role": user["role"], "role_label": ROLE_LABEL[user["role"]],
            "level": ROLE_LEVEL[user["role"]], "facility": dict(fac), "today": today().isoformat()}


@route("GET", "/api/meta", public=True)
def meta(h, conn, user, body, q):
    return {"forms": ai.FORM_DEFS, "daily_required": ai.DAILY_REQUIRED_TYPES, "doc_kinds": reports.DOC_KINDS,
            "incident_categories": ["転倒", "転落", "服薬", "誤嚥・窒息", "けが", "無断外出", "他害・トラブル", "物品破損", "感染症", "その他"]}


@route("POST", "/api/password")
def change_password(h, conn, user, body, q):
    if not db.verify_password(body.get("current") or "", user["pw_hash"], user["salt"]):
        raise ApiError(400, "今のパスワードがちがいます。")
    new = body.get("new") or ""
    if len(new) < 8:
        raise ApiError(400, "新しいパスワードは8文字以上にしてください。")
    hsh, salt = db.hash_password(new)
    conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (hsh, salt, user["id"]))
    db.audit(conn, user["facility_id"], user["id"], "パスワード変更", "users", user["id"])
    return {"ok": True}


# ---------------- 利用者・職員・計画 ----------------
@route("GET", "/api/residents")
def list_residents(h, conn, user, body, q):
    return rows(conn.execute("SELECT * FROM residents WHERE facility_id=? ORDER BY active DESC, room, id", (user["facility_id"],)))


@route("POST", "/api/residents", min_role="sabikan")
def save_resident(h, conn, user, body, q):
    if not (body.get("name") or "").strip():
        raise ApiError(400, "名前を入力してください。")
    fields = {k: body.get(k) for k in ("name", "kana", "room", "birth_date", "notes")}
    fields["active"] = 1 if body.get("active", True) else 0
    if body.get("id"):
        before = conn.execute("SELECT * FROM residents WHERE id=? AND facility_id=?", (body["id"], user["facility_id"])).fetchone()
        if not before:
            raise ApiError(404, "利用者が見つかりません。")
        conn.execute("UPDATE residents SET name=?,kana=?,room=?,birth_date=?,notes=?,active=? WHERE id=?",
                     (*fields.values(), body["id"]))
        db.audit(conn, user["facility_id"], user["id"], "利用者情報を変更", "residents", body["id"], dict(before), fields)
        return {"id": body["id"]}
    cur = conn.execute("INSERT INTO residents(facility_id,name,kana,room,birth_date,notes,active) VALUES(?,?,?,?,?,?,?)",
                       (user["facility_id"], *fields.values()))
    db.audit(conn, user["facility_id"], user["id"], "利用者を登録", "residents", cur.lastrowid, None, fields)
    return {"id": cur.lastrowid}


@route("GET", "/api/users")
def list_users(h, conn, user, body, q):
    return rows(conn.execute("SELECT id,name,login_id,role,active FROM users WHERE facility_id=? ORDER BY id", (user["facility_id"],)))


@route("POST", "/api/users", min_role="manager")
def save_user(h, conn, user, body, q):
    role = body.get("role")
    if role not in ROLE_LEVEL or not (body.get("name") or "").strip():
        raise ApiError(400, "名前と役割を入力してください。")
    if body.get("id"):
        before = conn.execute("SELECT id,name,login_id,role,active FROM users WHERE id=? AND facility_id=?",
                              (body["id"], user["facility_id"])).fetchone()
        if not before:
            raise ApiError(404, "職員が見つかりません。")
        conn.execute("UPDATE users SET name=?, role=?, active=? WHERE id=?",
                     (body["name"], role, 1 if body.get("active", True) else 0, body["id"]))
        if body.get("password"):
            hsh, salt = db.hash_password(body["password"])
            conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (hsh, salt, body["id"]))
        db.audit(conn, user["facility_id"], user["id"], "職員情報を変更", "users", body["id"], dict(before),
                 {"name": body["name"], "role": role, "active": body.get("active", True), "password_changed": bool(body.get("password"))})
        return {"id": body["id"]}
    login_id = (body.get("login_id") or "").strip()
    pw = body.get("password") or ""
    if not login_id or len(pw) < 8:
        raise ApiError(400, "ログインIDと8文字以上のパスワードを入力してください。")
    if conn.execute("SELECT 1 FROM users WHERE login_id=?", (login_id,)).fetchone():
        raise ApiError(400, "そのログインIDはすでに使われています。")
    hsh, salt = db.hash_password(pw)
    cur = conn.execute("INSERT INTO users(facility_id,name,login_id,pw_hash,salt,role) VALUES(?,?,?,?,?,?)",
                       (user["facility_id"], body["name"], login_id, hsh, salt, role))
    db.audit(conn, user["facility_id"], user["id"], "職員を登録", "users", cur.lastrowid, None,
             {"name": body["name"], "login_id": login_id, "role": role})
    return {"id": cur.lastrowid}


@route("GET", "/api/plans")
def list_plans(h, conn, user, body, q):
    return rows(conn.execute("SELECT p.*, r.name resident_name FROM plans p JOIN residents r ON r.id=p.resident_id "
                             "WHERE p.facility_id=? ORDER BY r.room, p.id DESC", (user["facility_id"],)))


@route("POST", "/api/plans", min_role="sabikan")
def save_plan(h, conn, user, body, q):
    res = conn.execute("SELECT id FROM residents WHERE id=? AND facility_id=?", (body.get("resident_id"), user["facility_id"])).fetchone()
    if not res:
        raise ApiError(400, "利用者を選んでください。")
    vals = [body.get(k) for k in ("goal", "support", "start_date", "end_date", "next_monitoring")]
    if body.get("id"):
        before = conn.execute("SELECT * FROM plans WHERE id=? AND facility_id=?", (body["id"], user["facility_id"])).fetchone()
        if not before:
            raise ApiError(404, "計画が見つかりません。")
        conn.execute("UPDATE plans SET goal=?,support=?,start_date=?,end_date=?,next_monitoring=?,status='submitted' WHERE id=?",
                     (*vals, body["id"]))
        db.audit(conn, user["facility_id"], user["id"], "個別支援計画を変更", "plans", body["id"], dict(before), body)
        return {"id": body["id"]}
    cur = conn.execute("INSERT INTO plans(facility_id,resident_id,goal,support,start_date,end_date,next_monitoring,created_by,created_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?)", (user["facility_id"], res["id"], *vals, user["id"], db.now()))
    db.audit(conn, user["facility_id"], user["id"], "個別支援計画を登録", "plans", cur.lastrowid, None, body)
    return {"id": cur.lastrowid}


# ---------------- 記録 ----------------
@route("POST", "/api/ai/draft")
def ai_draft(h, conn, user, body, q):
    try:
        return ai.draft(body.get("type"), body.get("fields"), body.get("memo", ""), body.get("phrases"))
    except ValueError:
        raise ApiError(400, "記録の種類が正しくありません。")


@route("POST", "/api/ai/parse")
def ai_parse(h, conn, user, body, q):
    try:
        return ai.parse_speech(body.get("type"), body.get("text", ""))
    except ValueError:
        raise ApiError(400, "記録の種類が正しくありません。")


RECORD_SELECT = ("SELECT r.*, res.name resident_name, cu.name created_by_name, au.name approved_by_name FROM records r "
                 "LEFT JOIN residents res ON res.id=r.resident_id LEFT JOIN users cu ON cu.id=r.created_by "
                 "LEFT JOIN users au ON au.id=r.approved_by ")


@route("GET", "/api/records")
def list_records(h, conn, user, body, q):
    where, args = ["r.facility_id=?"], [user["facility_id"]]
    if q.get("date_from"):
        where.append("r.date>=?"); args.append(parse_date(q["date_from"]).isoformat())
    if q.get("date_to"):
        where.append("r.date<=?"); args.append(parse_date(q["date_to"]).isoformat())
    for k in ("resident_id", "type", "status"):
        if q.get(k):
            where.append(f"r.{k}=?"); args.append(q[k])
    if q.get("q"):
        where.append("(r.text LIKE ? OR r.memo LIKE ?)"); args += [f"%{q['q']}%"] * 2
    sql = RECORD_SELECT + "WHERE " + " AND ".join(where) + " ORDER BY r.date DESC, r.time DESC, r.id DESC LIMIT 500"
    return rows(conn.execute(sql, args))


@route("GET", r"/api/records/(\d+)")
def get_record(h, conn, user, body, q, rec_id):
    r = conn.execute(RECORD_SELECT + "WHERE r.id=? AND r.facility_id=?", (rec_id, user["facility_id"])).fetchone()
    if not r:
        raise ApiError(404, "記録が見つかりません。")
    return dict(r)


@route("POST", "/api/records")
def create_record(h, conn, user, body, q):
    rtype = body.get("type")
    if rtype not in ai.FORM_DEFS:
        raise ApiError(400, "記録の種類を選んでください。")
    rid = body.get("resident_id")
    if rid:
        if not conn.execute("SELECT 1 FROM residents WHERE id=? AND facility_id=?", (rid, user["facility_id"])).fetchone():
            raise ApiError(400, "利用者が見つかりません。")
    elif not ai.FORM_DEFS[rtype].get("resident_optional"):
        raise ApiError(400, "利用者を選んでください。")
    text = (body.get("text") or "").strip()
    if not text:
        raise ApiError(400, "記録の文章が空です。「文章にする」を押すか、直接書いてください。")
    date = parse_date(body.get("date"), today()).isoformat()
    status = "draft" if body.get("draft") else "submitted"
    vals = (user["facility_id"], rid, date, body.get("time"), rtype, json.dumps(body.get("fields") or {}, ensure_ascii=False),
            body.get("memo"), text, 1 if (body.get("handover") or rtype == "handover") else 0, status, user["id"], db.now())
    cur = conn.execute("INSERT INTO records(facility_id,resident_id,date,time,type,data_json,memo,text,handover,status,created_by,created_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", vals)
    db.audit(conn, user["facility_id"], user["id"], "記録を作成", "records", cur.lastrowid, None,
             {"type": rtype, "date": date, "text": text, "status": status})
    return {"id": cur.lastrowid}


@route("POST", r"/api/records/(\d+)")
def update_record(h, conn, user, body, q, rec_id):
    before = conn.execute("SELECT * FROM records WHERE id=? AND facility_id=?", (rec_id, user["facility_id"])).fetchone()
    if not before:
        raise ApiError(404, "記録が見つかりません。")
    is_admin = ROLE_LEVEL[user["role"]] >= 2
    if not is_admin and (before["created_by"] != user["id"] or before["status"] == "approved"):
        raise ApiError(403, "この記録は直せません（承認済み、または他の職員の記録です）。管理者に相談してください。")
    text = (body.get("text") or "").strip()
    if not text:
        raise ApiError(400, "記録の文章が空です。")
    status = "draft" if body.get("draft") else "submitted"
    conn.execute("UPDATE records SET text=?, memo=?, data_json=?, handover=?, time=?, status=?, updated_by=?, updated_at=?, "
                 "approved_by=NULL, approved_at=NULL WHERE id=?",
                 (text, body.get("memo", before["memo"]), json.dumps(body.get("fields") or json.loads(before["data_json"]), ensure_ascii=False),
                  1 if body.get("handover", before["handover"]) else 0, body.get("time", before["time"]), status, user["id"], db.now(), rec_id))
    db.audit(conn, user["facility_id"], user["id"], "記録を修正", "records", int(rec_id),
             {"text": before["text"], "status": before["status"]}, {"text": text, "status": status})
    return {"id": int(rec_id)}


@route("GET", "/api/handovers")
def handovers(h, conn, user, body, q):
    days = max(1, min(int(q.get("days") or 3), 14))
    since = (today() - datetime.timedelta(days=days - 1)).isoformat()
    rs = conn.execute(RECORD_SELECT + "WHERE r.facility_id=? AND r.handover=1 AND r.date>=? ORDER BY r.date DESC, r.time DESC",
                      (user["facility_id"], since)).fetchall()
    notes = conn.execute("SELECT name, notes FROM residents WHERE facility_id=? AND active=1 AND notes<>''", (user["facility_id"],)).fetchall()
    return {"groups": ai.summarize_handovers(rs), "notes": rows(notes), "since": since}


# ---------------- 承認・履歴 ----------------
@route("GET", "/api/approvals", min_role="sabikan")
def approvals(h, conn, user, body, q):
    fid = user["facility_id"]
    return {
        "records": rows(conn.execute(RECORD_SELECT + "WHERE r.facility_id=? AND r.status='submitted' ORDER BY r.date, r.id", (fid,))),
        "incidents": rows(conn.execute("SELECT i.*, res.name resident_name, u.name created_by_name FROM incidents i LEFT JOIN residents res "
                                       "ON res.id=i.resident_id LEFT JOIN users u ON u.id=i.created_by WHERE i.facility_id=? AND i.status='submitted'", (fid,))),
        "documents": rows(conn.execute("SELECT d.*, u.name created_by_name FROM documents d LEFT JOIN users u ON u.id=d.created_by "
                                       "WHERE d.facility_id=? AND d.status='submitted'", (fid,))),
        "plans": rows(conn.execute("SELECT p.*, r.name resident_name FROM plans p JOIN residents r ON r.id=p.resident_id "
                                   "WHERE p.facility_id=? AND p.status='submitted'", (fid,))),
    }


@route("POST", "/api/approve", min_role="sabikan")
def approve(h, conn, user, body, q):
    target = body.get("target")
    if target not in APPROVABLE:
        raise ApiError(400, "対象が正しくありません。")
    action = body.get("action")
    if action not in ("approve", "return"):
        raise ApiError(400, "操作が正しくありません。")
    ids = body.get("ids") or ([body["id"]] if body.get("id") else [])
    comment = (body.get("comment") or "").strip()
    if action == "return" and not comment:
        raise ApiError(400, "差し戻す理由を書いてください。")
    done = 0
    for i in ids:
        row = conn.execute(f"SELECT status FROM {target} WHERE id=? AND facility_id=?", (i, user["facility_id"])).fetchone()
        if not row:
            continue
        new = "approved" if action == "approve" else "returned"
        conn.execute(f"UPDATE {target} SET status=?, approved_by=?, approved_at=?, comment=? WHERE id=?",
                     (new, user["id"], db.now(), comment or None, i))
        db.audit(conn, user["facility_id"], user["id"], "承認" if action == "approve" else "差し戻し", target, i,
                 {"status": row["status"]}, {"status": new, "comment": comment})
        done += 1
    return {"updated": done}


@route("GET", "/api/audit", min_role="sabikan")
def audit_list(h, conn, user, body, q):
    where, args = ["a.facility_id=?"], [user["facility_id"]]
    if q.get("target"):
        where.append("a.target=?"); args.append(q["target"])
    if q.get("target_id"):
        where.append("a.target_id=?"); args.append(q["target_id"])
    return rows(conn.execute("SELECT a.*, u.name user_name FROM audit_log a LEFT JOIN users u ON u.id=a.user_id WHERE "
                             + " AND ".join(where) + " ORDER BY a.id DESC LIMIT 300", args))


@route("GET", "/api/mine")
def my_returned(h, conn, user, body, q):
    return rows(conn.execute(RECORD_SELECT + "WHERE r.facility_id=? AND r.created_by=? AND r.status IN ('returned','draft') ORDER BY r.date DESC",
                             (user["facility_id"], user["id"])))


# ---------------- チェック ----------------
@route("GET", "/api/checks", min_role="sabikan")
def run_checks(h, conn, user, body, q):
    start, end = month_range(q.get("month"))
    result = checks.run_checks(conn, user["facility_id"], start, end, today())
    db.audit(conn, user["facility_id"], user["id"], "請求前チェックを実行", after={"month": q.get("month"), **result["summary"]})
    return result


@route("GET", "/api/occupancy")
def occupancy(h, conn, user, body, q):
    start, end = month_range(q.get("month"))
    data = {f"{r['resident_id']}|{r['date']}": r["status"] for r in conn.execute(
        "SELECT * FROM occupancy WHERE facility_id=? AND date BETWEEN ? AND ?", (user["facility_id"], start.isoformat(), end.isoformat()))}
    days = [(start + datetime.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    res = rows(conn.execute("SELECT id,name,room FROM residents WHERE facility_id=? AND active=1 ORDER BY room", (user["facility_id"],)))
    return {"days": days, "residents": res, "data": data}


@route("POST", "/api/occupancy", min_role="sabikan")
def set_occupancy(h, conn, user, body, q):
    status = body.get("status")
    date = parse_date(body.get("date")).isoformat()
    rid = body.get("resident_id")
    if not conn.execute("SELECT 1 FROM residents WHERE id=? AND facility_id=?", (rid, user["facility_id"])).fetchone():
        raise ApiError(400, "利用者が見つかりません。")
    before = conn.execute("SELECT status FROM occupancy WHERE resident_id=? AND date=?", (rid, date)).fetchone()
    if status in ("", None):
        conn.execute("DELETE FROM occupancy WHERE resident_id=? AND date=?", (rid, date))
    elif status in ("在宅", "外泊", "入院", "退去"):
        conn.execute("INSERT INTO occupancy(facility_id,resident_id,date,status) VALUES(?,?,?,?) "
                     "ON CONFLICT(resident_id,date) DO UPDATE SET status=excluded.status", (user["facility_id"], rid, date, status))
    else:
        raise ApiError(400, "状態が正しくありません。")
    db.audit(conn, user["facility_id"], user["id"], "稼働表を変更", "occupancy", rid,
             {"date": date, "status": before["status"] if before else None}, {"date": date, "status": status})
    return {"ok": True}


@route("GET", "/api/shifts")
def shifts(h, conn, user, body, q):
    start, end = month_range(q.get("month"))
    a = (user["facility_id"], start.isoformat(), end.isoformat())
    return {
        "shifts": rows(conn.execute("SELECT s.*, u.name user_name FROM shifts s JOIN users u ON u.id=s.user_id "
                                    "WHERE s.facility_id=? AND s.date BETWEEN ? AND ? ORDER BY s.date, s.start", a)),
        "attendance": rows(conn.execute("SELECT t.*, u.name user_name FROM attendance t JOIN users u ON u.id=t.user_id "
                                        "WHERE t.facility_id=? AND t.date BETWEEN ? AND ? ORDER BY t.date", a)),
    }


def _hhmm(v, label):
    if v in (None, ""):
        return None
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ApiError(400, f"{label}の時刻は 09:00 のように入力してください。")
    return v


@route("POST", "/api/shifts", min_role="manager")
def save_shift(h, conn, user, body, q):
    uid = body.get("user_id")
    if not conn.execute("SELECT 1 FROM users WHERE id=? AND facility_id=?", (uid, user["facility_id"])).fetchone():
        raise ApiError(400, "職員を選んでください。")
    date = parse_date(body.get("date")).isoformat()
    st, en = _hhmm(body.get("start"), "開始"), _hhmm(body.get("end"), "終了")
    if not st or not en:
        raise ApiError(400, "開始と終了の時刻を入力してください。")
    conn.execute("DELETE FROM shifts WHERE user_id=? AND date=?", (uid, date))
    conn.execute("INSERT INTO shifts(facility_id,user_id,date,start,end) VALUES(?,?,?,?,?)", (user["facility_id"], uid, date, st, en))
    db.audit(conn, user["facility_id"], user["id"], "シフトを登録", "shifts", uid, None, {"date": date, "start": st, "end": en})
    return {"ok": True}


@route("POST", "/api/attendance", min_role="manager")
def save_attendance(h, conn, user, body, q):
    uid = body.get("user_id")
    if not conn.execute("SELECT 1 FROM users WHERE id=? AND facility_id=?", (uid, user["facility_id"])).fetchone():
        raise ApiError(400, "職員を選んでください。")
    date = parse_date(body.get("date")).isoformat()
    cin, cout = _hhmm(body.get("clock_in"), "出勤"), _hhmm(body.get("clock_out"), "退勤")
    before = conn.execute("SELECT clock_in, clock_out FROM attendance WHERE user_id=? AND date=?", (uid, date)).fetchone()
    conn.execute("DELETE FROM attendance WHERE user_id=? AND date=?", (uid, date))
    conn.execute("INSERT INTO attendance(facility_id,user_id,date,clock_in,clock_out) VALUES(?,?,?,?,?)",
                 (user["facility_id"], uid, date, cin, cout))
    db.audit(conn, user["facility_id"], user["id"], "勤怠を修正", "attendance", uid,
             dict(before) if before else None, {"date": date, "clock_in": cin, "clock_out": cout})
    return {"ok": True}


@route("POST", "/api/clock")
def clock(h, conn, user, body, q):
    kind = body.get("kind")
    if kind not in ("in", "out"):
        raise ApiError(400, "出勤か退勤を選んでください。")
    now = datetime.datetime.now()
    hhmm = now.strftime("%H:%M")
    d = now.date().isoformat()
    row = conn.execute("SELECT * FROM attendance WHERE user_id=? AND date=?", (user["id"], d)).fetchone()
    if kind == "out" and not row:
        # 夜勤明け：前日の出勤記録に退勤を付ける
        prev = (now.date() - datetime.timedelta(days=1)).isoformat()
        row = conn.execute("SELECT * FROM attendance WHERE user_id=? AND date=? AND clock_out IS NULL", (user["id"], prev)).fetchone()
    if row:
        col = "clock_in" if kind == "in" else "clock_out"
        conn.execute(f"UPDATE attendance SET {col}=? WHERE id=?", (hhmm, row["id"]))
    else:
        conn.execute("INSERT INTO attendance(facility_id,user_id,date,clock_in,clock_out) VALUES(?,?,?,?,?)",
                     (user["facility_id"], user["id"], d, hhmm if kind == "in" else None, hhmm if kind == "out" else None))
    db.audit(conn, user["facility_id"], user["id"], "出勤打刻" if kind == "in" else "退勤打刻", "attendance", user["id"], None, {"time": hhmm})
    return {"time": hhmm}


# ---------------- 事故・ヒヤリハット ----------------
@route("GET", "/api/incidents")
def list_incidents(h, conn, user, body, q):
    where, args = ["i.facility_id=?"], [user["facility_id"]]
    if q.get("category"):
        where.append("i.category=?"); args.append(q["category"])
    if q.get("kind"):
        where.append("i.kind=?"); args.append(q["kind"])
    if q.get("q"):
        where.append("(i.description LIKE ? OR i.cause LIKE ? OR i.prevention LIKE ? OR i.place LIKE ?)"); args += [f"%{q['q']}%"] * 4
    return rows(conn.execute("SELECT i.*, res.name resident_name, u.name created_by_name FROM incidents i LEFT JOIN residents res "
                             "ON res.id=i.resident_id LEFT JOIN users u ON u.id=i.created_by WHERE " + " AND ".join(where) +
                             " ORDER BY i.date DESC, i.id DESC", args))


@route("POST", "/api/incidents")
def save_incident(h, conn, user, body, q):
    if body.get("kind") not in ("事故", "ヒヤリハット") or not body.get("category"):
        raise ApiError(400, "「事故かヒヤリハットか」と「分類」を選んでください。")
    if not (body.get("description") or "").strip():
        raise ApiError(400, "何があったか（発生状況）を書いてください。")
    rid = body.get("resident_id") or None
    if rid and not conn.execute("SELECT 1 FROM residents WHERE id=? AND facility_id=?", (rid, user["facility_id"])).fetchone():
        raise ApiError(400, "利用者が見つかりません。")
    vals = [rid, parse_date(body.get("date"), today()).isoformat(), body.get("time"), body["kind"], body["category"]] + \
           [body.get(k) for k in ("place", "description", "cause", "action_taken", "prevention")]
    if body.get("id"):
        before = conn.execute("SELECT * FROM incidents WHERE id=? AND facility_id=?", (body["id"], user["facility_id"])).fetchone()
        if not before:
            raise ApiError(404, "見つかりません。")
        if ROLE_LEVEL[user["role"]] < 2 and before["created_by"] != user["id"]:
            raise ApiError(403, "他の職員の報告は直せません。")
        conn.execute("UPDATE incidents SET resident_id=?,date=?,time=?,kind=?,category=?,place=?,description=?,cause=?,action_taken=?,"
                     "prevention=?,status='submitted' WHERE id=?", (*vals, body["id"]))
        db.audit(conn, user["facility_id"], user["id"], "事故・ヒヤリを修正", "incidents", body["id"], dict(before), body)
        return {"id": body["id"]}
    cur = conn.execute("INSERT INTO incidents(resident_id,date,time,kind,category,place,description,cause,action_taken,prevention,"
                       "facility_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (*vals, user["facility_id"], user["id"], db.now()))
    db.audit(conn, user["facility_id"], user["id"], "事故・ヒヤリを報告", "incidents", cur.lastrowid, None, body)
    return {"id": cur.lastrowid}


@route("GET", "/api/incidents/similar")
def incidents_similar(h, conn, user, body, q):
    return reports.similar_incidents(conn, user["facility_id"], q.get("q", ""), q.get("category"))


@route("GET", "/api/incidents/stats")
def incidents_stats(h, conn, user, body, q):
    start = parse_date(q.get("start"), today() - datetime.timedelta(days=90)).isoformat()
    end = parse_date(q.get("end"), today()).isoformat()
    st = reports.incident_stats(conn, user["facility_id"], start, end)
    st.pop("rows")
    st["start"], st["end"] = start, end
    return st


# ---------------- 書類 ----------------
@route("POST", "/api/documents/draft")
def doc_draft(h, conn, user, body, q):
    fac = conn.execute("SELECT * FROM facilities WHERE id=?", (user["facility_id"],)).fetchone()
    try:
        return reports.build(conn, dict(fac), body.get("kind"), body.get("params"))
    except ValueError as e:
        raise ApiError(400, str(e))


@route("GET", "/api/documents")
def list_documents(h, conn, user, body, q):
    return rows(conn.execute("SELECT d.*, u.name created_by_name, a.name approved_by_name FROM documents d LEFT JOIN users u ON u.id=d.created_by "
                             "LEFT JOIN users a ON a.id=d.approved_by WHERE d.facility_id=? ORDER BY d.id DESC", (user["facility_id"],)))


@route("POST", "/api/documents")
def save_document(h, conn, user, body, q):
    if body.get("kind") not in reports.DOC_KINDS or not body.get("title"):
        raise ApiError(400, "書類の種類とタイトルが必要です。")
    content = {"sections": body.get("sections") or []}
    missing = [s["heading"] for s in content["sections"] if s.get("required") and not (s.get("body") or "").strip()]
    if missing and not body.get("allow_missing"):
        raise ApiError(400, "記入もれがあります：" + "、".join(missing))
    cur = conn.execute("INSERT INTO documents(facility_id,kind,title,content_json,created_by,created_at) VALUES(?,?,?,?,?,?)",
                       (user["facility_id"], body["kind"], body["title"], json.dumps(content, ensure_ascii=False), user["id"], db.now()))
    db.audit(conn, user["facility_id"], user["id"], "書類を作成", "documents", cur.lastrowid, None, {"title": body["title"]})
    return {"id": cur.lastrowid}


# ---------------- チェックリスト・通知・期限 ----------------
@route("GET", "/api/checklist")
def checklist(h, conn, user, body, q):
    d = parse_date(q.get("date"), today()).isoformat()
    return rows(conn.execute("SELECT c.*, d.done_at, u.name done_by FROM checklist_items c LEFT JOIN checklist_done d "
                             "ON d.item_id=c.id AND d.date=? LEFT JOIN users u ON u.id=d.user_id WHERE c.facility_id=? AND c.active=1 "
                             "ORDER BY c.category, c.id", (d, user["facility_id"])))


@route("POST", "/api/checklist/done")
def checklist_done(h, conn, user, body, q):
    d = parse_date(body.get("date"), today()).isoformat()
    item = conn.execute("SELECT * FROM checklist_items WHERE id=? AND facility_id=?", (body.get("item_id"), user["facility_id"])).fetchone()
    if not item:
        raise ApiError(404, "項目が見つかりません。")
    if body.get("done", True):
        conn.execute("INSERT OR IGNORE INTO checklist_done(item_id,date,user_id,done_at) VALUES(?,?,?,?)", (item["id"], d, user["id"], db.now()))
    else:
        conn.execute("DELETE FROM checklist_done WHERE item_id=? AND date=?", (item["id"], d))
    db.audit(conn, user["facility_id"], user["id"], "チェック実施" if body.get("done", True) else "チェック取消", "checklist_items",
             item["id"], None, {"date": d, "name": item["name"]})
    return {"ok": True}


@route("POST", "/api/checklist/items", min_role="manager")
def add_checklist_item(h, conn, user, body, q):
    if not (body.get("name") and body.get("category")):
        raise ApiError(400, "分類と項目名を入力してください。")
    cur = conn.execute("INSERT INTO checklist_items(facility_id,category,name) VALUES(?,?,?)", (user["facility_id"], body["category"], body["name"]))
    db.audit(conn, user["facility_id"], user["id"], "チェック項目を追加", "checklist_items", cur.lastrowid, None, body)
    return {"id": cur.lastrowid}


@route("GET", "/api/deadlines")
def list_deadlines(h, conn, user, body, q):
    return rows(conn.execute("SELECT d.*, u.name assignee FROM deadlines d LEFT JOIN users u ON u.id=d.assignee_id "
                             "WHERE d.facility_id=? ORDER BY d.done, d.due_date", (user["facility_id"],)))


@route("POST", "/api/deadlines", min_role="sabikan")
def save_deadline(h, conn, user, body, q):
    if body.get("id"):
        conn.execute("UPDATE deadlines SET done=? WHERE id=? AND facility_id=?", (1 if body.get("done") else 0, body["id"], user["facility_id"]))
        db.audit(conn, user["facility_id"], user["id"], "期限の完了を変更", "deadlines", body["id"], None, {"done": body.get("done")})
        return {"id": body["id"]}
    if not body.get("title"):
        raise ApiError(400, "内容を入力してください。")
    cur = conn.execute("INSERT INTO deadlines(facility_id,title,due_date,assignee_id) VALUES(?,?,?,?)",
                       (user["facility_id"], body["title"], parse_date(body.get("due_date")).isoformat(), body.get("assignee_id") or None))
    db.audit(conn, user["facility_id"], user["id"], "期限を登録", "deadlines", cur.lastrowid, None, body)
    return {"id": cur.lastrowid}


@route("GET", "/api/notifications")
def notifications(h, conn, user, body, q):
    fid, t = user["facility_id"], today()
    out = []
    undone = conn.execute("SELECT c.category, c.name FROM checklist_items c LEFT JOIN checklist_done d ON d.item_id=c.id AND d.date=? "
                          "WHERE c.facility_id=? AND c.active=1 AND d.id IS NULL", (t.isoformat(), fid)).fetchall()
    if undone:
        cats = sorted({u["category"] for u in undone})
        out.append({"level": "warn", "text": f"今日のチェックがまだ{len(undone)}件あります（{'・'.join(cats)}）", "link": "checklist"})
    in_home = conn.execute("SELECT r.id, r.name FROM residents r JOIN occupancy o ON o.resident_id=r.id AND o.date=? "
                           "WHERE r.facility_id=? AND r.active=1 AND o.status='在宅'", (t.isoformat(), fid)).fetchall()
    have_med = {r["resident_id"] for r in conn.execute("SELECT resident_id FROM records WHERE facility_id=? AND date=? AND type='med'", (fid, t.isoformat()))}
    no_med = [r["name"] for r in in_home if r["id"] not in have_med]
    if no_med and datetime.datetime.now().hour >= 9:
        out.append({"level": "error", "text": "服薬の記録がまだ：" + "、".join(no_med), "link": "record"})
    for dl in conn.execute("SELECT d.*, u.name assignee FROM deadlines d LEFT JOIN users u ON u.id=d.assignee_id WHERE d.facility_id=? AND d.done=0 "
                           "AND d.due_date<=? AND (d.assignee_id IS NULL OR d.assignee_id=? OR ?>=2)",
                           (fid, (t + datetime.timedelta(days=7)).isoformat(), user["id"], ROLE_LEVEL[user["role"]])):
        left = (datetime.date.fromisoformat(dl["due_date"]) - t).days
        out.append({"level": "error" if left <= 1 else "warn",
                    "text": f"期限：{dl['title']}（{dl['due_date']}、あと{left}日）担当：{dl['assignee'] or '未定'}", "link": "deadlines"})
    imp = conn.execute("SELECT COUNT(*) c FROM records WHERE facility_id=? AND handover=1 AND date>=? AND data_json LIKE '%大事%'",
                       (fid, (t - datetime.timedelta(days=1)).isoformat())).fetchone()["c"]
    if imp:
        out.append({"level": "warn", "text": f"大事な申し送りが{imp}件あります", "link": "handover"})
    ret = conn.execute("SELECT COUNT(*) c FROM records WHERE created_by=? AND status='returned'", (user["id"],)).fetchone()["c"]
    if ret:
        out.append({"level": "error", "text": f"差し戻された記録が{ret}件あります。直してください", "link": "mine"})
    if ROLE_LEVEL[user["role"]] >= 2:
        pend = sum(conn.execute(f"SELECT COUNT(*) c FROM {tb} WHERE facility_id=? AND status='submitted'", (fid,)).fetchone()["c"] for tb in APPROVABLE)
        if pend:
            out.append({"level": "info", "text": f"承認待ちが{pend}件あります", "link": "approval"})
    return out


# ---------------- Excel(CSV)出力 ----------------
def _csv(h, name, header, data):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(data)
    h.raw = ("﻿" + buf.getvalue()).encode("utf-8")  # BOM付きUTF-8：Excelで文字化けしない
    h.raw_type = "text/csv; charset=utf-8"
    h.raw_name = name
    return None


@route("GET", "/api/export/records.csv", min_role="sabikan")
def export_records(h, conn, user, body, q):
    start, end = month_range(q.get("month"))
    rs = conn.execute(RECORD_SELECT + "WHERE r.facility_id=? AND r.date BETWEEN ? AND ? ORDER BY r.date, r.time",
                      (user["facility_id"], start.isoformat(), end.isoformat())).fetchall()
    status = {"draft": "下書き", "submitted": "承認待ち", "approved": "承認済み", "returned": "差し戻し"}
    db.audit(conn, user["facility_id"], user["id"], "記録をCSV出力", after={"month": q.get("month")})
    return _csv(h, f"records_{start:%Y%m}.csv", ["日付", "時刻", "利用者", "種類", "内容", "状態", "記録者", "承認者", "承認日時"],
                [[r["date"], r["time"] or "", r["resident_name"] or "", ai.FORM_DEFS[r["type"]]["label"], r["text"], status[r["status"]],
                  r["created_by_name"] or "", r["approved_by_name"] or "", r["approved_at"] or ""] for r in rs])


@route("GET", "/api/export/occupancy.csv", min_role="sabikan")
def export_occupancy(h, conn, user, body, q):
    o = occupancy(h, conn, user, body, q)
    mark = {"在宅": "○", "外泊": "外", "入院": "入", "退去": "退"}
    data = []
    for r in o["residents"]:
        line = [r["room"] or "", r["name"]] + [mark.get(o["data"].get(f"{r['id']}|{d}"), "") for d in o["days"]]
        line.append(sum(1 for d in o["days"] if o["data"].get(f"{r['id']}|{d}") == "在宅"))
        data.append(line)
    db.audit(conn, user["facility_id"], user["id"], "稼働表をCSV出力", after={"month": q.get("month")})
    return _csv(h, f"occupancy_{o['days'][0][:7].replace('-', '')}.csv", ["部屋", "利用者"] + [d[8:] for d in o["days"]] + ["在宅日数"], data)


@route("GET", "/api/export/attendance.csv", min_role="manager")
def export_attendance(h, conn, user, body, q):
    s = shifts(h, conn, user, body, q)
    att = {(a["user_id"], a["date"]): a for a in s["attendance"]}
    data = []
    for sh in s["shifts"]:
        a = att.get((sh["user_id"], sh["date"]))
        data.append([sh["date"], sh["user_name"], sh["start"], sh["end"], a["clock_in"] if a else "", a["clock_out"] if a else ""])
    db.audit(conn, user["facility_id"], user["id"], "勤務実績をCSV出力", after={"month": q.get("month")})
    return _csv(h, "attendance.csv", ["日付", "職員", "シフト開始", "シフト終了", "出勤打刻", "退勤打刻"], data)


# ---------------- HTTP処理 ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "CareKiroku"

    def log_message(self, fmt, *args):
        if not self.server.quiet:
            super().log_message(fmt, *args)

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if self.server.tls:
            self.send_header("Strict-Transport-Security", "max-age=31536000")

    def _send(self, status, payload, ctype="application/json; charset=utf-8", extra=None):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self._api("GET")
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as f:
            data = f.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, data, ctype)

    def do_POST(self):
        self._api("POST")

    def _user(self, conn):
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        self.token = c["sid"].value if "sid" in c else None
        if not self.token:
            return None
        return conn.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>? AND u.active=1",
                            (self.token, db.now())).fetchone()

    def _api(self, method):
        self.set_cookie = None
        self.raw = None
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        conn = db.connect(self.server.db_path)
        try:
            body = {}
            if method == "POST":
                # CSRF対策：画面(app.js)からの呼び出しには必ずこのヘッダーが付く
                if self.headers.get("X-Requested-With") != "carekiroku":
                    raise ApiError(403, "不正なリクエストです。")
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise ApiError(413, "データが大きすぎます。")
                if length:
                    try:
                        body = json.loads(self.rfile.read(length) or b"{}")
                    except json.JSONDecodeError:
                        raise ApiError(400, "データの形式が正しくありません。")
                    if not isinstance(body, dict):
                        raise ApiError(400, "データの形式が正しくありません。")
            for m, pattern, fn, min_role, public in ROUTES:
                if m != method:
                    continue
                match = pattern.match(u.path)
                if not match:
                    continue
                user = self._user(conn)
                if not public and not user:
                    raise ApiError(401, "ログインしてください。")
                if min_role and ROLE_LEVEL[user["role"]] < ROLE_LEVEL[min_role]:
                    raise ApiError(403, "この操作をする権限がありません。")
                result = fn(self, conn, user, body, q, *match.groups())
                conn.commit()
                extra = {"Set-Cookie": self.set_cookie} if self.set_cookie else {}
                if self.raw is not None:
                    extra["Content-Disposition"] = f'attachment; filename="{self.raw_name}"'
                    return self._send(200, self.raw, self.raw_type, extra)
                return self._send(200, result, extra=extra)
            raise ApiError(404, "見つかりません。")
        except ApiError as e:
            conn.rollback()
            self._send(e.status, {"error": e.message}, extra={"Set-Cookie": self.set_cookie} if self.set_cookie else None)
        except Exception as e:  # 想定外のエラーは中身を画面に出さず、サーバーログにだけ残す
            conn.rollback()
            self.log_error("server error: %r", e)
            self._send(500, {"error": "サーバーでエラーが起きました。管理者に連絡してください。"})
        finally:
            conn.close()


def make_server(db_path, host="127.0.0.1", port=8000, quiet=False, cert=None, key=None):
    db.init_db(db_path).close()
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.db_path = db_path
    srv.quiet = quiet
    srv.tls = bool(cert)
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv


def main():
    p = argparse.ArgumentParser(description="グループホーム記録システム")
    p.add_argument("--host", default="127.0.0.1", help="事業所内LANのタブレットから使うときは 0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--db", default=os.path.join(BASE, "data", "carekiroku.db"))
    p.add_argument("--cert")
    p.add_argument("--key")
    a = p.parse_args()
    os.makedirs(os.path.dirname(a.db), exist_ok=True)
    srv = make_server(a.db, a.host, a.port, cert=a.cert, key=a.key)
    scheme = "https" if a.cert else "http"
    print(f"起動しました → {scheme}://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}")
    print("デモ用ログイン：manager / sabikan / staff1 / staff2  （パスワードはすべて demo1234）")
    print("止めるときは Ctrl + C")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
