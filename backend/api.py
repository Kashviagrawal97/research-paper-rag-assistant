"""FastAPI server for the Research Paper Assistant.

Run from the project root:  python3 backend/app.py
(or from inside backend/:  python3 app.py)
Then open http://127.0.0.1:8000        API docs: http://127.0.0.1:8000/docs
"""
import os
import re
import shutil
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

import ingestion_pipeline
import retrieval_pipeline
from config import DATA_DIR, DB_DIR, FRONTEND_DIR, get_vectorstore
from fetch_papers import fetch_from_arxiv, fetch_from_semantic_scholar

MAX_UPLOADS = 8
MAX_UPLOAD_BYTES = 80 * 1024 * 1024  # 80 MB total
BUSY_STAGES = {"fetching", "reading", "embedding"}

# Single shared state: this app is meant for one local user.
state = {"stage": "idle", "message": "", "percent": 0, "papers": []}
lock = threading.Lock()


def set_state(**changes):
    with lock:
        state.update(changes)


def get_state():
    with lock:
        return dict(state)


def list_papers():
    os.makedirs(DATA_DIR, exist_ok=True)
    return sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf"))


def reset_library():
    """Delete all PDFs in the data folder and empty the vector DB."""
    for name in list_papers():
        os.remove(os.path.join(DATA_DIR, name))
    try:
        get_vectorstore().delete_collection()
    except Exception:
        pass


def safe_filename(name):
    """Keep only safe characters so an upload can't write outside data/."""
    name = os.path.basename(name.replace("\\", "/"))
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    return name


def claim_build(stage):
    """Atomically mark a build as started. Returns False if one is already running."""
    with lock:
        if state["stage"] in BUSY_STAGES:
            return False
        state.update(stage=stage, message="Starting", percent=0, papers=[])
        return True


# ---------- Request / response models ----------
class TopicRequest(BaseModel):
    topic: str = ""


class AskRequest(BaseModel):
    question: str = ""


class BuildStatus(BaseModel):
    stage: str
    message: str
    percent: int
    papers: list[str]


# ---------- App setup ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reuse a library that already exists on disk (e.g. built from the command line)
    try:
        if os.path.isdir(DB_DIR) and get_vectorstore().get(limit=1)["ids"]:
            set_state(stage="ready", message="Library is ready", percent=100, papers=list_papers())
    except Exception:
        pass
    yield


app = FastAPI(title="Research Paper Assistant", lifespan=lifespan)


# The frontend reads `data.error`, so return errors in that shape.
@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({"error": "That request was not valid. Check your input and try again."}, status_code=422)


# ---------- Background job ----------
def run_build(topic=None):
    """(Optionally) fetch papers, then ingest them. Runs after the response is sent."""
    try:
        if topic:
            set_state(stage="fetching", message=f"Searching for papers on \u201c{topic}\u201d", percent=0)
            for fetch, limit in ((fetch_from_semantic_scholar, 10), (fetch_from_arxiv, 5)):
                try:
                    fetch(topic, max_results=limit)
                except Exception as e:  # one source failing should not stop the other
                    print(f"Fetch step failed: {e}")
            if not list_papers():
                raise RuntimeError(
                    "No downloadable papers were found for this topic. "
                    "Try different keywords, or upload your own PDFs."
                )

        set_state(papers=list_papers())

        def progress(stage, message, percent):
            set_state(stage=stage, message=message, percent=percent)

        ingestion_pipeline.ingest(progress)
        set_state(stage="ready", message="Library is ready", percent=100, papers=list_papers())
    except Exception as e:
        set_state(stage="error", message=str(e), percent=0)


# ---------- API routes ----------
@app.get("/api/status", response_model=BuildStatus)
def status():
    return get_state()


@app.post("/api/build-from-topic")
def build_from_topic(req: TopicRequest, background: BackgroundTasks):
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(400, "Enter a topic to search for.")
    if not claim_build("fetching"):
        raise HTTPException(409, "A library is already being built. Wait for it to finish.")

    try:
        reset_library()
    except Exception as e:
        set_state(stage="error", message=f"Could not clear the old library: {e}")
        raise HTTPException(500, "Could not clear the old library.")

    background.add_task(run_build, topic)
    return {"ok": True}


@app.post("/api/build-from-upload")
def build_from_upload(background: BackgroundTasks, files: list[UploadFile] = File(default=[])):
    files = [f for f in files if f and f.filename]
    if not files:
        raise HTTPException(400, "Choose at least one PDF.")
    if len(files) > MAX_UPLOADS:
        raise HTTPException(400, f"Upload at most {MAX_UPLOADS} PDFs at a time.")
    if sum(f.size or 0 for f in files) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Those PDFs are too large. Keep the total under 80 MB.")

    for f in files:
        header = f.file.read(4)
        f.file.seek(0)
        if not f.filename.lower().endswith(".pdf") or header != b"%PDF":
            raise HTTPException(400, f"\u201c{f.filename}\u201d is not a valid PDF.")

    if not claim_build("reading"):
        raise HTTPException(409, "A library is already being built. Wait for it to finish.")

    try:
        reset_library()
        used = set()
        for i, f in enumerate(files):
            name = safe_filename(f.filename) or f"paper_{i + 1}.pdf"
            base, ext = os.path.splitext(name)
            n = 1
            while name in used:
                n += 1
                name = f"{base}_{n}{ext}"
            used.add(name)
            with open(os.path.join(DATA_DIR, name), "wb") as out:
                shutil.copyfileobj(f.file, out)
    except Exception as e:
        set_state(stage="error", message=f"Could not save the uploaded files: {e}")
        raise HTTPException(500, "Could not save the uploaded files.")

    set_state(papers=list_papers())
    background.add_task(run_build, None)
    return {"ok": True}


@app.post("/api/ask")
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Type a question first.")

    stage = get_state()["stage"]
    if stage in BUSY_STAGES:
        raise HTTPException(409, "The library is still being built.")
    if stage != "ready":
        raise HTTPException(400, "Build a library first.")

    try:
        return retrieval_pipeline.ask(question)
    except Exception as e:
        text = str(e)
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            raise HTTPException(429, "Gemini's rate limit was reached. Wait a minute and ask again.")
        raise HTTPException(500, f"Could not answer that: {text}")


# Serve the frontend (index.html, style.css, script.js). Must come AFTER the API routes.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)