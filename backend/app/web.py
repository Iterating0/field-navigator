"""Serve the built frontend from the same origin as the API."""
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        relative = path.replace('\\', '/').lstrip('/')
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # Unknown API paths and missing assets must remain real 404s.
            if exc.status_code != 404 or relative == 'api' or relative.startswith('api/') or Path(relative).suffix:
                raise
            response = await super().get_response('index.html', scope)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Cache-Control'] = ('public, max-age=31536000, immutable'
                                             if relative.startswith('assets/') else 'no-cache')
        return response
