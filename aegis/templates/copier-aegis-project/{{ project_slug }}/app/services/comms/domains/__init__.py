"""The service's logic, a package each:

- ``telephony``: SMS and voice calls, through the Twilio client
  (``adapters.twilio``); email is ``adapters.resend``
- ``inbound``: what Resend and Twilio send back (delivery events, replies)
"""
