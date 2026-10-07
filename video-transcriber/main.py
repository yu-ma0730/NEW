"""ブラウザから使える Web UI（FastAPI）。

起動: uvicorn main:app --reload  →  http://localhost:8000
文字起こしは時間がかかるため、ジョブとしてバックグラウンドで実行し、画面からポーリングする。
"""

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import transcriber

BASE_DIR = Path(__file__).parent
app = FastAPI(title="Video Transcriber")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

jobs: dict[str, dict] = {}
# Whisper は CPU/メモリを大きく使うので同時実行は 1 件に制限する
_worker_lock = threading.Lock()


class JobRequest(BaseModel):
    url: str
    language: str | None = None
    model: str = "small"
    use_subtitles: bool = True
    max_videos: int | None = 5


def _run(job_id: str, req: JobRequest) -> None:
    job = jobs[job_id]
    log = lambda msg: job["logs"].append(msg)
    with _worker_lock:
        job["status"] = "running"
        try:
            results = transcriber.transcribe_page(
                req.url,
                max_videos=req.max_videos,
                language=req.language or None,
                model_size=req.model,
                use_subtitles=req.use_subtitles,
                log=log,
            )
            job["results"] = results
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = str(e)


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/jobs")
def create_job(req: JobRequest):
    if not req.url.startswith(("http://", "https://")):
        raise HTTPException(400, "http(s) の URL を入力してください")
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "queued", "logs": [], "results": [], "error": None}
    threading.Thread(target=_run, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "ジョブが見つかりません")
    return {
        "status": job["status"],
        "logs": job["logs"][-200:],
        "error": job["error"],
        "results": [
            {"title": t.title, "url": t.source_url, "language": t.language,
             "method": t.method, "text": transcriber.to_txt(t, timestamps=True)}
            for t in job["results"]
        ],
    }


@app.get("/api/jobs/{job_id}/{index}.{fmt}")
def download(job_id: str, index: int, fmt: str):
    job = jobs.get(job_id)
    if not job or index >= len(job["results"]) or fmt not in ("txt", "srt", "vtt", "json"):
        raise HTTPException(404)
    body = transcriber.render(job["results"][index], fmt)
    return PlainTextResponse(
        body, headers={"Content-Disposition": f'attachment; filename="transcript_{index + 1}.{fmt}"'}
    )
