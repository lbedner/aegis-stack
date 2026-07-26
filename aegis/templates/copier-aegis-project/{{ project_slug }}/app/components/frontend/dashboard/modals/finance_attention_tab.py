"""The Attention tab: what the app thinks is worth your time.

One surface, three depths of the same idea: the analyst's latest note
narrates, the rule findings are the evidence it was written from, and the
recurring rollup is the standing context under both. These used to be two
stacked panels, each with its own header, toolbar, and scroll region - which
split one thought across two picture frames and squeezed the narration into
a fixed-height box. Now it is a single scroll with a single toolbar.

Only the newest note is shown. Each note is a daily digest of the same open
findings listed right below it, so yesterday's digest adds nothing but
scrolling; older notes stay in the API (``insight_type=analyst_note``).

Nothing here decides anything. The note was written by a local model from
figures the rules computed; this renders both and offers to ask for a new
note.
"""

import re

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    H3Text,
    PrimaryText,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import SuccessSnackBar
from app.components.frontend.controls.table import TableCellText, TableNameText
from app.components.frontend.dashboard.modals.modal_sections import date_cell
from app.components.frontend.theme import AegisTheme as Theme

from .modal_sections import EmptyStatePlaceholder

NOTE_INSIGHT_TYPE = "analyst_note"
_INSIGHTS_URL = "/api/v1/finance/insights"
_RECURRING_URL = "/api/v1/finance/recurring"
_RUN_URL = "/api/v1/finance/analyst/run"

_SEVERITY_COLOR = {
    "info": Theme.Colors.INFO,
    "warning": Theme.Colors.WARNING,
    "critical": Theme.Colors.ERROR,
}

# Bold, a bullet line, or a heading marker - the shapes the analyst's prompt
# allows (bold labels, occasional bullets) plus headings in case a model
# ignores the "no headings" rule.
_MARKDOWN_RE = re.compile(r"\*\*.+?\*\*|^\s*[-*] |^#{1,6} ", re.MULTILINE)


def _note_body(body: str) -> ft.Control:
    """Render a note's body as markdown when it actually carries markdown.

    Today's reports are sectioned markdown; notes written before that change
    are plain prose whose line breaks a markdown widget would swallow. Check
    the text, not the date: a model that ignores the format rules degrades to
    readable plain text instead of broken markup.
    """
    if not _MARKDOWN_RE.search(body):
        return SecondaryText(body)
    return ft.Markdown(
        body,
        selectable=True,
        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
        md_style_sheet=ft.MarkdownStyleSheet(
            p_text_style=ft.TextStyle(
                font_family="Roboto",
                size=Theme.Typography.BODY,
                color=Theme.Colors.TEXT_SECONDARY,
            ),
            list_bullet_text_style=ft.TextStyle(
                font_family="Roboto",
                size=Theme.Typography.BODY,
                color=Theme.Colors.TEXT_SECONDARY,
            ),
        ),
    )


class AttentionTab(ft.Container):
    """Analyst narration over the rule findings it was written from."""

    def __init__(self, page: ft.Page, *, with_notes: bool = True) -> None:
        super().__init__()
        self.page = page
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._with_notes = with_notes

        # Imported here, not at module scope: ``finance_modal`` imports THIS
        # module, so a top-level import would be a cycle.
        from .finance_modal import _refresh_row

        self._body = ft.Column(
            spacing=Theme.Spacing.LG, scroll=ft.ScrollMode.AUTO, expand=True
        )
        self._progress = ft.ProgressRing(width=16, height=16, visible=False)
        self._run_button = PulseButton(
            on_click_callable=self._run,
            text="Run analysis",
            variant="muted",
            compact=True,
        )
        leading: list[ft.Control] = []
        if with_notes:
            # No AI service in this build - there is no analyst to run, and
            # the findings are the whole tab.
            leading = [self._progress, self._run_button]
        self.content = ft.Column(
            [
                _refresh_row(
                    lambda e: e.page.run_task(self._load),
                    "Refresh",
                    leading=leading,
                ),
                self._body,
            ],
            spacing=0,
            expand=True,
        )

    def did_mount(self) -> None:
        if self.page:
            self.page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        from .finance_modal import _amount_cell, _recurring_display_amount, _usd

        api = get_session_state(self.page).api_client
        note = None
        if self._with_notes:
            notes_data = await api.get(
                _INSIGHTS_URL,
                params={"status": "new", "insight_type": NOTE_INSIGHT_TYPE},
            )
            notes = notes_data.get("items", []) if isinstance(notes_data, dict) else []
            note = notes[0] if notes else None
        ins_data = await api.get(_INSIGHTS_URL, params={"status": "new"})
        insights = ins_data.get("items", []) if isinstance(ins_data, dict) else []
        rec_data = await api.get(_RECURRING_URL)
        streams = rec_data.get("items", []) if isinstance(rec_data, dict) else []
        monthly = rec_data.get("monthly_cost", 0) if isinstance(rec_data, dict) else 0

        self._body.controls.clear()
        if self._with_notes:
            if note is not None:
                self._body.controls.append(self._note_card(note))
            else:
                self._body.controls.append(
                    EmptyStatePlaceholder(
                        message=(
                            "No note yet. The analyst runs nightly, "
                            "or you can run it now."
                        )
                    )
                )

        self._body.controls.append(H3Text("Findings"))
        if insights:
            self._body.controls.extend(self._insight_row(i) for i in insights)
        else:
            self._body.controls.append(
                EmptyStatePlaceholder(message="You're all caught up. No new findings.")
            )

        subs = sum(1 for s in streams if s.get("is_subscription"))
        self._body.controls.append(H3Text("Recurring"))
        self._body.controls.append(
            SecondaryText(
                f"{_usd(monthly)}/mo across {subs} subscription"
                f"{'s' if subs != 1 else ''}"
            )
        )
        if streams:
            columns = [
                DataTableColumn("Name"),
                DataTableColumn("Cadence", width=130),
                DataTableColumn("Amount", width=130, alignment="right"),
                DataTableColumn("Next", width=120),
            ]
            rows = [
                [
                    TableNameText(stream.get("name") or ""),
                    TableCellText(
                        (stream.get("frequency") or "").replace("_", " ").title()
                    ),
                    _amount_cell(_recurring_display_amount(stream)),
                    date_cell(stream.get("next_expected_date")),
                ]
                for stream in streams
            ]
            self._body.controls.append(
                DataTable(
                    columns=columns, rows=rows, empty_message="No recurring streams"
                )
            )
        if self._body.page is not None:
            self._body.update()

    def _note_card(self, note: dict) -> ft.Control:
        """The narration lead: full text, no height cap, model in the corner."""
        model_name = (note.get("metadata") or {}).get("model_name")
        header = [
            PrimaryText(
                note.get("title") or "",
                weight=Theme.Typography.WEIGHT_SEMIBOLD,
            ),
            ft.Container(expand=True),
        ]
        if model_name:
            header.append(SecondaryText(str(model_name)))
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        header,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=Theme.Spacing.SM,
                    ),
                    _note_body(note.get("body") or ""),
                ],
                spacing=Theme.Spacing.XS,
            ),
            padding=ft.padding.all(Theme.Spacing.MD),
            bgcolor=Theme.Colors.SURFACE_1,
            border=ft.border.all(1, Theme.Colors.BORDER_SUBTLE),
            border_radius=Theme.Components.CARD_RADIUS,
        )

    def _insight_row(self, item: dict) -> ft.Control:
        severity = item.get("severity", "info")
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            Tag(
                                text=severity.upper(),
                                color=_SEVERITY_COLOR.get(severity, Theme.Colors.INFO),
                            ),
                            PrimaryText(
                                item.get("title") or "",
                                weight=Theme.Typography.WEIGHT_SEMIBOLD,
                            ),
                            ft.Container(expand=True),
                            PulseButton(
                                on_click_callable=self._dismiss(item["id"]),
                                text="Dismiss",
                                variant="muted",
                                compact=True,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=Theme.Spacing.SM,
                    ),
                    SecondaryText(item.get("body") or ""),
                ],
                spacing=Theme.Spacing.XS,
            ),
            padding=ft.padding.all(Theme.Spacing.MD),
            bgcolor=Theme.Colors.SURFACE_1,
            border=ft.border.all(1, Theme.Colors.BORDER_SUBTLE),
            border_radius=Theme.Components.CARD_RADIUS,
        )

    def _dismiss(self, insight_id: int):
        """No-arg async click handler (PulseButton's contract)."""

        async def _handler() -> None:
            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            await api.post(f"{_INSIGHTS_URL}/{insight_id}/dismiss")
            SuccessSnackBar("Dismissed.").launch(self.page)
            await self._load()

        return _handler

    async def _run(self) -> None:
        """Ask for a fresh note via a background job.

        The model wait (minutes, when a cold local model has to load) runs
        as a server job; the endpoint answers with a job id immediately and
        the LoadingOverlay follows the job's SSE stream - no request is
        left holding a long connection.
        """
        from app.components.frontend.controls.loading_overlay import LoadingOverlay
        from app.components.frontend.state.session_state import get_session_state

        self._set_running(True)
        overlay = LoadingOverlay.of(self.page)
        overlay.show("Writing today's note...")
        try:
            api = get_session_state(self.page).api_client
            started = await api.post(f"{_RUN_URL}?force=true&background=true")
            if not isinstance(started, dict) or "job_id" not in started:
                overlay.fail(
                    api.last_error or "The analyst run could not be started.",
                    title="Note failed",
                )
                return
            note = await overlay.run_job(api, started["job_id"], title="Note failed")
            if note is None:
                return  # run_job already showed the job's error
            await self._load()
        finally:
            self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self._progress.visible = running
        self._run_button.disabled = running
        if self.page is not None:
            self.update()
