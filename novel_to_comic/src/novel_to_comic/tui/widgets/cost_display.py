"""Live cost display widget."""

from __future__ import annotations

from textual.widget import Widget
from textual.widgets import Static


class CostDisplay(Static):
    """Shows running total cost for the pipeline."""

    DEFAULT_CSS = """
    CostDisplay {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $surface-darken-2;
        color: $text-muted;
        text-align: right;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._total = 0.0

    def update_cost(self, total_usd: float) -> None:
        """Update the displayed cost."""
        self._total = total_usd
        self.update(f"Total cost: ${self._total:.2f}")
