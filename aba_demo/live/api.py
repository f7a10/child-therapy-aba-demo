"""Loopback-only HTTP + WebSocket API for the SIMULATED live-session shell.

Run with ``python -m aba_demo.live``. This is a single-operator local tool, not
an authenticated multi-user service; never bind it to a public interface.
"""
import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .analysis import MAX_UPLOAD_BYTES
from .runtime import (COMMANDS, CapacityExceeded, InvalidTransition, SessionManager,
                      SessionNotFound, SubscriberOverflow)

UI_DIST = Path(__file__).resolve().parents[2] / "live-ui" / "dist"
DEFAULT_PORT = 8767
DEV_UI_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
CSP = ("default-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = Field(min_length=1, max_length=64)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    activity: Literal["table", "movement", "break"] | None = None
    task_region: list[float] | None = Field(default=None, min_length=4, max_length=4)
    title: str | None = Field(default=None, max_length=120)


class MomentMark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["confirmed", "not_seen", "unsure"] | None
    note: str = Field(default="", max_length=500)


class PointLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    posture: Literal["sitting", "standing", "lying", "not_visible"] | None = None
    area: Literal["at_area", "away_from_area", "not_visible"] | None = None


class SessionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Literal[COMMANDS]
    activity: Literal["table", "movement", "break"] | None = None


def _error(code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=code)


def create_app(manager: SessionManager | None = None, port: int = DEFAULT_PORT,
               dev_origins=(), ui_dist: Path = UI_DIST, library=None, analyses=None) -> FastAPI:
    manager = manager or SessionManager()
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", *dev_origins}

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await manager.shutdown()
        if analyses is not None:
            await asyncio.to_thread(analyses.shutdown)

    app = FastAPI(title="ABA Live Session Shell — simulation", version="0.1.0",
                  lifespan=lifespan, docs_url="/api/live/docs", redoc_url=None,
                  openapi_url="/api/live/openapi.json")
    app.state.manager = manager
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return _error(403, "Cross-origin write rejected")
            if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
                if origin not in allowed_origins:
                    return _error(403, "Cross-site write rejected")
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/assets/"):
            # Vite content-hashes asset names, so they can be cached forever.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            # The HTML shell must be revalidated so an update never runs a stale bundle.
            response.headers["Cache-Control"] = "no-cache"
        if not request.url.path.startswith("/api/live/docs"):
            response.headers["Content-Security-Policy"] = CSP
        return response

    @app.exception_handler(SessionNotFound)
    async def not_found(_request, _exc):
        return _error(404, "Session not found")

    @app.exception_handler(InvalidTransition)
    async def invalid_transition(_request, exc):
        return _error(409, str(exc))

    @app.exception_handler(CapacityExceeded)
    async def capacity(_request, exc):
        return _error(429, str(exc))

    @app.exception_handler(ValueError)
    async def bad_value(_request, exc):
        return _error(400, str(exc))

    @app.get("/api/live/health")
    async def health():
        return {"status": "ok", "mode": "simulation", "camera": False, "inference": False}

    @app.get("/api/live/scenarios")
    async def scenarios():
        return {"scenarios": manager.scenarios()}

    @app.get("/api/live/sessions")
    async def list_sessions():
        return {"sessions": manager.list()}

    @app.post("/api/live/sessions", status_code=status.HTTP_201_CREATED)
    async def create_session(body: CreateSession):
        return manager.create(body.scenario).snapshot()

    @app.get("/api/live/sessions/{session_id}")
    async def get_session(session_id: str):
        return manager.get(session_id).snapshot()

    @app.delete("/api/live/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def discard_session(session_id: str):
        await manager.discard(session_id)

    @app.post("/api/live/sessions/{session_id}/commands")
    async def command(session_id: str, body: SessionCommand):
        if (body.command == "set_activity") != (body.activity is not None):
            raise ValueError("activity is required for set_activity and only for set_activity")
        return await manager.get(session_id).command(body.command, body.activity)

    @app.get("/api/live/sessions/{session_id}/video")
    async def session_video(session_id: str):
        # Only a replay's own SHA-bound local file; synthetic sessions have no video.
        video_path = getattr(manager.get(session_id).scenario, "video_path", None)
        if video_path is None:
            return _error(404, "This session has no video")
        return FileResponse(video_path(), headers={"Cache-Control": "no-store"})

    # ----- analysed-session library (review after the session) -----

    def _library():
        if library is None:
            raise SessionNotFound("library")
        return library

    def _job(job_id):
        if analyses is None:
            raise SessionNotFound("analysis")
        try:
            return analyses.get(job_id)
        except KeyError:
            raise SessionNotFound(job_id) from None

    @app.get("/api/library")
    async def library_list():
        if library is None:
            return {"sessions": [], "analysis": False}
        return {"sessions": await asyncio.to_thread(library.list), "analysis": analyses is not None}

    @app.get("/api/library/accuracy")
    async def library_accuracy():
        if library is None:
            return {"sessions": 0, "labeled_sessions": 0, "labels": {}, "verdicts": {}}
        return await asyncio.to_thread(library.accuracy_overview)

    @app.get("/api/library/{session_id}")
    async def library_review(session_id: str):
        try:
            return await asyncio.to_thread(_library().review, session_id)
        except KeyError:
            raise SessionNotFound(session_id) from None

    @app.get("/api/library/{session_id}/video")
    async def library_video(session_id: str):
        try:
            video = _library().get(session_id).video_path()
        except KeyError:
            raise SessionNotFound(session_id) from None
        return FileResponse(video, headers={"Cache-Control": "no-store"})

    @app.get("/api/library/{session_id}/thumbnail")
    async def library_thumbnail(session_id: str):
        try:
            image = await asyncio.to_thread(_library().thumbnail, session_id)
        except KeyError:
            raise SessionNotFound(session_id) from None
        if image is None:
            return _error(404, "No still for this session")
        return Response(image, media_type="image/jpeg")

    @app.get("/api/library/{session_id}/export/{kind}.csv")
    async def library_export(session_id: str, kind: Literal["intervals", "episodes"]):
        try:
            text = await asyncio.to_thread(_library().export_csv, session_id, kind)
        except KeyError:
            raise SessionNotFound(session_id) from None
        # A byte-order mark so spreadsheet programs read the file as UTF-8.
        return Response("\ufeff" + text, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{session_id}-{kind}.csv"'})

    @app.get("/api/library/{session_id}/labels")
    async def library_labels(session_id: str):
        try:
            return await asyncio.to_thread(_library().labels, session_id)
        except KeyError:
            raise SessionNotFound(session_id) from None

    @app.put("/api/library/{session_id}/labels/{time}")
    async def library_set_label(session_id: str, time: float, body: PointLabel):
        try:
            return await asyncio.to_thread(_library().set_label, session_id, time, body.posture, body.area)
        except KeyError:
            raise SessionNotFound(session_id) from None

    @app.put("/api/library/{session_id}/moments/{moment_id}")
    async def library_mark(session_id: str, moment_id: str, body: MomentMark):
        try:
            marks = await asyncio.to_thread(_library().mark, session_id, moment_id,
                                            body.verdict, body.note)
        except KeyError:
            raise SessionNotFound(session_id) from None
        return {"clinician": marks}

    # ----- in-app analysis of a new video -----

    @app.get("/api/analyses/current")
    async def analysis_current():
        return {"analysis": None if analyses is None else analyses.current()}

    @app.post("/api/analyses", status_code=status.HTTP_201_CREATED)
    async def analysis_upload(request: Request):
        if analyses is None:
            return _error(404, "Analysis is not available")
        from urllib.parse import unquote

        try:
            folder, video, title = analyses.begin_upload(unquote(request.headers.get("x-filename", "")))
        except RuntimeError as exc:
            return _error(409, str(exc))
        size = 0
        try:
            with video.open("wb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ValueError("video_too_large")
                    handle.write(chunk)
            if size == 0:
                raise ValueError("empty_upload")
            job = analyses.create(folder, video, title)
        except BaseException as exc:
            import shutil

            shutil.rmtree(folder, ignore_errors=True)
            if isinstance(exc, RuntimeError):
                return _error(409, str(exc))
            raise
        return job.status()

    @app.get("/api/analyses/{job_id}")
    async def analysis_status(job_id: str):
        return _job(job_id).status()

    @app.get("/api/analyses/{job_id}/frame")
    async def analysis_frame(job_id: str):
        image = _job(job_id).jpeg()
        if image is None:
            return _error(404, "No frame to show")
        return Response(image, media_type="image/jpeg")

    @app.post("/api/analyses/{job_id}/select")
    async def analysis_select(job_id: str, body: Selection):
        job = _job(job_id)
        job.select(body.x, body.y, activity=body.activity, task_region=body.task_region,
                   title=body.title)
        return job.status()

    @app.post("/api/analyses/{job_id}/skip")
    async def analysis_skip(job_id: str):
        job = _job(job_id)
        job.skip()
        return job.status()

    @app.post("/api/analyses/{job_id}/continue")
    async def analysis_continue(job_id: str):
        job = _job(job_id)
        job.continue_without()
        return job.status()

    @app.delete("/api/analyses/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def analysis_discard(job_id: str):
        _job(job_id)
        await asyncio.to_thread(analyses.discard, job_id)

    @app.websocket("/api/live/sessions/{session_id}/events")
    async def events(websocket: WebSocket, session_id: str, after: int = Query(0, ge=0)):
        if websocket.headers.get("origin") not in allowed_origins:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        try:
            runner = manager.get(session_id)
        except SessionNotFound:
            # Accept first so the client receives a definitive close code instead of retrying.
            await websocket.close(code=4404, reason="session not found")
            return
        backlog, subscription = runner.subscribe(after)
        try:
            await websocket.send_json({"event_type": "stream_ready", "snapshot": runner.snapshot(),
                                       "history_start": runner.history_start(), "after": after})
            for event in backlog:
                await websocket.send_json(event)

            async def pump():
                while True:
                    await websocket.send_json(await subscription.next())

            async def drain_client():
                while True:
                    await websocket.receive_text()

            tasks = {asyncio.create_task(pump()), asyncio.create_task(drain_client())}
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
            for task in done:
                exc = task.exception()
                if isinstance(exc, SubscriberOverflow):
                    await websocket.close(code=4408, reason="lagging; resume with after")
                elif exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            subscription.close()

    if (ui_dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=ui_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            candidate = (ui_dist / path).resolve()
            if path and candidate.is_file() and ui_dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(ui_dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def not_built():
            return HTMLResponse("<h1>Live UI not built</h1><p>Run <code>npm ci &amp;&amp; npm run build"
                                "</code> in <code>live-ui/</code>, or use the Vite dev server.</p>")

    return app
