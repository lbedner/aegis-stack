"""The pieces the voice panels are built from: a collapsing section,
a level meter, and a preview player."""

import asyncio
import random
from collections.abc import Callable

import flet as ft
from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.controls.expand_arrow import ExpandArrow
from app.components.frontend.theme import AegisTheme as Theme


class CollapsibleSection(ft.Container):
    """A section with a clickable header that expands/collapses content."""

    def __init__(
        self,
        title: str,
        content: ft.Control,
        initially_expanded: bool = True,
    ) -> None:
        super().__init__()

        self._expanded = initially_expanded
        self._arrow = ExpandArrow(expanded=initially_expanded)
        self._content_container = ft.Container(
            content=content,
            visible=initially_expanded,
            padding=ft.padding.only(
                top=Theme.Spacing.MD,
                left=Theme.Spacing.MD,
                right=Theme.Spacing.MD,
                bottom=Theme.Spacing.MD,
            ),
        )

        # Header row with arrow and title
        header = ft.Container(
            content=ft.Row(
                [
                    self._arrow,
                    ft.Text(title, weight=ft.FontWeight.W_600, size=14),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM,
                vertical=Theme.Spacing.SM,
            ),
            on_hover=self._on_hover,
        )

        # Clickable header
        clickable_header = ft.GestureDetector(
            content=header,
            on_tap=self._toggle,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        self.content = ft.Column(
            [clickable_header, self._content_container],
            spacing=0,
        )

    def _toggle(self, _e: ft.ControlEvent) -> None:
        """Toggle expansion state."""
        self._expanded = not self._expanded
        self._arrow.set_expanded(self._expanded)
        self._content_container.visible = self._expanded
        self.update()

    def _on_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover state."""
        if e.data == "true":
            e.control.bgcolor = ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)
        else:
            e.control.bgcolor = None
        if e.control.page:
            e.control.update()


class AudioWaveVisualizer(ft.Container):
    """Animated sound wave bars that pulse during audio playback."""

    NUM_BARS = 11
    BASE_INTERVAL = 0.1  # 100ms base animation interval

    def __init__(self) -> None:
        super().__init__()

        self._bars: list[ft.Container] = []
        self._is_playing = False
        self._speed = 1.0

        # Build bars with varying initial heights (wave pattern)
        base_heights = [8, 14, 20, 26, 32, 36, 32, 26, 20, 14, 8]
        for i in range(self.NUM_BARS):
            bar = ft.Container(
                width=6,
                height=base_heights[i],
                bgcolor=Theme.Colors.PRIMARY,
                border_radius=3,
                animate=ft.Animation(100, ft.AnimationCurve.EASE_IN_OUT),
            )
            self._bars.append(bar)

        self.content = ft.Row(
            self._bars,
            spacing=4,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def start_animation(self, speed: float = 1.0) -> None:
        """Start the wave animation at the given speed."""
        self._is_playing = True
        self._speed = max(0.25, min(4.0, speed))  # Clamp to valid range
        if self.page:
            self.page.run_task(self._animate_bars)

    def stop_animation(self) -> None:
        """Stop the wave animation and reset bars."""
        self._is_playing = False
        # Reset to default heights
        base_heights = [8, 14, 20, 26, 32, 36, 32, 26, 20, 14, 8]
        for i, bar in enumerate(self._bars):
            bar.height = base_heights[i]
        if self.page:
            self.update()

    async def _animate_bars(self) -> None:
        """Animate bar heights in a wave pattern."""
        # Faster speed = shorter interval (more frequent updates)
        interval = self.BASE_INTERVAL / self._speed
        while self._is_playing:
            for bar in self._bars:
                # Randomize height between 8 and 40
                bar.height = random.randint(8, 40)
            if self.page:
                self.update()
            await asyncio.sleep(interval)


class VoicePreviewPlayer(ft.Container):
    """Preview player with play button, wave visualizer, and voice info."""

    DEFAULT_PREVIEW_TEXT = "Hello! This is a preview of my voice."

    def __init__(
        self,
        on_play: Callable[[str], None],
        voice_name: str = "",
        voice_description: str = "",
    ) -> None:
        super().__init__()

        self._on_play = on_play
        self._is_playing = False
        self._visualizer = AudioWaveVisualizer()

        self._play_button = ft.IconButton(
            icon=ft.Icons.PLAY_CIRCLE_FILLED,
            icon_size=48,
            icon_color=Theme.Colors.PRIMARY,
            on_click=self._on_play_click,
            tooltip="Preview voice",
        )

        self._voice_label = ft.Text(
            voice_name,
            size=14,
            weight=ft.FontWeight.W_600,
            text_align=ft.TextAlign.CENTER,
        )

        self._voice_description = SecondaryText(
            voice_description,
            size=12,
            text_align=ft.TextAlign.CENTER,
        )

        # Text input for custom preview text
        self._text_field = ft.TextField(
            value=self.DEFAULT_PREVIEW_TEXT,
            label="Preview text",
            hint_text="Enter text to speak...",
            multiline=True,
            min_lines=2,
            max_lines=3,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
        )

        # Layout: centered column with text field, button, visualizer, voice info
        self.content = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "VOICE PREVIEW",
                        size=10,
                        weight=ft.FontWeight.W_500,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=Theme.Spacing.SM),
                    self._text_field,
                    ft.Container(height=Theme.Spacing.SM),
                    ft.Row(
                        [self._play_button, self._visualizer],
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=Theme.Spacing.MD,
                    ),
                    ft.Container(height=Theme.Spacing.SM),
                    self._voice_label,
                    self._voice_description,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=Theme.Spacing.MD,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=Theme.Components.CARD_RADIUS,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        )

    def _on_play_click(self, e: ft.ControlEvent) -> None:
        """Handle play button click."""
        if self._on_play:
            text = self._text_field.value or self.DEFAULT_PREVIEW_TEXT
            self._on_play(text)

    def set_playing(self, playing: bool, speed: float = 1.0) -> None:
        """Update play state and animation."""
        self._is_playing = playing
        if playing:
            self._play_button.icon = ft.Icons.STOP_CIRCLE
            self._visualizer.start_animation(speed)
        else:
            self._play_button.icon = ft.Icons.PLAY_CIRCLE_FILLED
            self._visualizer.stop_animation()
        self.update()

    def set_voice(self, name: str, description: str) -> None:
        """Update displayed voice info."""
        self._voice_label.value = name
        self._voice_description.value = description
        self.update()
