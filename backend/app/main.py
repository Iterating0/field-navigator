from contextlib import asynccontextmanager
import logging
from pathlib import Path
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import Settings
from app.api.fields import router as fields_router
from app.db.cache import FieldCache
from app.providers.base import ProviderError
from app.providers.openalex import OpenAlexProvider
from app.providers.llm import CompatibleLLMProvider
from app.providers.mock import MockLLMProvider
from app.services.field_decomposer import FieldDecomposer
from app.services.field_explorer import FieldExplorer
from app.services.paper_ranker import PaperRanker
from app.services.access_policy import LiveRequestGate
from app.services.query_resolver import QueryResolver
from app.services.literature_retriever import LiteratureRetriever
from app.web import FrontendFiles


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Keep timing/token events visible under the default uvicorn setup, which
        # otherwise configures only its own loggers. Never log prompts or keys.
        app_logger = logging.getLogger('app')
        if not app_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(levelname)s %(name)s %(message)s'))
            app_logger.addHandler(handler)
        app_logger.setLevel(logging.INFO)
        app_logger.propagate = False
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
            app.state.live_gate = LiveRequestGate(settings.live_request_budget, settings.live_max_concurrency)
            llm = CompatibleLLMProvider(client, settings) if settings.llm_api_key else MockLLMProvider()
            papers = OpenAlexProvider(client, settings.openalex_api_key, settings.openalex_mailto)
            cache = FieldCache(settings.db_path)
            app.state.explorer = FieldExplorer(settings,
                papers,
                FieldDecomposer(llm, require_evidence=bool(settings.llm_api_key)),
                PaperRanker(settings.rank_weights), cache,
                LiteratureRetriever(settings, papers, llm, client=client)
                    if settings.llm_api_key and settings.llm_model.strip() else None)
            app.state.resolver = QueryResolver(
                settings,
                llm if settings.llm_api_key and settings.llm_model.strip() else None,
                papers,
                cache,
            )
            yield

    app = FastAPI(title='Field Navigator', version='0.1.0', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173'],
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    @app.exception_handler(ProviderError)
    async def provider_error(request: Request, exc: ProviderError):
        return JSONResponse(status_code=exc.status_code, content={'detail': str(exc)})

    @app.get('/api/health')
    async def health():
        return {'status': 'ok', 'llm_configured': bool(settings.llm_api_key),
                'llm_ready': bool(settings.llm_api_key and settings.llm_model.strip()),
                'openalex_key_configured': bool(settings.openalex_api_key)}

    app.include_router(fields_router)
    if settings.frontend_dist_path:
        frontend = Path(settings.frontend_dist_path).resolve()
        if not (frontend / 'index.html').is_file():
            raise RuntimeError('FRONTEND_DIST_PATH must contain a built frontend index.html.')
        app.mount('/', FrontendFiles(directory=frontend, html=True), name='frontend')
    return app


app = create_app()
