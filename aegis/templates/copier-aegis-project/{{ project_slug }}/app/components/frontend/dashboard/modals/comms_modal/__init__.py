"""The comms modal, one module per tab.

``comms_modal.py`` was eight hundred lines of three tabs, two of which
were the same editable-configuration tab written twice. The shared
half is now ``config_tab``; each tab is its own module. This re-exports
the names that were importable before, so nothing outside the package
had to change.
"""

from .config_tab import EditableConfigTab
from .dialog import CommsDetailDialog
from .email_tab import EmailTab
from .overview_tab import OverviewSection, OverviewTab
from .twilio_tab import TwilioTab

__all__ = [
    "CommsDetailDialog",
    "EditableConfigTab",
    "EmailTab",
    "OverviewSection",
    "OverviewTab",
    "TwilioTab",
]
