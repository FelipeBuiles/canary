"""Fake dispatch transport; route tests execute the production command lifecycle."""
from unittest.mock import AsyncMock

from novel_to_comic.server.app import create_app as create_production_app
from novel_to_comic.server.durable_queue import DurableQueue


class TestDispatcher(DurableQueue):
    __test__ = False

    @property
    def healthy(self):
        return True

    def publish(self, job):
        super().publish(job)
        # Convenient manual execution for route tests; billing, operation
        # reconstruction, and cleanup are exactly the production executor.
        from novel_to_comic.server.job_execution import execute_command
        job.runner = lambda: execute_command(self.app, job)
        self.app.state.generation_queue.put_nowait(job)


def create_app(*args, **kwargs):
    app = create_production_app(*args, **kwargs)
    queue = TestDispatcher(app, 'postgresql://localhost/canary_test')
    queue.backend.job_manager.cancel_job_by_id_async = AsyncMock(return_value=True)
    app.state.durable_queue = queue
    return app


def enqueue_test_operation(app, *, work, config=None, **kwargs):
    import asyncio
    return asyncio.run(enqueue_test_operation_async(app, work=work, config=config, **kwargs))


async def enqueue_test_operation_async(app, *, work, config=None, on_settled=None, **kwargs):
    """Inject an operation handler in tests while exercising durable command billing."""
    from pathlib import Path
    from unittest.mock import patch
    from novel_to_comic.config import Config
    from novel_to_comic.state import create_initial_state, save_state
    from novel_to_comic.server.admission import Admission
    from novel_to_comic.server.credited_job import enqueue_reserved_generation_job
    from novel_to_comic.server.job_commands import command
    from novel_to_comic.server.job_execution import execute_command
    config = config or Config()
    volume = Path(kwargs['project_dir'])
    directory = volume / kwargs['user_id'] / 'book'
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / 'state.json').exists():
        save_state(create_initial_state('Book', 'input/source.txt'), directory)
    app.state.projects_dir = volume
    app.state.admission = Admission(volume)
    app.state.durable_queue_required = True
    app.state.durable_queue = TestDispatcher(app, 'postgresql://unused')
    kwargs['project_dir'] = directory
    kwargs['command'] = command('cover', directory, config)
    job, created = await enqueue_reserved_generation_job(app, **kwargs)
    async def execute():
        async def handler(*_args):
            return await work(), on_settled
        with patch('novel_to_comic.server.job_execution._operate', new=handler):
            return await execute_command(app, job)
    job.runner = execute
    return job, created
