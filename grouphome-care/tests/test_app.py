"""自動テスト：python3 -m unittest discover -s tests -v

本物のサーバーを一時的なデータベースで起動し、画面と同じAPIを呼んで確かめます。
"""
import datetime
import http.cookiejar
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402
from app import ai  # noqa: E402

TODAY = datetime.date.today()


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None, csrf=True):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data:
            req.add_header("Content-Type", "application/json")
        if csrf:
            req.add_header("X-Requested-With", "carekiroku")
        try:
            with self.opener.open(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if "json" in r.headers["Content-Type"] else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def get(self, p):
        return self.call("GET", p)

    def post(self, p, b=None, **kw):
        return self.call("POST", p, b or {}, **kw)

    def login(self, lid):
        s, _ = self.post("/api/login", {"login_id": lid, "password": "demo1234"})
        assert s == 200, s
        return self


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = server.make_server(os.path.join(cls.tmp.name, "t.db"), port=0, quiet=True)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def c(self, who=None):
        cl = Client(self.base)
        return cl.login(who) if who else cl

    # --- 認証・権限 ---
    def test_login_required_and_wrong_password(self):
        c = self.c()
        self.assertEqual(c.get("/api/records")[0], 401)
        self.assertEqual(c.post("/api/login", {"login_id": "staff1", "password": "x"})[0], 401)

    def test_csrf_header_required(self):
        c = self.c("staff1")
        self.assertEqual(c.post("/api/records", {"type": "case"}, csrf=False)[0], 403)

    def test_staff_cannot_approve_or_export(self):
        c = self.c("staff1")
        self.assertEqual(c.post("/api/approve", {"target": "records", "id": 1, "action": "approve"})[0], 403)
        self.assertEqual(c.get("/api/export/records.csv")[0], 403)
        self.assertEqual(c.get("/api/audit")[0], 403)

    # --- AI原案：入力にない事実を足さない ---
    def test_draft_uses_only_input(self):
        r = ai.draft("vital", {"temp": "37.8", "bp_high": "120"}, "えーっと、少し咳が出ていた")
        self.assertIn("体温37.8℃", r["text"])
        self.assertNotIn("血圧", r["text"])  # 下の血圧がないので文にしない
        self.assertIn("少し咳が出ていた。", r["text"])
        self.assertNotIn("えーっと", r["text"])
        joined = " ".join(r["checks"])
        self.assertIn("37.5℃以上", joined)
        self.assertIn("片方だけ", joined)
        self.assertIn("体調不良", joined)

    def test_draft_suggests_incident_and_missing(self):
        r = ai.draft("case", {}, "廊下で転んだ")
        self.assertTrue(r["suggest_incident"])
        self.assertTrue(r["checks"][0].startswith("まだ入力されていない項目"))

    # --- 記録 → 承認 → 履歴 ---
    def test_record_flow_with_approval_and_audit(self):
        staff, boss = self.c("staff1"), self.c("sabikan")
        s, r = staff.post("/api/records", {"resident_id": 1, "type": "case", "fields": {"mood": "元気"}, "text": "元気だった。", "handover": True})
        self.assertEqual(s, 200)
        rid = r["id"]
        s, r = boss.post("/api/approve", {"target": "records", "id": rid, "action": "return"})
        self.assertEqual(s, 400)  # 理由なしの差し戻しはできない
        boss.post("/api/approve", {"target": "records", "id": rid, "action": "return", "comment": "時刻を書いて"})
        self.assertEqual(staff.get(f"/api/records/{rid}")[1]["status"], "returned")
        self.assertTrue(any(x["id"] == rid for x in staff.get("/api/mine")[1]))
        self.assertEqual(staff.post(f"/api/records/{rid}", {"text": "20時、元気だった。"})[0], 200)
        boss.post("/api/approve", {"target": "records", "ids": [rid], "action": "approve"})
        rec = staff.get(f"/api/records/{rid}")[1]
        self.assertEqual(rec["status"], "approved")
        self.assertEqual(staff.post(f"/api/records/{rid}", {"text": "改ざん"})[0], 403)  # 承認後は職員は直せない
        actions = [a["action"] for a in boss.get(f"/api/audit?target=records&target_id={rid}")[1]]
        self.assertEqual(actions, ["承認", "記録を修正", "差し戻し", "記録を作成"])
        groups = staff.get("/api/handovers?days=1")[1]["groups"]
        self.assertTrue(any(i["id"] == rid for g in groups for i in g["items"]))

    def test_record_validation(self):
        c = self.c("staff2")
        self.assertEqual(c.post("/api/records", {"resident_id": 1, "type": "case", "text": ""})[0], 400)
        self.assertEqual(c.post("/api/records", {"type": "case", "text": "x"})[0], 400)  # 利用者なし
        self.assertEqual(c.post("/api/records", {"type": "diary", "text": "特に変わりなし。"})[0], 200)  # 業務日誌は利用者なしOK
        self.assertEqual(c.post("/api/records", {"resident_id": 1, "type": "zzz", "text": "x"})[0], 400)

    # --- 請求前チェック ---
    def test_checks_find_seeded_problems_and_recheck(self):
        boss = self.c("manager")
        month = TODAY.strftime("%Y-%m")
        res = boss.get(f"/api/checks?month={month}")[1]
        msgs = [i["message"] for i in res["issues"]]
        two_days = (TODAY - datetime.timedelta(days=2)).isoformat()
        if two_days[:7] == month:
            self.assertTrue(any("鈴木 けん" in m and "バイタル" in m for m in msgs))
            self.assertTrue(any("打刻がありません" in m for m in msgs))
        # 記録を足して再チェックすると、その問題が消える
        if two_days[:7] == month:
            boss.post("/api/records", {"resident_id": 3, "type": "vital", "date": two_days, "fields": {"temp": "36.4"}, "text": "体温36.4℃。"})
            msgs2 = [i["message"] for i in boss.get(f"/api/checks?month={month}")[1]["issues"] if i["date"] == two_days]
            self.assertFalse(any("鈴木 けん" in m and "バイタル" in m for m in msgs2))

    def test_occupancy_conflict_detected(self):
        boss = self.c("manager")
        day = (TODAY - datetime.timedelta(days=1)).isoformat()
        boss.post("/api/occupancy", {"resident_id": 1, "date": day, "status": "入院"})
        res = boss.get(f"/api/checks?month={day[:7]}")[1]
        self.assertTrue(any("入院" in i["message"] and i["date"] == day for i in res["issues"]))
        boss.post("/api/occupancy", {"resident_id": 1, "date": day, "status": "在宅"})

    def test_csv_export_has_bom(self):
        boss = self.c("manager")
        s, raw = boss.get("/api/export/occupancy.csv")
        self.assertEqual(s, 200)
        self.assertTrue(raw.startswith("﻿".encode()))
        self.assertIn("在宅日数".encode(), raw)

    # --- 事故・ヒヤリ ---
    def test_incident_similar_and_report(self):
        c = self.c("staff1")
        sim = c.get("/api/incidents/similar?q=" + urllib.request.quote("浴室で転倒しそうになった") + "&category=" + urllib.request.quote("転倒"))[1]
        self.assertTrue(sim and sim[0]["category"] == "転倒")
        s, r = c.post("/api/incidents", {"kind": "事故", "category": "転倒", "description": "居室で転倒", "resident_id": 5})
        self.assertEqual(s, 200)
        doc = c.post("/api/documents/draft", {"kind": "incident_report", "params": {"incident_id": r["id"]}})[1]
        self.assertIn("原因", doc["missing"])  # 空欄は勝手に埋めず「もれ」として返す
        self.assertEqual(c.post("/api/documents", {"kind": "incident_report", "title": doc["title"], "sections": doc["sections"]})[0], 400)
        stats = c.get("/api/incidents/stats")[1]
        self.assertGreaterEqual(stats["total"], 4)

    # --- チェックリスト・通知 ---
    def test_checklist_and_notifications(self):
        c = self.c("staff2")
        items = c.get("/api/checklist")[1]
        before = [n for n in c.get("/api/notifications")[1] if n["link"] == "checklist"]
        self.assertTrue(before)
        for i in items:
            c.post("/api/checklist/done", {"item_id": i["id"]})
        after = [n for n in c.get("/api/notifications")[1] if n["link"] == "checklist"]
        self.assertFalse(after)
        for i in items:
            c.post("/api/checklist/done", {"item_id": i["id"], "done": False})

    def test_static_and_security_headers(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
            self.assertIn("ケアきろく", r.read().decode())
        try:
            urllib.request.urlopen(self.base + "/../server.py")
            self.fail("should not serve")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main()
