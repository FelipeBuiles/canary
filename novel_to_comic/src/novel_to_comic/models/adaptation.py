"""Book-level story adaptation contracts for the full-page pipeline."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.validation import EditorialIssue


class RevisionedArtifact(BaseModel):
    """Immutable artifact whose hash changes with any authored content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(ge=1)
    content_sha256: str = ""

    @staticmethod
    def _content_digest(payload: dict) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @model_validator(mode="after")
    def _verify_content_hash(self) -> "RevisionedArtifact":
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        digest = self._content_digest(payload)
        if (
            self.content_sha256
            and self.content_sha256 != digest
        ):
            raise ValueError("content_sha256 does not match artifact content")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", digest)
        return self


class AdaptationBrief(RevisionedArtifact):
    """Human-approved book-level constraints for the adaptation."""

    status: Literal["draft", "approved"] = "draft"
    story_promises: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    point_of_view: str = ""
    narrator_treatment: str = ""
    tone: str = ""
    ambiguities: tuple[str, ...] = ()
    motifs: tuple[str, ...] = ()
    protected_language: tuple[str, ...] = ()
    essential_events: tuple[str, ...] = ()
    character_turns: tuple[str, ...] = ()
    transformation_level: Literal["faithful", "medium_specific", "transformative"] = (
        "medium_specific"
    )
    desired_emphasis: tuple[str, ...] = ()
    target_page_min: int = Field(ge=1)
    target_page_max: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_brief(self) -> "AdaptationBrief":
        if self.target_page_min > self.target_page_max:
            raise ValueError("target_page_min cannot exceed target_page_max")
        if self.status == "approved":
            required = {
                "story_promises": self.story_promises,
                "themes": self.themes,
                "point_of_view": self.point_of_view,
                "narrator_treatment": self.narrator_treatment,
                "tone": self.tone,
                "essential_events": self.essential_events,
                "character_turns": self.character_turns,
                "desired_emphasis": self.desired_emphasis,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(
                    "approved adaptation brief is incomplete: " + ", ".join(missing)
                )
        return self


class NarrativeTreatment(BaseModel):
    """The adaptation's global dramatic reasoning before page allocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    causal_spine: tuple[str, ...] = Field(min_length=1)
    character_arcs: tuple[str, ...] = ()
    essential_events: tuple[str, ...] = ()
    essential_event_ids: tuple[str, ...] = ()
    character_turns: tuple[str, ...] = ()
    character_turn_ids: tuple[str, ...] = ()
    reveals: tuple[str, ...] = ()
    reactions: tuple[str, ...] = ()
    consequences: tuple[str, ...] = ()
    transitions: tuple[str, ...] = ()
    aftermath: tuple[str, ...] = ()
    motifs: tuple[str, ...] = ()
    relative_emphasis: tuple[str, ...] = ()


class LetteringItem(BaseModel):
    """Complete, final wording for one lettering element."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: Literal["dialogue", "thought", "caption", "sfx"]
    text: str = Field(min_length=1)
    speaker: str | None = None
    speaker_entity_id: str | None = None
    delivery: Literal[
        "onscreen",
        "offscreen",
        "narration",
        "quoted_text",
        "display",
    ] | None = None
    source_unit_ids: tuple[str, ...] = ()


class AppearanceChange(BaseModel):
    """A story-state change downstream stages must render consistently."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(min_length=1)
    from_state_id: str | None = None
    to_state_id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ContinuityTransition(BaseModel):
    """An explicit change needed to follow place, time, knowledge, or emotion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: Literal["time", "place", "knowledge", "emotional_state"]
    scope_id: str = Field(
        min_length=1,
        description=(
            "Stable character/entity ID for knowledge or emotion, or stable "
            "narrative-thread ID for time or place."
        ),
    )
    from_state: str = Field(min_length=1)
    to_state: str = Field(min_length=1)
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_change(self) -> "ContinuityTransition":
        if self.from_state == self.to_state:
            raise ValueError("continuity transition must change state")
        return self


class AdaptedBeat(BaseModel):
    """One ordered story beat, independent of pages or panels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    summary: str = Field(min_length=1)
    narrative_function: Literal[
        "establisher",
        "initial",
        "prolongation",
        "peak",
        "release",
        "transition",
    ]
    story_functions: tuple[
        Literal[
            "causal_event",
            "reveal",
            "reaction",
            "consequence",
            "transition",
            "aftermath",
            "character_turn",
        ],
        ...,
    ] = ()
    brief_requirement_ids: tuple[str, ...] = ()
    source_unit_ids: tuple[str, ...] = Field(min_length=1)
    entity_ids: tuple[str, ...] = ()
    lettering: tuple[LetteringItem, ...] = ()
    transitions: tuple[ContinuityTransition, ...] = ()
    appearance_changes: tuple[AppearanceChange, ...] = ()


class AdaptationLedgerEntry(BaseModel):
    """Explicit accounting for one source unit's adapted disposition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_unit_id: str = Field(min_length=1)
    disposition: Literal[
        "depicted",
        "dialogue",
        "thought",
        "caption",
        "visual_motif",
        "compressed_into",
        "intentionally_omitted",
    ]
    adapted_beat_ids: tuple[str, ...] = ()
    reason: str | None = None
    preserved_function: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_disposition(self) -> "AdaptationLedgerEntry":
        if self.disposition in {"compressed_into", "intentionally_omitted"}:
            if not self.reason:
                raise ValueError(f"{self.disposition} requires a reason")
        if self.disposition == "compressed_into" and not self.adapted_beat_ids:
            raise ValueError("compressed_into requires an adapted-beat destination")
        if self.disposition == "intentionally_omitted" and self.adapted_beat_ids:
            raise ValueError(
                "intentionally_omitted cannot have an adapted-beat destination"
            )
        if (
            self.disposition not in {"compressed_into", "intentionally_omitted"}
            and not self.adapted_beat_ids
        ):
            raise ValueError(f"{self.disposition} requires an adapted beat")
        return self


class BookAdaptation(RevisionedArtifact):
    """Canonical book-level adaptation, before page allocation."""

    source_sha256: str = Field(min_length=64, max_length=64)
    brief_revision: int = Field(ge=1)
    brief_sha256: str = Field(min_length=64, max_length=64)
    treatment: NarrativeTreatment
    beats: tuple[AdaptedBeat, ...] = Field(min_length=1)
    ledger: tuple[AdaptationLedgerEntry, ...] = Field(min_length=1)
    editorial_issues: tuple[EditorialIssue, ...] = ()

    @model_validator(mode="after")
    def _validate_book(self) -> "BookAdaptation":
        beat_ids = [beat.id for beat in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("adapted beat IDs must be unique")
        if [beat.order for beat in self.beats] != list(range(1, len(self.beats) + 1)):
            raise ValueError("adapted beat order must be consecutive")

        lettering_ids = [item.id for beat in self.beats for item in beat.lettering]
        if len(lettering_ids) != len(set(lettering_ids)):
            raise ValueError("lettering IDs must be unique")

        known_beats = set(beat_ids)
        source_unit_ids = [entry.source_unit_id for entry in self.ledger]
        if len(source_unit_ids) != len(set(source_unit_ids)):
            raise ValueError("adaptation ledger source units must be unique")
        for entry in self.ledger:
            unknown = set(entry.adapted_beat_ids) - known_beats
            if unknown:
                raise ValueError(
                    f"ledger entry {entry.source_unit_id!r} references unknown beats: "
                    + ", ".join(sorted(unknown))
                )
        return self
