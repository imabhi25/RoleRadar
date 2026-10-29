"""Vercel entrypoint for the roleradar-api project.

Vercel's FastAPI preset looks for an ``app`` in a root-level app.py. The real
application lives in api/main.py; the repo-root main.py is the CLI prototype.
"""

from api.main import app  # noqa: F401
