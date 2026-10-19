"""Comms service: email (Resend), SMS and voice calls (Twilio).

``service`` is the entry point; its logic lives in ``domains`` (telephony,
inbound), what it talks to in ``adapters`` (Resend, Twilio). No database of its own beyond ``models``; the spine
is ``health``.
"""
