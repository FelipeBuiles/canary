"""Provider-free settlement driver for the same execution path durable jobs use."""
from novel_to_comic import page_drawing
from novel_to_comic.page_drawing import page_draw_execution
from novel_to_comic.usage import calculate_cost_breakdown


async def execute_draw(compiled, *, artifacts, page, settle=True, **inputs):
    work, settled = page_draw_execution(
        project_dir=artifacts.project_dir, compiled=compiled, artifacts=artifacts,
        page=page, **inputs,
    )
    result = await work()
    # Unknown paid usage remains recoverable until the real ledger can settle it.
    if settle and calculate_cost_breakdown(result.usage).source != "unknown_provider_usage":
        settled(result)
    return result.value


class ScriptedPageAdapter:
    """Draw's request and result checks around a scripted transport, with no gateway."""

    def __init__(self, transport, profile=None):
        self._transport = transport
        self._profile = profile or page_drawing.production_page_capability_profile()

    def prepare(self, compiled):
        page_drawing.require_bound_page_request(compiled, self._profile)
        return page_drawing._prepare_complete_page(compiled, self._profile)

    async def generate(self, prepared):
        page_drawing._validate_prepared_page(prepared, self._profile)
        result = await self._transport.generate(prepared)
        page_drawing.check_vertex_page_result(result, prepared)
        return result
