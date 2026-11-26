from contextlib import asynccontextmanager
import sqlite3
import secrets
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.datastructures import Headers

from .database import AccessDenied, SQLiteDatabase, seed_database
from .presentation import SummaryChoice, choose_summary, claim_projection, followup
from .conversation import ChatInput, ChatOutput, Conversation, MessageConflict
from .consent import ConsentPurpose
from .llm import Provider, create_provider
from .session import Model, SessionState, SessionStatus, SessionUnavailable, SQLiteSessions, now_utc
from .settings import Settings
from .sop import Phase
from .workflow import FoundationWorkflow


JSON_BODY_LIMIT = 128 * 1024


class RequestBodyPolicy:
    """Bound bytes before JSON parsing, including streamed requests without a length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not (scope["type"] == "http" and scope["method"] == "POST"
                and scope["path"].startswith("/api/v1/sessions")):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        route = scope["path"].rstrip("/")
        if route.endswith(("/messages", "/summary", "/consent-demo")) and (
            headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
        ):
            response = JSONResponse(status_code=415, content={
                "code": "unsupported_media_type", "message": "Use application/json.", "retryable": False,
            })
            await response(scope, receive, send)
            return
        payload = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body = event.get("body", b"")
            if len(payload) + len(body) > JSON_BODY_LIMIT:
                response = JSONResponse(status_code=413, content={
                    "code": "request_too_large", "message": "The request body is too large.", "retryable": False,
                })
                await response(scope, receive, send)
                return
            payload.extend(body)
            if not event.get("more_body", False):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": bytes(payload), "more_body": False}

        await self.app(scope, replay, send)


class SessionView(BaseModel):
    session_id: str
    phase: Phase
    status: SessionStatus
    version: int


class CreatedSession(SessionView):
    credential: str


class ConsentDemoInput(Model):
    command: Literal["start", "poll"]
    request_id: str | None = None


def view(state: SessionState) -> SessionView:
    return SessionView(session_id=state.session_id, phase=state.phase,
                       status=state.status, version=state.version)


def create_app(settings: Settings | None = None, provider: Provider | None = None, *,
               clock=now_utc) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings if settings is not None else Settings()
        model_provider = provider if provider is not None else create_provider(config)
        path = config.database_path
        path.parent.mkdir(parents=True, exist_ok=True)
        database = SQLiteDatabase(path)
        if config.demo_mode:
            seed_database(database)
        else:
            database.initialize()
        app.state.sessions = SQLiteSessions(database, config.session_ttl_minutes, clock)
        app.state.sessions.initialize()
        app.state.workflow = FoundationWorkflow(app.state.sessions, config)
        app.state.conversation = Conversation(app.state.workflow, model_provider, config)
        app.state.settings = config
        yield

    app = FastAPI(title="Insurance Claims SOP", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestBodyPolicy)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, __):
        return JSONResponse(status_code=422, content={
            "code": "invalid_request", "message": "The request is invalid.", "retryable": False,
        })

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            app.state.sessions.check_ready()
        except (AttributeError, sqlite3.Error) as error:
            raise HTTPException(status_code=503, detail="Service unavailable") from error
        return {"status": "ready"}

    @app.post("/api/v1/sessions", status_code=201)
    def create_session(response: Response) -> CreatedSession:
        response.headers["Cache-Control"] = "no-store"
        state, token = app.state.sessions.create()
        return CreatedSession(**view(state).model_dump(), credential=token)

    @app.get("/api/v1/sessions/{session_id}")
    def read_session(session_id: str, response: Response,
                     authorization: Annotated[str | None, Header()] = None) -> SessionView:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=404, detail="Session unavailable")
        try:
            state = app.state.sessions.get(session_id, token)
        except SessionUnavailable as error:
            raise HTTPException(status_code=404, detail="Session unavailable") from error
        response.headers["Cache-Control"] = "no-store"
        return view(state)

    def load_authorized(connection, session_id, authorization):
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(404, "Session unavailable")
        try:
            return app.state.sessions.load(connection, session_id, token)
        except SessionUnavailable as error:
            raise HTTPException(404, "Session unavailable") from error

    @app.get("/api/v1/sessions/{session_id}/workspace")
    def workspace(session_id: str, response: Response,
                  authorization: Annotated[str | None, Header()] = None):
        response.headers["Cache-Control"] = "no-store"
        with app.state.sessions.transaction() as connection:
            state = load_authorized(connection, session_id, authorization)
            try:
                claim = claim_projection(app.state.workflow, state)
                summary = followup(app.state.workflow, connection, state)
            except AccessDenied:
                claim, summary = None, None
            return {**view(state).model_dump(), "claim": claim, "summary": summary,
                    "transcript": app.state.sessions.transcript(connection, state),
                    "verification": state.verification,
                    "handoff": state.handoff_status,
                    "human_offer": bool(state.recovery.offer_reason and state.status == SessionStatus.ACTIVE),
                    "provider": app.state.settings.llm_provider,
                    "demo": app.state.settings.demo_mode}

    def authorize_diagnostics(x_demo_key):
        key = app.state.settings.demo_diagnostics_key.get_secret_value()
        if not app.state.settings.demo_mode or not key or not secrets.compare_digest(
            key.encode(), (x_demo_key or "").encode()
        ):
            raise HTTPException(404, "Diagnostics unavailable")

    @app.get("/api/v1/sessions/{session_id}/events")
    def events(session_id: str, response: Response,
               authorization: Annotated[str | None, Header()] = None,
               x_demo_key: Annotated[str | None, Header()] = None):
        authorize_diagnostics(x_demo_key)
        response.headers["Cache-Control"] = "no-store"
        with app.state.sessions.transaction() as connection:
            state = load_authorized(connection, session_id, authorization)
            return {"events": app.state.sessions.audit_events(session_id)[-60:],
                    "matched": len(state.matched_fields),
                    "required": app.state.settings.min_verification_fields,
                    "intent": state.memory.intent, "emotion": state.emotion,
                    "secondary_intents": state.memory.secondary_intents,
                    "scope_count": state.out_of_scope_count, "refusals": state.refusal_count,
                    "pending": state.discussion.pending,
                    "hints": state.memory.claim_hints.model_dump(exclude={"case_id"}),
                    "provenance": state.memory.provenance, "origin_phases": state.memory.origin_phases}

    @app.post("/api/v1/sessions/{session_id}/consent-demo")
    def consent_demo(session_id: str, body: ConsentDemoInput, response: Response,
                     authorization: Annotated[str | None, Header()] = None,
                     x_demo_key: Annotated[str | None, Header()] = None):
        authorize_diagnostics(x_demo_key)
        response.headers["Cache-Control"] = "no-store"
        with app.state.sessions.transaction() as connection:
            state = load_authorized(connection, session_id, authorization)
            flow = app.state.workflow
            if state.status != SessionStatus.ACTIVE or not state.identity_verified:
                raise HTTPException(409, "Verification required")
            if body.command == "start":
                result = flow.consent.create(connection, state, "timeout", ConsentPurpose.SIMULATION, "demo")
            else:
                tool = flow._execute(connection, state, "get_consent_status",
                                     {"request_id": body.request_id, "purpose": "simulation"})
                if not tool.decision.allowed:
                    raise HTTPException(404, "Simulation unavailable")
                result = tool.output
            return {"request_id": result.request_id, "status": result.status, "poll_count": result.poll_count}

    @app.post("/api/v1/sessions/{session_id}/summary")
    def summary_choice(session_id: str, choice: SummaryChoice, response: Response,
                       authorization: Annotated[str | None, Header()] = None):
        response.headers["Cache-Control"] = "no-store"
        with app.state.sessions.transaction() as connection:
            state = load_authorized(connection, session_id, authorization)
            try:
                state = choose_summary(app.state.workflow, connection, state, choice)
            except (ValueError, AccessDenied) as error:
                raise HTTPException(409, "Summary choice unavailable or changed") from error
            return view(state)

    @app.post("/api/v1/sessions/{session_id}/messages", response_model=ChatOutput)
    def send_message(session_id: str, request: ChatInput, response: Response, incoming: Request,
                     authorization: Annotated[str | None, Header()] = None):
        scheme, _, token = (authorization or "").partition(" ")
        try:
            if scheme.lower() != "bearer" or not token:
                raise SessionUnavailable()
            if len(request.message) > app.state.settings.max_input_length:
                return JSONResponse(status_code=422, content={
                    "code": "message_too_long", "message": "The message exceeds the configured limit.",
                    "retryable": False,
                })
            result = app.state.conversation.send(session_id, token, request,
                                                 verification_source=incoming.client.host if incoming.client else "local")
        except SessionUnavailable:
            return JSONResponse(status_code=404, content={
                "code": "session_unavailable", "message": "Session unavailable.", "retryable": False,
            })
        except MessageConflict:
            return JSONResponse(status_code=409, content={
                "code": "message_conflict", "message": "This message ID is already in use.",
                "retryable": False,
            })
        except sqlite3.Error:
            return JSONResponse(status_code=503, content={
                "code": "storage_unavailable", "message": "Service unavailable.", "retryable": True,
            })
        response.headers["Cache-Control"] = "no-store"
        return result

    return app


app = create_app()
