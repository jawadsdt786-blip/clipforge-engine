"""ClipForge public beta: visitor uploads and permitted YouTube links.

Requires ffmpeg/ffprobe and yt-dlp. Project access is protected with bearer
capability tokens, but this remains a limited public beta rather than a
production SaaS: accounts, billing, queues, cloud storage, and stronger abuse
prevention are not included.
"""
from __future__ import annotations

import json
import hashlib
import secrets
from collections import defaultdict, deque
import math
import os
import re
import shutil
import sys
import importlib.util
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
STORAGE = Path(os.environ.get("CLIPFORGE_STORAGE_DIR", str(ROOT / "storage"))).resolve()
MEDIA = STORAGE / "media"
DATA = STORAGE / "data"
STATIC = ROOT / "static"
ASSETS = ROOT / "assets"
for path in (MEDIA, DATA, STATIC, ASSETS):
    path.mkdir(exist_ok=True, parents=True)
DB = DATA / "projects.json"
LOCK = threading.RLock()
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "150")) * 1024 * 1024
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_IMPORT_HOSTS = {"youtube.com", "youtu.be"}
MAX_ACTIVE_JOBS = int(os.environ.get("MAX_ACTIVE_JOBS", "2"))
MAX_JOBS_HOURLY = int(os.environ.get("MAX_JOBS_HOURLY", "8"))
PROJECT_TTL_SECONDS = int(os.environ.get("PROJECT_TTL_HOURS", "24")) * 3600
ACTIVE_JOBS: set[str] = set()
RECENT_JOBS: dict[str, deque[float]] = defaultdict(deque)
LAST_SWEEP = 0.0
app = FastAPI(title="ClipForge Video Studio", version="2.0")
# CORS only permits approved frontends. This is NOT authentication or rate-limiting.
allowed_origins = [x.strip().rstrip("/") for x in os.environ.get(
    "CLIPFORGE_CORS_ORIGINS", "https://jawadsdt786-blip.github.io,http://localhost:8000,http://127.0.0.1:8000"
).split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins,
                   allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type", "Accept"])

app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith('/api/') else "public, max-age=60"
    return response

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def project_for_user(pid: str, token: str | None) -> dict:
    project = get_project(pid)
    good = project.get("token_hash")
    if not good or not token or not secrets.compare_digest(good, token_hash(token)):
        raise HTTPException(status_code=403, detail="Project access denied. Open this project from the browser where you created it.")
    if project.get("expires", 0) < time.time():
        raise HTTPException(status_code=410, detail="Project expired; please create a new one.")
    return project

def public_project(project: dict) -> dict:
    return {k: v for k,v in project.items() if k not in {"token_hash", "owner_ip"}}

def send_created(project: dict, token: str) -> dict:
    return {**public_project(project), "access_token": token}

def reserve_job(request: Request) -> str:
    global LAST_SWEEP
    client = request.client.host if request.client else "unknown"
    now = time.time()
    with LOCK:
        if len(ACTIVE_JOBS) >= MAX_ACTIVE_JOBS:
            raise HTTPException(429, "Video server is busy. Try again after another job finishes.")
        logs = RECENT_JOBS[client]
        while logs and logs[0] < now - 3600:
            logs.popleft()
        if len(logs) >= MAX_JOBS_HOURLY:
            raise HTTPException(429, "Hourly clip limit reached. Please return later.")
        logs.append(now)
        job_id = uuid.uuid4().hex[:12]
        ACTIVE_JOBS.add(job_id)
        if now > LAST_SWEEP + 300:
            LAST_SWEEP = now
            expired = [p['id'] for p in read_db().values() if p.get('expires', now+1) < now and p.get('id') not in ACTIVE_JOBS]
            if expired:
                db = read_db()
                for pid in expired:
                    db.pop(pid, None)
                    shutil.rmtree(MEDIA / pid, ignore_errors=True)
                write_db(db)
        return job_id

def release_job(job_id: str) -> None:
    with LOCK:
        ACTIVE_JOBS.discard(job_id)

def complete_job(task, job_id: str, *args) -> None:
    try:
        task(*args)
    finally:
        release_job(job_id)

def run_cmd(args: list[str], *, timeout: int = 900, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=timeout)


def read_db() -> dict[str, dict[str, Any]]:
    if not DB.exists():
        return {}
    try:
        return json.loads(DB.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_db(db: dict) -> None:
    temp = DB.with_suffix(".tmp")
    temp.write_text(json.dumps(db, indent=2), encoding="utf-8")
    temp.replace(DB)


def store_project(project: dict) -> None:
    with LOCK:
        db = read_db()
        db[project["id"]] = project
        write_db(db)


def update_project(project_id: str, **fields: Any) -> None:
    with LOCK:
        db = read_db()
        if project_id not in db:
            return
        db[project_id].update(fields)
        write_db(db)


def get_project(project_id: str) -> dict:
    with LOCK:
        project = read_db().get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def ffprobe(path: Path) -> dict:
    result = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], timeout=30)
    info = json.loads(result.stdout)
    duration = float(info.get("format", {}).get("duration") or 0)
    video = next((stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"), None)
    if duration <= 0 or video is None:
        raise ValueError("Could not detect a valid video stream")
    return {"duration": round(duration, 2), "width": video.get("width"), "height": video.get("height"), "has_audio": any(s.get("codec_type") == "audio" for s in info["streams"])}


def get_audio_energy(path: Path, duration: float) -> np.ndarray:
    """Quick per-second RMS of source audio, used ONLY for heuristic highlights."""
    if duration > 7200:
        return np.zeros(math.ceil(duration), dtype=np.float32)
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "4000", "-f", "f32le", "pipe:1"]
    try:
        data = subprocess.run(cmd, capture_output=True, timeout=180, check=True).stdout
        audio = np.frombuffer(data, dtype=np.float32)
        if audio.size == 0:
            return np.zeros(math.ceil(duration), dtype=np.float32)
        n = math.ceil(audio.size / 4000)
        energy = [float(np.sqrt(np.mean(audio[i * 4000:(i + 1) * 4000] ** 2))) if len(audio[i * 4000:(i + 1) * 4000]) else 0 for i in range(n)]
        return np.asarray(energy, dtype=np.float32)
    except (subprocess.SubprocessError, OSError):
        return np.zeros(math.ceil(duration), dtype=np.float32)


def find_moments(path: Path, duration: float, count: int, requested_length: int) -> list[dict]:
    """Diversified windows rated using speech/audio energy. Not an AI virality model."""
    length = max(4, min(float(requested_length), duration))
    if duration <= length + 1:
        return [{"start": 0.0, "end": round(duration, 2), "moment_score": None}]
    energy = get_audio_energy(path, duration)
    window = int(math.ceil(length))
    starts = np.arange(0, max(1, int(duration - length) + 1), max(1, int(length / 5)))
    # A window is better with consistent speech rather than pure loudness peaks.
    scored = []
    p80 = max(float(np.percentile(energy, 80)), 0.0001) if energy.size else 0.0001
    for start in starts:
        part = energy[int(start): min(len(energy), int(start + window))]
        if len(part):
            speech_ratio = float(np.mean(part > max(p80 * .2, 0.003)))
            energy_level = float(np.clip(np.mean(part) / p80, 0, 1))
            variability = float(np.clip(np.std(part) / p80, 0, 1))
            score = speech_ratio * .55 + energy_level * .30 + variability * .15
        else:
            score = 0.5
        scored.append((score, float(start)))
    scored.sort(key=lambda row: row[0], reverse=True)
    selected = []
    for score, start in scored:
        if all(abs(start - item["start"]) >= length * .75 for item in selected):
            selected.append({"start": round(start, 2), "end": round(min(duration, start + length), 2), "moment_score": int(round(50 + 45 * score))})
        if len(selected) >= count:
            break
    # Fill with distinct points if windows did not suffice.
    for start in np.linspace(0, max(0, duration - length), count):
        if len(selected) >= count:
            break
        if all(abs(start - item["start"]) > length * .6 for item in selected):
            selected.append({"start": round(float(start), 2), "end": round(float(start + length), 2), "moment_score": None})
    return selected


def srt_timestamp(seconds: float) -> str:
    milliseconds = int(round(max(seconds, 0) * 1000))
    hh, remain = divmod(milliseconds, 3600000)
    mm, remain = divmod(remain, 60000)
    ss, ms = divmod(remain, 1000)
    return f"{hh:02}:{mm:02}:{ss:02},{ms:03}"


def generate_srt(path: Path, start: float, end: float, destination: Path) -> bool:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return False
    try:
        model_name = os.environ.get("WHISPER_MODEL", "tiny")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(path), beam_size=1, vad_filter=True)
        entries = []
        for segment in segments:
            if segment.end <= start or segment.start >= end:
                continue
            s, e = max(start, segment.start) - start, min(end, segment.end) - start
            if e - s <= .02:
                continue
            entries.append(f"{len(entries) + 1}\n{srt_timestamp(s)} --> {srt_timestamp(e)}\n{segment.text.strip()}\n")
        if entries:
            destination.write_text("\n".join(entries), encoding="utf-8")
            return True
    except Exception as exc:
        print("Subtitle generation skipped:", str(exc))
    return False


def render_clip(source: Path, dest: Path, start: float, end: float, aspect: str, caption_text: str = "", subtitle_file: Path | None = None):
    size = {"9:16": (720, 1280), "1:1": (720, 720), "16:9": (1280, 720)}.get(aspect, (720, 1280))
    w, h = size
    filters = [f"scale={w}:{h}:force_original_aspect_ratio=increase", f"crop={w}:{h}", "setsar=1"]
    if subtitle_file and subtitle_file.exists():
        # ffmpeg subtitles filter uses filename escaping for punctuation.
        file_path = str(subtitle_file).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        filters.append(f"subtitles='{file_path}':force_style='FontName=DejaVu Sans,FontSize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=3,Alignment=2,MarginV=65'")
    if caption_text.strip():
        # Text is stored on disk rather than interpolated into ffmpeg expressions.
        textfile = dest.with_suffix(".txt")
        textfile.write_text(caption_text[:140], encoding="utf-8")
        safe_file = str(textfile).replace(":", "\\:").replace("'", "\\'")
        fonts = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf"]
        font_file = next((f for f in fonts if Path(f).exists()), None)
        safe_font = font_file.replace(":", "\\:") if font_file else None
        font_option = f"fontfile='{safe_font}'" if safe_font else "font=Sans"
        filters.append(f"drawtext={font_option}:textfile='{safe_file}':fontcolor=white:fontsize=38:borderw=4:bordercolor=black:x=(w-text_w)/2:y=h*0.78-text_h/2")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(max(0, start)), "-i", str(source), "-t", str(max(.3, end-start)), "-vf", ",".join(filters), "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "27", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)]
    result = run_cmd(command, timeout=1800, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or "Video render failed")[-1400:])


def process_project(pid: str) -> None:
    project = get_project(pid)
    try:
        update_project(pid, status="processing", progress=5, error=None)
        source = MEDIA / pid / project["source_file"]
        metadata = ffprobe(source)
        update_project(pid, duration=metadata["duration"], source_width=metadata["width"], source_height=metadata["height"], progress=13)
        moments = find_moments(source, metadata["duration"], project["settings"]["count"], project["settings"]["length"])
        directory = MEDIA / pid
        clips = []
        for i, moment in enumerate(moments):
            clip_id = uuid.uuid4().hex[:12]
            clip_filename = f"clip_{i+1}_{clip_id}.mp4"
            subs = directory / f"captions_{clip_id}.srt"
            has_captions = False
            if project["settings"].get("captions"):
                has_captions = generate_srt(source, moment["start"], moment["end"], subs)
            render_clip(source, directory / clip_filename, moment["start"], moment["end"], project["settings"]["aspect"], subtitle_file=subs if has_captions else None)
            clips.append({"id": clip_id, "name": f"Highlight {i+1:02}", "start": moment["start"], "end": moment["end"], "moment_score": moment["moment_score"], "url": f"/api/projects/{pid}/files/{clip_filename}", "captions": has_captions})
            update_project(pid, clips=clips, progress=round(15 + 84 * (i+1) / len(moments)))
        update_project(pid, status="done", progress=100, clips=clips)
    except Exception as exc:
        update_project(pid, status="error", error=str(exc)[:500])
        print("Project error:", repr(exc))


def create_project(source_file: str, name: str, settings: dict, pid: str | None = None) -> dict:
    pid = pid or uuid.uuid4().hex[:12]
    token = secrets.token_urlsafe(32)
    project = {"id": pid, "name": name[:120], "source_file": source_file, "created": int(time.time()), "expires": int(time.time())+PROJECT_TTL_SECONDS, "status": "queued", "progress": 0, "settings": settings, "duration": 0, "clips": [], "error": None, "token_hash": token_hash(token)}
    store_project(project)
    return send_created(project, token)


def normalize_settings(count: int, length: int, aspect: str, captions: bool) -> dict:
    if aspect not in {"9:16", "1:1", "16:9"}:
        raise HTTPException(400, "Unsupported aspect ratio")
    return {"count": min(max(count, 1), 5), "length": min(max(length, 5), 45), "aspect": aspect, "captions": captions}


@app.get("/")
def homepage():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")), "ffmpeg": bool(shutil.which("ffmpeg")), "link_import": bool(importlib.util.find_spec("yt_dlp")), "automatic_captions": bool(_has_whisper())}


def _has_whisper() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


@app.get("/api/projects")
def list_projects():
    with LOCK:
        raise HTTPException(status_code=403, detail="Public project listings are disabled for visitor privacy.")


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str, x_project_token: str | None = Header(default=None)):
    return public_project(project_for_user(project_id, x_project_token))


@app.post("/api/upload", status_code=201)
async def upload(background_tasks: BackgroundTasks, request: Request, file: UploadFile = File(...), count: int = Form(3), length: int = Form(30), aspect: str = Form("9:16"), captions: bool = Form(False)):
    settings = normalize_settings(count, length, aspect, captions)
    job_id = reserve_job(request)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        release_job(job_id)
        raise HTTPException(status_code=400, detail="Please upload MP4, MOV, MKV, WebM, AVI or M4V video")
    pid = job_id
    folder = MEDIA / pid
    folder.mkdir(parents=True)
    name = "source" + suffix
    target = folder / name
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024*1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"File too large. Limit: {MAX_UPLOAD_BYTES // (1024*1024)} MB")
                out.write(chunk)
        meta = ffprobe(target)
        if meta["duration"] > 3600:
            raise HTTPException(413, "Video too long for public beta (max 60 minutes)")
    except HTTPException:
        release_job(job_id)
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception:
        release_job(job_id)
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(400, "Video could not be read. Try another format")
    finally:
        await file.close()
    project = create_project(name, file.filename or "Untitled video", settings, pid)
    background_tasks.add_task(complete_job, process_project, job_id, pid)
    return project


class ImportRequest(BaseModel):
    url: str
    count: int = 3
    length: int = 30
    aspect: str = "9:16"
    captions: bool = False


def download_from_url(pid: str, link: str) -> None:
    project = get_project(pid)
    try:
        folder = MEDIA / pid
        folder.mkdir(exist_ok=True)
        update_project(pid, status="importing", progress=3)
        command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                   "--no-progress", "--no-warnings", "--socket-timeout", "30", "--retries", "2", "--max-filesize",
                   f"{MAX_UPLOAD_BYTES // (1024*1024)}M", "--match-filters", "!is_live & duration <= 3600",
                   "--merge-output-format", "mp4", "-f", "bv*+ba/b",
                   "-o", str(folder / "source.%(ext)s"), link]
        result = run_cmd(command, timeout=900, check=False)
        if result.returncode:
            raise RuntimeError("Import failed. The video may be live, private, restricted or blocked by YouTube. Try a regular public video you are authorized to use, or upload your own file.")
        file = next((p for p in folder.glob("source.*") if p.suffix.lower() in VIDEO_SUFFIXES), None)
        if not file or file.stat().st_size > MAX_UPLOAD_BYTES:
            raise RuntimeError("The imported video is missing, unsupported or too large")
        meta = ffprobe(file)
        if meta["duration"] > 3600:
            raise RuntimeError("Imported video is longer than 60-minute public beta limit")
        update_project(pid, source_file=file.name)
        process_project(pid)
    except Exception as exc:
        update_project(pid, status="error", error=str(exc)[:500])
        # Remove partial downloads to avoid filling the disk.
        shutil.rmtree(MEDIA / pid, ignore_errors=True)


@app.post("/api/from-url", status_code=201)
def import_url(request: ImportRequest, background_tasks: BackgroundTasks, http_request: Request):
    if not importlib.util.find_spec("yt_dlp"):
        raise HTTPException(503, "URL import needs yt-dlp. Install it with: python -m pip install -U yt-dlp")
    parsed = urlparse(request.url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host == domain or host.endswith("."+domain) for domain in ALLOWED_IMPORT_HOSTS):
        raise HTTPException(400, "Please use a public YouTube video link you have permission to edit")
    settings = normalize_settings(request.count, request.length, request.aspect, request.captions)
    pid = reserve_job(http_request)
    project = create_project("", "Imported video • " + host, settings, pid)
    background_tasks.add_task(complete_job, download_from_url, pid, pid, request.url.strip())
    return project


@app.post("/api/demo", status_code=201)
def demo(background_tasks: BackgroundTasks, http_request: Request, count: int = 3, length: int = 15, aspect: str = "9:16"):
    source = ASSETS / "demo.mp4"
    if not source.exists():
        raise HTTPException(404, "Demo footage is not installed")
    settings = normalize_settings(count, length, aspect, False)
    pid = reserve_job(http_request)
    folder = MEDIA / pid
    folder.mkdir(exist_ok=True)
    shutil.copyfile(source, folder / "source.mp4")
    project = create_project("source.mp4", "Sample content creation demo", settings, pid)
    background_tasks.add_task(complete_job, process_project, pid, pid)
    return project


class EditRequest(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    aspect: str = "9:16"
    caption_text: str = Field(default="", max_length=140)


@app.post("/api/projects/{project_id}/clips/{clip_id}/edit")
def edit_clip(project_id: str, clip_id: str, request: EditRequest, x_project_token: str | None = Header(default=None)):
    project = project_for_user(project_id, x_project_token)
    if project.get("status") != "done":
        raise HTTPException(400, "Finish processing the project before editing")
    settings = normalize_settings(1, 30, request.aspect, False)
    if request.end <= request.start or request.end > project["duration"] + .2:
        raise HTTPException(400, "Invalid trim timestamps")
    clip = next((c for c in project["clips"] if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(404, "Clip not found")
    folder = MEDIA / project_id
    output = f"edited_{uuid.uuid4().hex[:12]}.mp4"
    try:
        render_clip(folder / project["source_file"], folder / output, request.start, request.end, settings["aspect"], request.caption_text)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(500, f"Render failed: {str(exc)[-300:]}")
    with LOCK:
        db = read_db()
        latest = db[project_id]
        for item in latest["clips"]:
            if item["id"] == clip_id:
                item.update({"start": request.start, "end": request.end, "url": f"/api/projects/{project_id}/files/{output}", "edited": True, "captions": bool(request.caption_text)})
                clip = item
                break
        write_db(db)
    return clip


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, x_project_token: str | None = Header(default=None)):
    _ = project_for_user(project_id, x_project_token)
    with LOCK:
        db = read_db()
        db.pop(project_id, None)
        write_db(db)
    shutil.rmtree(MEDIA / project_id, ignore_errors=True)
    return {"ok": True}


@app.get("/api/info")
def service_info():
    return {"product": "ClipForge", "edition": "Public beta", "billing_active": False,
            "highlight_method": "audio-heuristic", "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024)}

@app.get("/api/projects/{project_id}/clips/{clip_id}/download")
def download_clip(project_id: str, clip_id: str, token: str = Query(default="")):
    project = project_for_user(project_id, token)
    clip = next((c for c in project.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(404, "Clip not found")
    name = Path(clip["url"]).name
    target = MEDIA / project_id / name
    if not target.is_file():
        raise HTTPException(404, "Clip file not found")
    return FileResponse(target, media_type="video/mp4", filename=f"clipforge-{clip_id}.mp4")

@app.get("/api/projects/{project_id}/files/{filename}")
def private_clip_file(project_id: str, filename: str, token: str = Query(default="")):
    project = project_for_user(project_id, token)
    if not re.fullmatch(r"(?:clip|edited)_[A-Za-z0-9_-]+\.mp4", filename):
        raise HTTPException(404, "Video not found")
    if not any(Path(clip.get("url", "")).name == filename for clip in project.get("clips", [])):
        raise HTTPException(404, "Video not found")
    path = MEDIA / project_id / filename
    if not path.is_file():
        raise HTTPException(404, "Video not found")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control":"private, no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
