"""Column widths and thresholds the tabs share."""

from datetime import datetime

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from ..modal_sections import MetricCard


SLOWLOG_CRITICAL_MS = 1000  # 1 second - Critical (red)
SLOWLOG_WARNING_MS = 100  # 100ms - Warning (yellow)
COL_WIDTH_CLIENT_ID = 100
COL_WIDTH_ADDRESS = 150
COL_WIDTH_AGE = 80
COL_WIDTH_IDLE = 80
COL_WIDTH_DB = 60
COL_WIDTH_COMMAND = 200
COL_WIDTH_TIMESTAMP = 180
COL_WIDTH_DURATION = 100
COL_WIDTH_SLOWLOG_CMD = 400
STAT_LABEL_WIDTH = 200
