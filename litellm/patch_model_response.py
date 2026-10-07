"""Avoid deprecated Pydantic instance metadata in LiteLLM 1.101.0 streams.

Exclude metadata names before evaluating their getters, preserving the upstream
empty-chunk classification. Reject unknown or partially patched source layouts.
"""
from importlib.util import find_spec
from pathlib import Path


CHOICE_OLD = '''            attr_name.startswith("_")
            or callable(_attribute_of(choice, attr_name))
            or attr_name.startswith("model_")'''
CHOICE_NEW = '''            attr_name.startswith("_")
            or attr_name.startswith("model_")  # Canary: skip metadata before getters.
            or callable(_attribute_of(choice, attr_name))'''
DELTA_OLD = '''        if attr_name.startswith("_") or callable(_attribute_of(delta, attr_name)) or attr_name.startswith("model_"):'''
DELTA_NEW = '''        if (
            attr_name.startswith("_")
            or attr_name.startswith("model_")  # Canary: skip metadata before getters.
            or callable(_attribute_of(delta, attr_name))
        ):'''
PATCHES = ((CHOICE_OLD, CHOICE_NEW), (DELTA_OLD, DELTA_NEW))


def patch_source(source: str) -> str:
    if all(source.count(new) == 1 and old not in source for old, new in PATCHES):
        return source
    if any(source.count(old) != 1 or new in source for old, new in PATCHES):
        raise RuntimeError("LiteLLM stream inspection changed; review the Pydantic metadata patch")
    for old, new in PATCHES:
        source = source.replace(old, new)
    return source


def main() -> None:
    spec = find_spec("litellm")
    if spec is None or spec.origin is None:
        raise RuntimeError("LiteLLM package could not be located")
    target = Path(spec.origin).parent / "litellm_core_utils/model_response_utils.py"
    if not target.is_file():
        raise RuntimeError(f"LiteLLM stream inspection target missing beside {spec.origin}")
    source = target.read_text()
    patched = patch_source(source)
    if patched != source:
        target.write_text(patched)
    print(f"Verified Pydantic metadata patch: {target}")


if __name__ == "__main__":
    main()
