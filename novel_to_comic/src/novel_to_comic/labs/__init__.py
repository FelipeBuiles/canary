"""Labs — image-model experimentation harness.

A standalone surface for running the same prompt + reference images through
multiple image-generation providers in parallel and comparing the results.
Independent of the main pipeline so we can wire experimental providers
(fal.ai, together.ai, ...) without touching production code.
"""

from .registry import LabsModelEntry, load_registry
from .providers.base import LabsImageInput, LabsImageResult

__all__ = [
    "LabsModelEntry",
    "load_registry",
    "LabsImageInput",
    "LabsImageResult",
]
