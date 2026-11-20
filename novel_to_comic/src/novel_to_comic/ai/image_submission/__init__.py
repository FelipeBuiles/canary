"""Image submission to the gateway for Draw pages and Look (Style/Cast) assets.

Each entry point binds its own credit rule and error style, so a caller
cannot pair a Draw page with Look's per-call authorisation or the reverse.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from novel_to_comic.ai.context import generation_probe
from novel_to_comic.ai.image_submission._attempt import DRAW_PAGE, LOOK_ASSET, attempt
from novel_to_comic.ai.image_submission._envelopes import look_envelope, page_envelope
from novel_to_comic.ai.providers import selector
from novel_to_comic.config import Config
from novel_to_comic.image_route_fallback import (
    OPENAI_SUNBURST_GATEWAY_MODEL,
    GatewayRoute,
    RoutePlan,
    SingleRoute,
    run_route_plan,
    sunburst_route_plan,
)
from novel_to_comic.models.draw import CompletePageProviderResult, PreparedCompletePageRequest
from novel_to_comic.provider_wire import ProviderWireRequest
from novel_to_comic.usage import ApiResult, estimate_image_cost


async def submit_page_image(
    prepared: PreparedCompletePageRequest, *, routes: RoutePlan, quality: str | None, config: Config,
) -> CompletePageProviderResult:
    """Submit one frozen complete page and return its verified PNG bytes.

    Draw's credit rule: the page's own job reservation covers the call.
    """
    result, evidence = await run_route_plan(
        routes,
        lambda route: attempt(page_envelope(prepared, route, quality=quality, config=config), DRAW_PAGE, config),
        surface=DRAW_PAGE.name, request_key=prepared.request_sha256,
        estimate_openai_usd=lambda: estimate_image_cost(
            OPENAI_SUNBURST_GATEWAY_MODEL, 1, quality=quality,
            ref_count=len(prepared.references) + int(prepared.edit_source_bytes is not None),
            prompt_text=prepared.prompt, width=prepared.width, height=prepared.height, basis="expected",
        ),
    )
    if evidence is None:
        return result
    return result.model_copy(update={"response_metadata": {**(result.response_metadata or {}), **evidence}})


async def submit_look_image(
    wire: ProviderWireRequest, *, output_path: Path, feature: str, config: Config,
    routes: RoutePlan | None = None,
) -> ApiResult[Path]:
    """Submit one frozen Style/Cast wire and save its image at ``output_path``.

    Look's credit rule: every submission is authorised on its own. Without
    ``routes`` the wire runs on the route order its provider key froze.
    """
    routes = routes or sunburst_route_plan(wire.provider_key) or SingleRoute(
        GatewayRoute(wire.provider_key, wire.requested_alias or ""),
    )

    async def on_route(route: GatewayRoute) -> ApiResult[Path]:
        routed = wire
        if route.gateway_model != (wire.requested_alias or ""):
            routed = replace(wire, requested_alias=route.gateway_model)
            routed = replace(routed, execution_fingerprint=routed.recompute_execution_fingerprint())
        selector.require_gateway_route(routed.requested_alias or "", config)
        # Each route's attempt is its own provider call and telemetry probe.
        with generation_probe() as probe:
            probe.wire_schema_version = wire.schema_version
            return await attempt(
                look_envelope(routed, route, output_path=output_path, feature=feature), LOOK_ASSET, config,
            )

    result, evidence = await run_route_plan(
        routes, on_route, surface=LOOK_ASSET.name, request_key=wire.execution_fingerprint,
        estimate_openai_usd=lambda: estimate_image_cost(
            OPENAI_SUNBURST_GATEWAY_MODEL, 1, quality=dict(wire.controls).get("quality"),
            ref_count=len(wire.references), prompt_text=wire.prompt_parts[0],
            width=wire.width, height=wire.height, basis="expected",
        ),
    )
    if evidence is None:
        return result
    return replace(result, response_metadata={**(result.response_metadata or {}), **evidence})
