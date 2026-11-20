"""Pure encoders: one route's exact gateway request for a page or a Look asset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import gcd
from pathlib import Path
from typing import Any

from novel_to_comic.ai.providers.litellm_http import serialize_wire_request
from novel_to_comic.config import Config
from novel_to_comic.image_route_fallback import GatewayRoute
from novel_to_comic.models.draw import PreparedCompletePageRequest
from novel_to_comic.provider_wire import ProviderWireRequest


class _CallMetadata:
    """Stands in ``GatewayCall.fields`` for the usage event's metadata, which
    exists only once the call has started."""


CALL_METADATA = _CallMetadata()


@dataclass(frozen=True, slots=True)
class PageSettlement:
    """Draw: the image is verified against the frozen page and returned as bytes."""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class AssetSettlement:
    """Look: the image is saved at ``output_path``."""

    output_path: Path


@dataclass(frozen=True, slots=True)
class GatewayCall:
    """One route's exact request and the facts its usage event records."""

    route: GatewayRoute
    accounting_model: str
    #: The frozen request's provider model.
    request_model: str
    feature: str
    prompt: str
    event_params: dict[str, Any]
    ref_reads: list[tuple[Path, bytes | None]]
    fields: dict[str, Any]
    files: list[tuple[str, tuple[str, bytes, str]]]
    preview_target: str | None
    settlement: PageSettlement | AssetSettlement

    @property
    def endpoint(self) -> str:
        return "/v1/images/edits" if self.files else "/v1/images/generations"


def page_envelope(
    prepared: PreparedCompletePageRequest, route: GatewayRoute, *, quality: str | None, config: Config,
) -> GatewayCall:
    """The frozen page as ``route``'s provider expects it.

    The prompt is the frozen request's, as compiled: lettering was decided
    upstream, so this encoder cannot add or remove comic copy.
    """
    files = []
    ref_reads: list[tuple[Path, bytes | None]] = []
    if prepared.edit_source_bytes is not None:
        files.append(("image", ("complete-page-edit-source.png", prepared.edit_source_bytes, "image/png")))
        ref_reads.append((Path("complete-page-edit-source.png"), prepared.edit_source_bytes))
    for reference, data in zip(prepared.references, prepared.reference_bytes, strict=True):
        files.append(("image", (f"complete-page-ref-{reference.order}", data, reference.media_type)))
    ref_reads.extend(
        (Path(f"complete-page-ref-{reference.order}-{reference.id}"), data)
        for reference, data in zip(prepared.references, prepared.reference_bytes, strict=True)
    )
    fields: dict[str, Any] = {
        # Route through the configured gateway alias while preserving
        # the actual provider/model in the frozen edition manifest.
        "model": route.gateway_model,
        "prompt": prepared.prompt,
        "response_format": "b64_json",
        "canary_complete_page_request": prepared.frozen_request_json,
        "canary_requested_width": str(prepared.width),
        "canary_requested_height": str(prepared.height),
        "canary_requested_aspect": str(prepared.width / prepared.height),
        "canary_idempotency_key": prepared.idempotency_key,
    }
    if route.provider in {"openai", "openrouter", "fal-queue", "runware"}:
        # GPT Image 2.5 rejects input_fidelity, including on image edits.
        # Reference images are still sent unchanged in the multipart files.
        fields = {
            "model": route.gateway_model, "prompt": prepared.prompt,
            "size": f"{prepared.width}x{prepared.height}", "n": 1,
        }
        if route.provider in {"openai", "fal-queue", "runware"}:
            # Runware-only models (MiniMax H3) have no quality tier.
            quality_controls = [] if quality is None else [["quality", quality]]
            fields.update({"output_format": "png", **({} if quality is None else {"quality": quality})})
            # Both routes run through custom gateway handlers, which lose
            # standard Images fields. Preserve dimensions and controls
            # through the manifest those handlers consume.
            fields["canary_wire_request"] = json.dumps({
                "width": prepared.width,
                "height": prepared.height,
                "controls": [
                    *quality_controls,
                    ["output_format", "png"],
                    ["n", 1],
                ],
            })
        else:
            # LiteLLM 1.83.14 drops named size on custom image edits but
            # forwards aspect_ratio through optional_params to OpenRouter.
            divisor = gcd(prepared.width, prepared.height)
            fields["aspect_ratio"] = f"{prepared.width // divisor}:{prepared.height // divisor}"
            # Canary renders public-domain literature whose canonical
            # content can include distress (e.g. The Gift of the Magi).
            # Mirror the Vertex safety-off precedent: request Muse's
            # documented relaxed moderation tier instead of retrying
            # content-management-policy rejections that no other control
            # can clear.
            fields["moderation"] = "low"
    return GatewayCall(
        route=route,
        accounting_model=route.gateway_model,
        request_model=prepared.model,
        feature="complete_page_draw",
        prompt=prepared.prompt,
        event_params={
            "model": route.gateway_model,
            "provider_model": prepared.model,
            "size": f"{prepared.width}x{prepared.height}",
            "quality": quality or config.image_quality,
            "artifact_kind": "complete_page",
        },
        ref_reads=ref_reads,
        fields=fields,
        files=files,
        preview_target=f"page:{json.loads(prepared.frozen_request_json)['page_number']}",
        settlement=PageSettlement(prepared.width, prepared.height),
    )


def look_envelope(
    wire: ProviderWireRequest, route: GatewayRoute, *, output_path: Path, feature: str,
) -> GatewayCall:
    """The frozen Style/Cast wire, already bound to ``route``'s gateway alias.

    The wire's provider key picks the serializer; the route only names the
    deployment.
    """
    params, files = serialize_wire_request(wire)
    multipart = bool(files)
    return GatewayCall(
        route=route,
        accounting_model=wire.requested_alias or wire.configured_provider_model,
        request_model=wire.configured_provider_model,
        feature=feature,
        prompt=wire.prompt_parts[0],
        event_params=params,
        ref_reads=[
            (Path(ref.source_path), data)
            for ref, (_, (_, data, _)) in zip(wire.references, files, strict=True)
        ],
        fields={"prompt": str(params["prompt"]), "metadata": CALL_METADATA, **{
            key: str(value) if multipart else value
            for key, value in params.items() if key != "prompt" and value is not None
        }},
        files=files,
        preview_target=str(output_path.resolve()),
        settlement=AssetSettlement(output_path),
    )
