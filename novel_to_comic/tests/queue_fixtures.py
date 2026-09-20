"""Explicit non-durable route fixture. Real queue tests use PostgreSQL.

These pre-existing route tests inspect runner closures without starting lifespan;
production create_app always requires the durable service.
"""
from types import SimpleNamespace

from novel_to_comic.server.app import create_app as create_production_app


def create_app(*args, **kwargs):
    app = create_production_app(*args, **kwargs)
    app.state.durable_queue_required = False
    app.state.durable_queue = SimpleNamespace(healthy=True)
    return app
