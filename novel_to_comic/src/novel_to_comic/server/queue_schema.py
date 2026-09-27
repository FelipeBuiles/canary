"""Explicit queue schema bootstrap: python -m novel_to_comic.server.queue_schema.

Use a dedicated database or a private schema selected by the login role's
search_path. Existing schemas are left untouched; Procrastinate version upgrades
require its documented migration procedure.
"""
import asyncio
import os

import procrastinate
from dotenv import load_dotenv


async def initialize_schema():
    load_dotenv()
    dsn = os.environ.get("CANARY_QUEUE_DATABASE_URL")
    if not dsn:
        raise SystemExit("Set CANARY_QUEUE_DATABASE_URL to the dedicated queue database")
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=dsn))
    async with app.open_async():
        row = await app.connector.execute_query_one_async("SELECT to_regclass('procrastinate_jobs') AS relation")
        if row["relation"] is None:
            await app.schema_manager.apply_schema_async()
            print("Procrastinate schema created")
        else:
            print("Procrastinate schema already exists; no changes made")


if __name__ == "__main__":
    asyncio.run(initialize_schema())
