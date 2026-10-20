"""Provider-free Draw authority shared by admission, stage quotes and reviews."""
from __future__ import annotations

from dataclasses import dataclass

from novel_to_comic.config import Config
from novel_to_comic.models.draw import BookEdition, RetryProvenance
from novel_to_comic.models.page import ApprovedVisualReferenceInventory
from novel_to_comic.page_drawing import (
    ApprovedReferenceFile, compile_page_generation_request, complete_page_adapter, ensure_current_page_edition,
    initial_page_profile, select_book_edition, validate_review_request,
)
from novel_to_comic.stages.s5_plan import approved_reference_files, approved_visual_inventory
from novel_to_comic.target_artifacts import TargetArtifacts


def resolve_draw_edition(target: TargetArtifacts, config: Config, *, persist=False,
                         allow_new=False, retained_review=False) -> BookEdition:
    if allow_new and not target.book_edition_path.exists():
        edition = select_book_edition(edition_id="book-edition-001",
                                     profile=initial_page_profile(target.project_dir, config))
        if persist:
            target.write_book_edition(edition)
        return edition
    return ensure_current_page_edition(target, target.read_book_edition(), config,
                                      persist=persist, allow_retained_review=retained_review)


@dataclass(frozen=True)
class DrawPreparation:
    config: Config
    edition: BookEdition
    inventory: ApprovedVisualReferenceInventory
    reference_files: dict[str, ApprovedReferenceFile]

    @classmethod
    def load(cls, target, config, *, persist=False, allow_new=False, retained_review=False,
             quote_identity=False):
        edition = resolve_draw_edition(target, config, persist=persist, allow_new=allow_new,
                                       retained_review=retained_review)
        if quote_identity:
            # Stage-wide estimates historically use a synthetic identity. It is
            # never persisted or submitted; route quotes keep the pinned edition.
            edition = select_book_edition(edition_id="estimate", profile=edition.capability_profile)
        return cls(config, edition, approved_visual_inventory(target.project_dir),
                   approved_reference_files(target.project_dir))

    def adapter(self):
        return complete_page_adapter(self.config, self.edition.capability_profile)

    def compile(self, page, *, retry: RetryProvenance, depiction="canonical", review=False):
        compiled = compile_page_generation_request(
            page, self.edition, self.inventory, self.reference_files, retry=retry,
            depiction=depiction, style_template=self.config.style_template,
        )
        if review:
            # Retained baked profiles may still be reviewed, but cannot submit
            # new image work through a current production adapter.
            validate_review_request(compiled, self.edition)
        else:
            self.adapter().prepare(compiled)
        return compiled
