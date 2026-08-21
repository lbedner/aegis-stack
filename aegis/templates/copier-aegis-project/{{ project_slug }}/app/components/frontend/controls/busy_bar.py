"""Indeterminate progress bar - the house "something is happening" signal.

A bar that sweeps back and forth, used instead of a spinning ring. A ring
occupies a fixed little square and reads as decoration beside a label; a
bar spans the width it is given, so it reads as the operation itself
rather than an ornament next to it.

Indeterminate is the point: ``ft.ProgressBar`` animates whenever ``value``
is ``None``, which is the honest rendering for work whose duration is not
known (an upload, an import, a model that loads for however long it
loads). Pass a ``value`` only when a real fraction exists - a bar that
fills at a made-up rate is a lie the user will time.

Example::

    from app.components.frontend.controls.busy_bar import busy_bar

    ft.Column([label, busy_bar()], spacing=16)
"""

import flet as ft

from app.components.frontend.styles import PulseColors


def busy_bar(*, width: int | None = None) -> ft.ProgressBar:
    """Return an indeterminate progress bar in the house accent.

    Args:
        width: Fixed width in pixels. ``None`` (the default) lets the bar
            fill its parent, which is what a panel or a column wants.

    Returns:
        An ``ft.ProgressBar`` with no ``value``, so it animates
        continuously rather than reporting a fraction.
    """
    return ft.ProgressBar(
        width=width,
        color=PulseColors.TEAL,
        bgcolor=PulseColors.BORDER,
        bar_height=4,
    )
