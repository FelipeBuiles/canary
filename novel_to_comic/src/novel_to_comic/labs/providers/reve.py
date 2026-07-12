"""Reve Labs adapter.

Reve experiments use the same compiled provider wire as production aliases.
The direct HTTP implementation was intentionally removed so this adapter cannot
rebuild prompt prose, infer reference roles, or upload mutable paths itself.
"""

from __future__ import annotations

from .base import LabsImageInput, LabsImageResult
from .litellm import LitellmProvider


class ReveProvider:
    name = "reve"

    async def generate(
        self,
        *,
        endpoint: str,
        inp: LabsImageInput,
        params: dict | None = None,
    ) -> LabsImageResult:
        # The runner compiles this wire with the image-reve route. Keep the
        # Labs registry endpoint as a display/price identity only.
        return await LitellmProvider().generate(
            endpoint="image-reve",
            inp=inp,
            params=params,
        )
