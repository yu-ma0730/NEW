"""データベース（SQLite）の作成・接続・初期データ投入。

外部ライブラリを使わず、Python標準の sqlite3 だけで動きます。
全テーブルに facility_id（事業所ID）を持たせ、複数事業所へ展開できる設計です。
"""
import datetime
import hashlib
import json
import os
import secrets
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS facilities (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, retention_years INTEGER NOT NULL DEFAULT 5
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL REFERENCES facilities(id),
  name TEXT NOT NULL, login_id TEXT NOT NULL UNIQUE, pw_hash TEXT NOT NULL, salt TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('staff','sabikan','manager')), active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS residents (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL REFERENCES facilities(id),
  name TEXT NOT NULL, kana TEXT, room TEXT, birth_date TEXT, notes TEXT, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, resident_id INTEGER NOT NULL REFERENCES residents(id),
  goal TEXT, support TEXT, start_date TEXT, end_date TEXT, next_monitoring TEXT,
  status TEXT NOT NULL DEFAULT 'submitted', created_by INTEGER, created_at TEXT,
  approved_by INTEGER, approved_at TEXT, comment TEXT
);
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, resident_id INTEGER REFERENCES residents(id),
  date TEXT NOT NULL, time TEXT, type TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}',
  memo TEXT, text TEXT, handover INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'submitted' CHECK(status IN ('draft','submitted','approved','returned')),
  created_by INTEGER, created_at TEXT, updated_by INTEGER, updated_at TEXT,
  approved_by INTEGER, approved_at TEXT, comment TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_date ON records(facility_id, date);
CREATE TABLE IF NOT EXISTS shifts (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
  date TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attendance (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
  date TEXT NOT NULL, clock_in TEXT, clock_out TEXT
);
CREATE TABLE IF NOT EXISTS occupancy (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, resident_id INTEGER NOT NULL REFERENCES residents(id),
  date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('在宅','外泊','入院','退去')),
  UNIQUE(resident_id, date)
);
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, resident_id INTEGER REFERENCES residents(id),
  date TEXT NOT NULL, time TEXT, kind TEXT NOT NULL CHECK(kind IN ('事故','ヒヤリハット')),
  category TEXT NOT NULL, place TEXT, description TEXT, cause TEXT, action_taken TEXT, prevention TEXT,
  status TEXT NOT NULL DEFAULT 'submitted', created_by INTEGER, created_at TEXT,
  approved_by INTEGER, approved_at TEXT, comment TEXT
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
  content_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'submitted', created_by INTEGER, created_at TEXT,
  approved_by INTEGER, approved_at TEXT, comment TEXT
);
CREATE TABLE IF NOT EXISTS checklist_items (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, category TEXT NOT NULL, name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS checklist_done (
  id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES checklist_items(id), date TEXT NOT NULL,
  user_id INTEGER NOT NULL, done_at TEXT NOT NULL, UNIQUE(item_id, date)
);
CREATE TABLE IF NOT EXISTS deadlines (
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL, title TEXT NOT NULL, due_date TEXT NOT NULL,
  assignee_id INTEGER REFERENCES users(id), done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY, facility_id INTEGER, user_id INTEGER, action TEXT NOT NULL,
  target TEXT, target_id INTEGER, before_json TEXT, after_json TEXT, at TEXT NOT NULL
);
"""


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 120_000).hex()
    return digest, salt


def verify_password(password, digest, salt):
    return secrets.compare_digest(hash_password(password, salt)[0], digest)


def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path, seed=True):
    first = not os.path.exists(path) or os.path.getsize(path) == 0
    conn = connect(path)
    conn.executescript(SCHEMA)
    if first and seed:
        seed_demo(conn)
    conn.commit()
    return conn


def audit(conn, facility_id, user_id, action, target=None, target_id=None, before=None, after=None):
    conn.execute(
        "INSERT INTO audit_log(facility_id,user_id,action,target,target_id,before_json,after_json,at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (facility_id, user_id, action, target, target_id,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None, now()),
    )


def seed_demo(conn, today=None):
    """デモ用の架空データ。実在の人物・事業所とは関係ありません。"""
    today = today or datetime.date.today()
    d = lambda n: (today - datetime.timedelta(days=n)).isoformat()
    conn.execute("INSERT INTO facilities(id,name) VALUES(1,'デモ事業所（グループホームさくら）')")
    users = [
        ("管理 花子", "manager", "manager"),
        ("サビ管 一郎", "sabikan", "sabikan"),
        ("職員 太郎", "staff1", "staff"),
        ("グエン ミン", "staff2", "staff"),
    ]
    for name, login, role in users:
        h, s = hash_password("demo1234")
        conn.execute("INSERT INTO users(facility_id,name,login_id,pw_hash,salt,role) VALUES(1,?,?,?,?,?)",
                     (name, login, h, s, role))
    residents = [
        ("山田 さとし", "やまだ さとし", "101", "てんかん発作歴あり。入浴時は見守り。"),
        ("佐藤 みき", "さとう みき", "102", "甘い物の食べすぎに注意。"),
        ("鈴木 けん", "すずき けん", "103", "夜間に不安が強くなることがある。"),
        ("高橋 ゆい", "たかはし ゆい", "201", "毎週土曜は家族宅へ外泊。"),
        ("田中 ひろし", "たなか ひろし", "202", "歩行時ふらつきあり。"),
    ]
    for name, kana, room, notes in residents:
        conn.execute("INSERT INTO residents(facility_id,name,kana,room,notes) VALUES(1,?,?,?,?)",
                     (name, kana, room, notes))
    for rid, goal in [(1, "自分で服薬の準備ができる"), (2, "体重を維持して健康に過ごす"),
                      (3, "夜に安心して眠れる"), (4, "家族との時間を大切にする"), (5, "転ばずに安全に歩く")]:
        conn.execute("INSERT INTO plans(facility_id,resident_id,goal,support,start_date,end_date,next_monitoring,"
                     "status,created_by,created_at) VALUES(1,?,?,?,?,?,?,'approved',2,?)",
                     (rid, goal, "声かけと見守りを行う", d(150), (today + datetime.timedelta(days=20 if rid == 5 else 120)).isoformat(),
                      (today + datetime.timedelta(days=10 if rid in (3, 5) else 60)).isoformat(), now()))
    # 稼働（在宅・外泊）・記録・シフト・勤怠を過去7日分
    for n in range(7, 0, -1):
        day = d(n)
        for rid in range(1, 6):
            status = "外泊" if (rid == 4 and n in (3, 4)) else "在宅"
            conn.execute("INSERT INTO occupancy(facility_id,resident_id,date,status) VALUES(1,?,?,?)", (rid, day, status))
            if status != "在宅":
                continue
            # わざと一部の記録を抜いて、チェック機能で見つかるようにしている
            if not (rid == 3 and n == 2):
                conn.execute("INSERT INTO records(facility_id,resident_id,date,time,type,data_json,text,status,created_by,created_at)"
                             " VALUES(1,?,?,'07:30','vital',?,?,'approved',3,?)",
                             (rid, day, json.dumps({"temp": "36.5", "bp_high": "118", "bp_low": "76", "pulse": "72"}),
                              "体温36.5℃、血圧118/76mmHg、脈拍72回/分。", now()))
            if not (rid == 5 and n == 1):
                conn.execute("INSERT INTO records(facility_id,resident_id,date,time,type,data_json,text,status,created_by,created_at)"
                             " VALUES(1,?,?,'08:00','med',?,?,?,4,?)",
                             (rid, day, json.dumps({"timing": ["朝"], "result": "飲んだ"}), "朝の薬を飲んだ。",
                              "submitted" if n == 1 else "approved", now()))
            if not (rid == 2 and n == 1):
                conn.execute("INSERT INTO records(facility_id,resident_id,date,time,type,data_json,text,status,created_by,created_at)"
                             " VALUES(1,?,?,'20:00','case',?,?,?,3,?)",
                             (rid, day, json.dumps({"mood": "おだやか"}), "おだやかに過ごされていた。",
                              "submitted" if n == 1 else "approved", now()))
        for uid, (st, en) in {3: ("09:00", "18:00"), 4: ("17:00", "09:00")}.items():
            conn.execute("INSERT INTO shifts(facility_id,user_id,date,start,end) VALUES(1,?,?,?,?)", (uid, day, st, en))
            if uid == 4 and n == 2:
                continue  # 打刻漏れ
            cin = "09:40" if (uid == 3 and n == 3) else st
            conn.execute("INSERT INTO attendance(facility_id,user_id,date,clock_in,clock_out) VALUES(1,?,?,?,?)",
                         (uid, day, cin, en))
    conn.execute("INSERT INTO records(facility_id,resident_id,date,time,type,data_json,memo,text,handover,status,created_by,created_at)"
                 " VALUES(1,3,?,'22:10','handover','{\"priority\":\"大事\"}',?,?,1,'submitted',4,?)",
                 (d(1), "夜中に何度か起きて不安そうだった", "夜中に何度か起きて不安そうだった。", now()))
    incidents = [
        (5, d(30), "14:00", "事故", "転倒", "廊下", "廊下で足がもつれて転倒。右ひざに擦り傷。", "床が濡れていた",
         "消毒し、看護師へ報告", "床が濡れたらすぐ拭く。歩行時は見守る。"),
        (1, d(20), "08:10", "ヒヤリハット", "服薬", "食堂", "朝の薬を別の利用者に渡しそうになった。", "名前の確認をしなかった",
         "渡す前に気づいた", "渡す前に名前と日付を声に出して確認する。"),
        (5, d(10), "19:30", "ヒヤリハット", "転倒", "浴室", "浴室でよろけたが職員が支えた。", "床がすべりやすい",
         "けがなし", "すべり止めマットを置く。"),
        (3, d(5), "02:00", "ヒヤリハット", "無断外出", "玄関", "夜中に玄関を開けようとしていた。", "不安で家に帰りたくなった",
         "声かけして居室へ戻った", "夜間の巡回を増やす。"),
    ]
    for r in incidents:
        conn.execute("INSERT INTO incidents(facility_id,resident_id,date,time,kind,category,place,description,cause,"
                     "action_taken,prevention,status,created_by,created_at) VALUES(1,?,?,?,?,?,?,?,?,?,?,'approved',3,?)",
                     (*r, now()))
    items = [("服薬", "朝・昼・夕・寝る前の服薬確認"), ("服薬", "薬の残数チェック"),
             ("感染症対策", "手すり・ドアノブの消毒"), ("感染症対策", "職員の検温"),
             ("防災", "非常口・避難経路に物がないか確認"), ("防災", "火の元・ガス栓の確認（夜）"),
             ("事故防止", "浴室・廊下の床が濡れていないか確認"), ("事故防止", "夜間巡回（2時間ごと）")]
    for cat, name in items:
        conn.execute("INSERT INTO checklist_items(facility_id,category,name) VALUES(1,?,?)", (cat, name))
    conn.execute("INSERT INTO deadlines(facility_id,title,due_date,assignee_id) VALUES(1,'避難訓練の実施報告',?,1)",
                 ((today + datetime.timedelta(days=3)).isoformat(),))
    conn.execute("INSERT INTO deadlines(facility_id,title,due_date,assignee_id) VALUES(1,'国保連 請求データ提出',?,1)",
                 ((today + datetime.timedelta(days=6)).isoformat(),))
    conn.commit()
