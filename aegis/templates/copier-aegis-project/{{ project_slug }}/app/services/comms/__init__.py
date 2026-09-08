"""Comms service: email (Resend), SMS and voice calls (Twilio).

One domain module per channel: ``email``, ``sms``, ``calls``; ``webhooks``
receives the providers' delivery callbacks. No database of its own beyond
``models``; the spine is ``health``.
"""
