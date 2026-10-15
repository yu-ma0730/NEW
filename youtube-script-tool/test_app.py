from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

BASE = {
    "theme": "お金が貯まる人の習慣",
    "genre": "business",
    "minutes": 10,
    "teller": {"preset": "marisa"},
    "listener": {"preset": "reimu"},
}


def test_options():
    data = client.get("/api/options").json()
    assert any(c["id"] == "zundamon" for c in data["characters"])
    assert any(g["id"] == "sukatto" for g in data["genres"])


def test_build_dialogue():
    data = client.post("/api/build", json=BASE).json()
    assert data["target_chars"] == 3300
    assert data["outline"][0]["title"] == "つかみ"
    assert data["outline"][-1]["end"] == "10:00"
    assert "魔理沙：" in data["template"] and "霊夢：" in data["template"]
    assert "受け手：霊夢" in data["prompt"]


def test_build_solo_with_points():
    body = {**BASE, "listener": None, "points": ["先取り貯金", "固定費"]}
    data = client.post("/api/build", json=body).json()
    assert data["target_chars"] == 3000
    titles = [s["title"] for s in data["outline"]]
    assert "本題：先取り貯金" in titles and "本題：固定費" in titles
    assert "霊夢" not in data["template"]


def test_client_mode_without_ai_permission_hides_prompt():
    body = {**BASE, "mode": "client", "char_count": 5000, "ng_words": "絶対"}
    data = client.post("/api/build", json=body).json()
    assert data["target_chars"] == 5000
    assert data["prompt"] is None
    assert client.post("/api/generate", json=body).status_code == 403


def test_client_mode_with_ai_permission():
    body = {**BASE, "mode": "client", "ai_allowed": True, "client_rules": "冒頭はどうも〇〇です", "ng_words": "絶対"}
    prompt = client.post("/api/build", json=body).json()["prompt"]
    assert "クライアントからの指定" in prompt and "NGワード" in prompt


def test_story_structure():
    data = client.post("/api/build", json={**BASE, "genre": "sukatto"}).json()
    assert data["outline"][0]["title"] == "冒頭（結末のチラ見せ）"


def test_custom_character_name():
    body = {**BASE, "teller": {"preset": "custom", "name": "タロウ", "tone": "関西弁"}}
    assert "タロウ：" in client.post("/api/build", json=body).json()["template"]


def test_generate_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.post("/api/generate", json=BASE).status_code == 503


def test_validation():
    assert client.post("/api/build", json={**BASE, "theme": ""}).status_code == 422
