"""Comms service: email (Resend), SMS and voice calls (Twilio).

``service`` is the entry point; its logic lives in ``domains`` (email,
telephony, inbound). No database of its own beyond ``models``; the spine
is ``health``.
"""
