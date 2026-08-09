"""Frontend UI controls for styled components."""

from .action_menu import ActionDropdown, ActionMenu, ActionMenuItem, MenuAction
from .busy_bar import busy_bar
from .buttons import ConfirmDialog
from .data_table import DataTable, DataTableColumn
from .expand_arrow import ExpandArrow
from .expandable_data_table import ExpandableDataTable, ExpandableRow
from .form_fields import (
    FormActionButtons,
    FormDropdown,
    FormSecretField,
    FormTextField,
)
from .method_badge import METHOD_COLORS, MethodBadge
from .section_card import SectionCard
from .service_card import ServiceCard
from .severity_filter import SeverityFilter
from .status_dot import StatusDot, status_dot
from .switch import ThemedSwitch
from .table import (
    TableCellText,
    TableHeaderText,
    TableNameText,
)
from .tag import StatusTag, Tag
from .tech_badge import TechBadge
from .text import (
    AccentText,
    BodyText,
    ConfirmationText,
    DisplayText,
    ErrorText,
    H1Text,
    H2Text,
    H3Text,
    LabelText,
    MetricText,
    NumericText,
    PrimaryText,
    SecondaryText,
    SuccessText,
    TitleText,
    WarningText,
)

__all__ = [
    # Legacy controls (refactored to use theme)
    "NumericText",
    "PrimaryText",
    "SecondaryText",
    "TitleText",
    "ConfirmationText",
    "MetricText",
    "LabelText",
    # New theme-based controls
    "DisplayText",
    "H1Text",
    "H2Text",
    "H3Text",
    "BodyText",
    "AccentText",
    "SuccessText",
    "WarningText",
    "ErrorText",
    # Table controls
    "DataTable",
    "DataTableColumn",
    "ExpandableDataTable",
    "ExpandableRow",
    "TableHeaderText",
    "TableCellText",
    "TableNameText",
    # Badge/Tag controls
    "Tag",
    "StatusTag",
    "TechBadge",
    "MethodBadge",
    "METHOD_COLORS",
    # Card layout controls
    "SectionCard",
    "ServiceCard",
    # Dialog controls
    "ConfirmDialog",
    # Action menu controls
    "ActionDropdown",
    "ActionMenu",
    "ActionMenuItem",
    "MenuAction",
    # Arrow controls
    "ExpandArrow",
    # Form controls
    "FormTextField",
    "FormSecretField",
    "FormDropdown",
    "FormActionButtons",
    # Filter controls
    "SeverityFilter",
    # Status indicators
    "busy_bar",
    "status_dot",
    "StatusDot",
    "ThemedSwitch",
]
