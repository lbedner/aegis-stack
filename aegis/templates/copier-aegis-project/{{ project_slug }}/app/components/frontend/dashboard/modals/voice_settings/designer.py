"""A voice profile's editor in the voice tab, as the htmx Overseer's (one
profile opened from the list, ``profiles``), in three steps over the API
(``/api/v1/voice/design``), drawn from the designer's view as it comes:
every pick and filter asks the server again. Voice: who it is (narrowed
by gender, tone and accent; a provider without its key one line).
Delivery: a style, the speed, and the dials and anything extra under
Fine-tune. Review: what gets sent, heard unsaved, saved."""

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    H3Text,
    NativeDropdown,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings

API = "/api/v1/voice"


def preview(voice: str, model: str | None = None) -> str:
    """Where ``voice`` is heard (on ``model`` where given): the voice API's
    preview."""
    return f"{API}/preview/{voice}" + (
        f"?{urlencode({'model': model})}" if model else ""
    )


# The search's filters were sent (``finder.SENT``): a cleared one stays so.
SENT = "filtered"


def ticked(options: list[dict[str, Any]], named: bool = False) -> str:
    """A checklist's first ticked option, as a dropdown's value."""
    found = next((o for o in options if o["checked"]), None)
    if found is None:
        return ""
    return f"{found['name']}:{found['value']}" if named else found["value"]


def accent_choices(options: list[dict[str, Any]]) -> dict[str, str]:
    """The accent checklist as one dropdown: each language (all its
    accents), its accents indented under it."""
    return {"": "Any"} | {
        f"{o['name']}:{o['value']}": f"    {o['label']}"
        if o["indent"]
        else f"{o['label']} (all)"
        for o in options
    }


def accent_picked(value: str) -> dict[str, list[str]]:
    """An accent dropdown's value as the filters it sets: a language, or
    one accent."""
    name, _, picked = value.partition(":")
    return {"language": [], "accent_of": []} | ({name: [picked]} if picked else {})


def api(page: ft.Page) -> Any:
    from app.components.frontend.state.session_state import get_session_state

    return get_session_state(page).api_client


def play(page: ft.Page, held: list[ft.Audio], path: str) -> None:
    """``path`` heard, one at a time: a new one stops the last."""
    for audio in held:
        if audio in page.overlay:
            page.overlay.remove(audio)
    held[:] = [ft.Audio(src=f"http://localhost:{settings.PORT}{path}", autoplay=True)]
    page.overlay.append(held[0])
    page.update()


class VoiceEditor(ft.Column):
    """One profile's editor, a step at a time; ``back`` returns to the list."""

    def __init__(self, profile_id: int, back: Callable[[], None]) -> None:
        super().__init__(spacing=Theme.Spacing.MD)
        self._profile_id, self._back = profile_id, back
        self._view: dict[str, Any] = {}
        self._step = "voice"
        # Whether Fine-tune is open: every pick redraws the editor.
        self._tuning = False
        self._held: list[ft.Audio] = []

    def _api(self) -> Any:
        return api(self.page)

    async def load(self, query: dict[str, Any]) -> None:
        query = {"profile": str(self._profile_id)} | query
        view = await self._api().get(f"{API}/design?{urlencode(query, doseq=True)}")
        if isinstance(view, dict):
            if not self._view:  # opened to edit: Fine-tune open where tuned
                self._tuning = view["tuned"]
            self._show(view)

    def _query(self, **picks: Any) -> dict[str, Any]:
        """The design and the search as the server reads them, ``picks``
        over them (a filter's values a list)."""
        view, find = self._view, self._view["find"]
        return view["form"] | find["filters"] | {SENT: "1", "q": find["q"]} | picks

    def _pick(self, **picks: Any) -> None:
        """A pick or a filter asks the server again: the voices narrowed,
        the dials a style sets, what gets sent rewritten."""
        self.page.run_task(self.load, self._query(**picks))

    def _go(self, step: str) -> None:
        self._step = step
        self._show(self._view)

    def _show(self, view: dict[str, Any]) -> None:
        self._view = view
        body = {"voice": self._who, "delivery": self._how, "review": self._review}
        self.controls = [self._head(), body[self._step](), self._nav()]
        if self.page:
            self.update()

    def _choose(
        self, label: str, choices: dict[str, str], value: str, on: Any, width: int = 200
    ) -> ft.Control:
        return NativeDropdown(
            label=label,
            options=[ft.dropdown.Option(k, v) for k, v in choices.items()],
            value=value,
            width=width,
            on_change=lambda e: on(e.control.value or ""),
        )

    def _head(self) -> ft.Control:
        steps = self._view["steps"]
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.TextButton(
                            "Profiles",
                            icon=ft.Icons.ARROW_BACK,
                            on_click=lambda _: self._back(),
                        ),
                        H3Text(self._view["profile"]["name"]),
                        SecondaryText("In use" if self._view["active"] else ""),
                    ]
                ),
                ft.Row(
                    [
                        ft.TextButton(
                            f"{i}. {label}",
                            style=ft.ButtonStyle(
                                color=Theme.Colors.SUCCESS
                                if key == self._step
                                else None
                            ),
                            on_click=lambda _, key=key: self._go(key),
                        )
                        for i, (key, label) in enumerate(steps.items(), 1)
                    ]
                    + [
                        SecondaryText(
                            f"step {list(steps).index(self._step) + 1} of {len(steps)}"
                        )
                    ]
                ),
            ],
            spacing=0,
        )

    def _who(self) -> ft.Control:
        view, find = self._view, self._view["find"]
        options = find["options"]
        listed = ([view["chosen"]] if view["chosen"] else []) + find["cards"]
        more = find["matched"] - len(find["cards"])
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.TextField(
                            label="Search voices",
                            value=find["q"],
                            width=220,
                            dense=True,
                            on_submit=lambda e: self._pick(q=e.control.value or ""),
                        ),
                        *(
                            self._choose(
                                label,
                                {"": "Any"}
                                | {o["value"]: o["label"] for o in options[key]},
                                ticked(options[key]),
                                lambda v, name=name: self._pick(
                                    **{name: [v] if v else []}
                                ),
                                width=170,
                            )
                            for key, name, label in (
                                ("provider", "provider", "Provider"),
                                ("gender", "gender", "Gender"),
                                ("family", "family", "Tone"),
                            )
                        ),
                        self._choose(
                            "Accent",
                            accent_choices(options["accent"]),
                            ticked(options["accent"], named=True),
                            lambda v: self._pick(**accent_picked(v)),
                            width=220,
                        ),
                    ],
                    wrap=True,
                    spacing=Theme.Spacing.MD,
                ),
                *(
                    SecondaryText(
                        f"{lock['voices']} {lock['provider_name']} voices need "
                        f"{lock['key']}: add it in Secrets to use them."
                    )
                    for lock in view["locked"]
                ),
                ft.RadioGroup(
                    value=view["voice"],
                    on_change=lambda e: self._pick(voice=e.control.value),
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Radio(value=v["id"], width=32),
                                    ProviderIcon(
                                        v["provider_name"],
                                        view["logos"]
                                        .get(v["provider"], {})
                                        .get("icon"),
                                    ),
                                    BodyText(v["name"], width=170),
                                    SecondaryText(v["detail"], expand=True),
                                    ft.IconButton(
                                        ft.Icons.VOLUME_UP,
                                        icon_size=16,
                                        tooltip="Listen",
                                        on_click=lambda _, v=v: play(
                                            self.page,
                                            self._held,
                                            preview(v["id"], view["model"]),
                                        ),
                                    ),
                                ],
                                data="chosen" if v is view["chosen"] else None,
                            )
                            for v in listed
                        ],
                        spacing=0,
                    ),
                ),
                SecondaryText(
                    "No other voice matches all of those: clear a filter or the search.",
                    visible=not find["cards"],
                ),
                SecondaryText(
                    f"The first {len(find['cards'])} of {find['matched']:,}; "
                    "search or narrow to see the rest.",
                    visible=more > 0,
                ),
                self._choose(
                    "Spoken on",
                    {m["id"]: f"{m['id']}: {m['note']}" for m in view["models"]},
                    view["model"],
                    lambda v: self._pick(model=v),
                    width=520,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

    def _speed(self, view: dict[str, Any]) -> ft.Control:
        """The speed slider, over the speeds the model takes; nothing for a
        model with no speed (Gemini)."""
        if not view["speed_range"]:
            return ft.Row(visible=False)
        low, high = view["speed_range"]
        return ft.Row(
            [
                SecondaryText("Speed"),
                ft.Slider(
                    min=low,
                    max=high,
                    value=view["speed"],
                    divisions=int((high - low) / 0.05),
                    label="{value}",
                    width=300,
                    on_change_end=lambda e: self._pick(speed=round(e.control.value, 2)),
                ),
            ]
        )

    def _how(self) -> ft.Control:
        view, delivery, chosen = (
            self._view,
            self._view["delivery"],
            self._view["chosen"],
        )
        dials = [
            self._choose(
                name.title(),
                choices,
                delivery[name],
                lambda v, name=name: self._pick(**{name: v}),
                width=150,
            )
            for name, choices in view["dials"].items()
        ]
        return ft.Column(
            [
                ft.Row(
                    [
                        SecondaryText("Voice"),
                        BodyText(chosen["name"] if chosen else view["voice"]),
                        SecondaryText(
                            f"{chosen['detail']} · on {view['model']}" if chosen else ""
                        ),
                        ft.IconButton(
                            ft.Icons.VOLUME_UP,
                            icon_size=16,
                            tooltip="Listen",
                            on_click=lambda _: play(
                                self.page,
                                self._held,
                                preview(view["voice"], view["model"]),
                            ),
                        ),
                    ],
                    data="chosen",
                ),
                SecondaryText(
                    f"{view['model']} ignores delivery instructions: a style and "
                    "fine-tuning change nothing. Pick a model that follows them on "
                    "the Voice step.",
                    color=Theme.Colors.WARNING,
                    visible=not view["follows"],
                    data="ignores",
                ),
                ft.RadioGroup(
                    value=delivery["style"] or "",
                    on_change=lambda e: self._pick(style=e.control.value),
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Radio(
                                        value=key, label=style["label"], width=220
                                    ),
                                    SecondaryText(style["sounds"], expand=True),
                                ]
                            )
                            for key, style in view["styles"].items()
                        ],
                        spacing=0,
                    ),
                ),
                self._speed(view),
                ft.ExpansionTile(
                    title=SecondaryText(
                        "Fine-tune (hints the model follows loosely; accents most of all)"
                    ),
                    initially_expanded=self._tuning,
                    on_change=lambda e: setattr(self, "_tuning", e.data == "true"),
                    controls=[
                        ft.Row(dials, wrap=True, spacing=Theme.Spacing.MD),
                        SecondaryText(
                            f"On {view['model']} the accent comes with the voice: "
                            "pick a voice by accent on the Voice step.",
                            visible=not view["steers_accent"],
                        ),
                        ft.TextField(
                            label="Anything else (pronunciation, words to avoid, how to open)",
                            value=delivery["extra"] or "",
                            multiline=True,
                            min_lines=2,
                            on_blur=lambda e: self._pick(extra=e.control.value or ""),
                        ),
                    ],
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

    def _review(self) -> ft.Control:
        view, chosen = self._view, self._view["chosen"]
        style = view["styles"][view["delivery"]["style"] or ""]
        return ft.Column(
            [
                BodyText(f"Voice: {chosen['name'] if chosen else view['voice']}"),
                BodyText(
                    f"Model: {view['model']}"
                    + ("" if view["follows"] else " (ignores delivery instructions)")
                ),
                BodyText(f"Style: {style['label']}"),
                BodyText(f"Speed: {view['speed']}", visible=bool(view["speed_range"])),
                SecondaryText("What gets sent"),
                ft.Container(
                    BodyText(view["instructions"], size=12, selectable=True),
                    border=ft.border.all(1, Theme.Colors.BORDER_DEFAULT),
                    border_radius=4,
                    padding=Theme.Spacing.SM,
                ),
                ft.Row(
                    [
                        PulseButton(
                            on_click_callable=self._listen,
                            text="Listen",
                            variant="muted",
                        ),
                        PulseButton(on_click_callable=self._save, text="Save"),
                    ],
                    spacing=Theme.Spacing.MD,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

    def _nav(self) -> ft.Control:
        labels = self._view["steps"]
        steps = list(labels)
        at, last = steps.index(self._step), len(steps) - 1
        return ft.Row(
            [
                ft.TextButton(
                    f"Back: {labels[steps[at - 1]]}",
                    visible=at > 0,
                    on_click=lambda _: self._go(steps[at - 1]),
                ),
                ft.TextButton(
                    f"Next: {labels[steps[at + 1]]}" if at < last else "",
                    visible=at < last,
                    on_click=lambda _: self._go(steps[min(at + 1, last)]),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

    async def _listen(self) -> None:
        """The design as it stands, heard unsaved."""
        play(
            self.page,
            self._held,
            f"{API}/design/preview?{urlencode(self._view['form'])}",
        )

    async def _save(self) -> None:
        view = self._view
        body = {
            "voice": view["voice"],
            "model": view["model"],
            "delivery": view["delivery"],
            "speed": view["speed"],
        }
        saved = await self._api().post(
            f"{API}/design?profile={view['profile']['id']}", json=body
        )
        if isinstance(saved, dict):
            self._back()
