"""Quote, admit and execute Style proofs from one derived proof request."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from novel_to_comic import artifacts
from novel_to_comic.asset_generation import asset_matches_request
from novel_to_comic.codex_dev import CodexRoutingError, classify_operations, is_subscription
from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.image_geometry import style_proof_dimensions
from novel_to_comic.image_models import image_model_profile_for_config
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.stages import s2_style as style
from novel_to_comic.style_contract import style_template_for_suggestion
from novel_to_comic.usage import estimate_image_cost

from .codex_admission import (
    image_operations,
    prompt_image_operations,
    style_sample_operations,
)
from .credited_job import enqueue_reserved_generation_job
from .credits import credit_estimate_for_provider_cost
from .generation_jobs import (
    find_active_generation_job,
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
)
from .job_commands import command


def read_story_bible(project_dir: Path) -> StoryBible | None:
    path = artifacts.story_bible_path(project_dir)
    if not path.exists():
        return None
    return StoryBible.model_validate_json(path.read_text())


def supports_style_reference(config: Config) -> bool:
    return "style" in image_model_profile_for_config(config).supported_roles


@dataclass(frozen=True)
class StyleProof:
    """The single derivation of one proof's request inputs.

    A sample proof and a validation proof of the same suggestion differ only in
    candidate identity, brief, action and composition. Pricing, execution and
    freshness all read those from here.
    """

    candidate: dict
    project_dir: Path
    config: Config
    reference: Path | None
    validation: bool

    @classmethod
    def derive(
        cls, config: Config, project_dir: Path, candidate: dict, *, validation: bool = False,
    ) -> "StyleProof":
        direction_id = candidate.get("direction_id")
        direction = style.load_style_direction(project_dir, direction_id) if direction_id else None
        return cls(
            candidate=candidate,
            project_dir=project_dir,
            config=config.model_copy(update={"style_template": style_template_for_suggestion(candidate)}),
            reference=style.style_direction_image(project_dir, direction),
            validation=validation,
        )

    @property
    def candidate_id(self) -> str:
        identity = self.candidate["id"]
        return f"{identity}:validation" if self.validation else identity

    @property
    def _framing(self) -> dict[str, str]:
        if not self.validation:
            return {}
        return {
            "subject_action": style.STYLE_VALIDATION_ACTION,
            "composition": style.STYLE_VALIDATION_COMPOSITION,
        }

    def output_path(self, index: int) -> Path:
        if self.validation:
            return artifacts.style_validation_path(self.project_dir, self.candidate["id"])
        return artifacts.style_sample_path(self.project_dir, index)

    def request(self, bible: StoryBible, brief: str):
        return style.build_style_sample_request(
            self.config, bible, brief,
            candidate_id=self.candidate_id,
            style_reference=self.reference,
            style_reference_mode=self.candidate["style_reference_mode"],
            # A sample proof derives its project from the series-rooted output path.
            **({"project_dir": self.project_dir} if self.validation else {}),
            **self._framing,
        )

    def is_fresh(self, bible: StoryBible, index: int) -> bool:
        """Whether the stored image was made from today's request for this proof."""
        output = self.output_path(index)
        if not output.exists():
            return False
        brief = style.style_validation_brief(bible) if self.validation else None
        return asset_matches_request(output, self.request(bible, brief))

    def cost_usd(self, bible: StoryBible) -> float:
        return style.estimate_style_proof_cost_usd(
            self.config, self.project_dir, bible,
            self.config.style_template, self.candidate_id,
            style_reference=self.reference,
            style_reference_mode=self.candidate["style_reference_mode"],
            **self._framing,
        )

    def quote(self, bible: StoryBible) -> dict:
        return sample_quote(
            self.config, reserve=True,
            has_style_reference=self.reference is not None,
            exact_cost_usd=self.cost_usd(bible), validation=self.validation,
        )

    async def execute(self, bible: StoryBible, index: int, brief: str | None):
        """Draw this proof; the caller owns the shared sample brief."""
        return await style.generate_sample_image(
            self.config, bible, self.output_path(index), brief=brief,
            candidate_id=self.candidate_id,
            style_reference=self.reference,
            style_reference_mode=self.candidate["style_reference_mode"],
            # A sample proof derives its project from the series-rooted output path.
            **({"project_dir": self.project_dir} if self.validation else {}),
            **self._framing,
        )


def _reserved(quote: dict) -> int:
    return quote["reserved_credits"] or quote["estimate_credits"]


def sample_quote(
    config: Config,
    *,
    reserve: bool = False,
    has_style_reference: bool = False,
    exact_cost_usd: float | None = None,
    validation: bool = False,
) -> dict:
    """Keep one-sample preflight and generation credit checks in lockstep."""
    funding = classify_operations(style_sample_operations(config, validation=validation))
    if is_subscription(funding):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=reserve, funding=funding))
    if mock_mode_active(config):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=reserve))
    if exact_cost_usd is None:
        width, height = style_proof_dimensions()
        cost_kwargs = {
            "quality": getattr(config, "image_quality", None),
            "width": width, "height": height,
        }
        if has_style_reference and supports_style_reference(config):
            cost_kwargs["ref_count"] = 1
        exact_cost_usd = estimate_image_cost(config.effective_image_model(), 1, **cost_kwargs)
    return dict(credit_estimate_for_provider_cost(
        exact_cost_usd, "style", reserve=reserve, zero_cost_estimate=1,
    ))


def suggest_batch_quote(
    config: Config,
    project_dir: Path,
    sample_count: int = style.SAMPLE_COUNT,
    *,
    has_style_reference: bool = False,
    reference_size: tuple[int, int] | None = None,
) -> dict:
    funding = classify_operations(prompt_image_operations(config))
    if is_subscription(funding):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=True, funding=funding))
    if mock_mode_active(config):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=True))
    cost_usd = style.estimate_style_batch_cost_usd(
        config, project_dir, sample_count,
        has_style_reference=has_style_reference,
        reference_size=reference_size,
    )
    return dict(credit_estimate_for_provider_cost(cost_usd, "style", reserve=True))


def direction_operations(config: Config, *, with_neighbors: bool = False):
    """A faithful direction proof is followed by one vision call that names it."""
    base = prompt_image_operations(config) if with_neighbors else style_sample_operations(config)
    return (*base, ("text", config.effective_visual_review_model()))


def direction_quotes(
    config: Config,
    project_dir: Path,
    *,
    has_style_reference: bool = False,
    template: str | None = None,
    candidate_id: str = "direction_estimate",
    reference_size: tuple[int, int] | None = None,
) -> dict:
    def quote(operations, cost, *, zero_cost_estimate=1):
        try:
            funding = classify_operations(operations)
        except CodexRoutingError as exc:
            return {"supported": False, "error": str(exc)}
        return dict(credit_estimate_for_provider_cost(
            0.0 if is_subscription(funding) or mock_mode_active(config) else cost(),
            "style", reserve=True,
            zero_cost_estimate=0 if mock_mode_active(config) else zero_cost_estimate,
            funding=funding,
        ))

    reference_count = 1 if has_style_reference and supports_style_reference(config) else 0
    bible = read_story_bible(project_dir)

    def faithful_cost():
        width, height = style_proof_dimensions()
        naming = style.estimate_custom_direction_naming_cost_usd(
            config, bible.title if bible is not None else "", template or "",
        )
        return naming + (
            style.estimate_style_proof_cost_usd(
                config, project_dir, bible, template or config.style_template, candidate_id,
                reference_size=(reference_size or (1024, 1024)) if reference_count else None,
            )
            if bible is not None
            else estimate_image_cost(
                config.effective_image_model(), 1,
                quality=getattr(config, "image_quality", None),
                width=width, height=height,
                ref_count=reference_count,
                ref_image_sizes=[reference_size or (1024, 1024)] if reference_count else None,
            )
        )

    def neighbor_cost():
        return style.estimate_style_batch_cost_usd(
            config, project_dir, style.NEIGHBOR_COUNT, has_style_reference=bool(reference_count),
            reference_size=reference_size,
        )

    return {
        "faithful": quote(direction_operations(config), faithful_cost),
        "neighbors": quote(prompt_image_operations(config), neighbor_cost, zero_cost_estimate=0),
        "faithful_with_neighbors": quote(
            direction_operations(config, with_neighbors=True), lambda: faithful_cost() + neighbor_cost(),
        ),
    }


async def submit_samples(
    app: FastAPI,
    *,
    project_name: str,
    user_id: str,
    project_id: str,
    project_dir: Path,
    config: Config,
    bible: StoryBible,
    suggestions: list[dict],
    indices: list[int],
) -> list[dict[str, Any]]:
    """Quote and admit one sample job per index, reusing a proof already in flight."""
    operations = style_sample_operations(config)
    classify_operations(operations)
    jobs = []
    prune_finished_generation_jobs(app)
    for index in indices:
        existing = find_active_generation_job(
            app, project_name=project_name, kind="style_sample", payload={"index": index},
        )
        if existing:
            jobs.append(generation_job_payload(app, existing))
            continue
        candidate = suggestions[index - 1]
        proof = StyleProof.derive(config, project_dir, candidate)
        job, _created = await enqueue_reserved_generation_job(
            app, project_name=project_name, kind="style_sample",
            label=f"style {index}", payload={"index": index},
            user_id=user_id, project_id=project_id,
            project_dir=project_dir, stage="style",
            debit_description=f"Style sample {index}",
            reservation_credits=_reserved(proof.quote(bible)),
            operations=operations,
            command=command("style_sample", project_dir, config,
                bible=bible.model_dump(mode="json"), candidate=candidate, index=index),
            semaphore=generation_semaphore_for_config(app, proof.config),
        )
        jobs.append(generation_job_payload(app, job))
    return jobs


async def submit_validation(
    app: FastAPI,
    *,
    project_name: str,
    user_id: str,
    project_id: str,
    project_dir: Path,
    config: Config,
    bible: StoryBible,
    suggestion: dict,
    index: int,
) -> dict[str, Any]:
    """Quote and admit the optional validation proof, or return the one in flight."""
    operations = image_operations(config)
    prune_finished_generation_jobs(app)
    payload = {"id": suggestion["id"], "index": index}
    existing = find_active_generation_job(
        app, project_name=project_name, kind="style_validation", payload=payload,
    )
    if existing:
        return generation_job_payload(app, existing)
    proof = StyleProof.derive(config, project_dir, suggestion, validation=True)
    job, _created = await enqueue_reserved_generation_job(
        app, project_name=project_name, kind="style_validation",
        label=f"{suggestion['label']} validation", payload=payload,
        user_id=user_id, project_id=project_id, project_dir=project_dir, stage="style",
        debit_description="Style validation",
        reservation_credits=_reserved(proof.quote(bible)),
        operations=operations,
        command=command("style_validation", project_dir, config,
            bible=bible.model_dump(mode="json"), candidate=suggestion, index=index),
        semaphore=generation_semaphore_for_config(app, proof.config),
    )
    return generation_job_payload(app, job)
