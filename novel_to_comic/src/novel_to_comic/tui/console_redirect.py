"""Silence Rich console.print output when running inside the TUI.

Stages use their own ``Console()`` instances for CLI output.
In TUI mode we redirect those to a black hole so they don't
clobber the Textual display.
"""

from __future__ import annotations

import io
from rich.console import Console


def install() -> None:
    """Monkey-patch ``rich.console.Console.print`` to a no-op.

    Call once at TUI startup.  Stages that create their own
    ``Console()`` instances will still go through this patched method.
    """
    _original_print = Console.print

    def _silent_print(self, *args, **kwargs):
        pass

    Console.print = _silent_print
    return _original_print


def uninstall(original) -> None:
    """Restore the original Console.print."""
    Console.print = original
