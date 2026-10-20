"""Provider-free settlement driver for the same execution path durable jobs use."""
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
