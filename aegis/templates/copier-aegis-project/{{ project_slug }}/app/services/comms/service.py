"""Communications: email (Resend), and SMS and voice calls (Twilio). The
one way in: callers outside the service import from here, never from
``domains``."""

from app.services.comms.adapters.resend.messages import (
    EmailConfigurationError,
    EmailError,
    get_email_status,
    send_email,
    send_email_simple,
    validate_email_config,
)
from app.services.comms.domains.telephony.calls import (
    CallConfigurationError,
    CallError,
    get_call_status,
    make_call,
    make_call_simple,
    validate_call_config,
)
from app.services.comms.domains.telephony.sms import (
    SMSConfigurationError,
    SMSError,
    get_sms_status,
    send_sms,
    send_sms_simple,
    validate_sms_config,
)
from app.services.comms.models import (
    CallResponse,
    EmailResponse,
    MakeCallRequest,
    SendEmailRequest,
    SendSMSRequest,
    SMSResponse,
)

__all__ = [
    "CallConfigurationError",
    "CallError",
    "CallResponse",
    "EmailConfigurationError",
    "EmailError",
    "EmailResponse",
    "MakeCallRequest",
    "SMSConfigurationError",
    "SMSError",
    "SMSResponse",
    "SendEmailRequest",
    "SendSMSRequest",
    "get_call_status",
    "get_email_status",
    "get_sms_status",
    "make_call",
    "make_call_simple",
    "send_email",
    "send_email_simple",
    "send_sms",
    "send_sms_simple",
    "validate_call_config",
    "validate_email_config",
    "validate_sms_config",
]
