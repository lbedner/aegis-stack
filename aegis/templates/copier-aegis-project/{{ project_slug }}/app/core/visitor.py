"""Who a request is, for what it owns: the one spelling auth and AI share.

Conversations and spend are owned by a string, the chat mount's user. A
signed-in user owns by user id. A guest (``auth[guest]``) signs in to one
shared account, so it owns by its session instead, ``guest:<session id>``:
two guests never share a conversation list or a budget, and every guest's
spend together is every owner starting ``guest:``.
"""

GUEST = "guest"
GUESTS = f"{GUEST}:"  # what every guest's owner id starts with
# The shared guest account's email, on a reserved domain no mail reaches;
# no one signs up with it (``UserCreate``).
GUEST_EMAIL = "guest@example.com"


def guest_visitor(session_id: str) -> str:
    """The owner id of the guest signed in as session ``session_id``."""
    return f"{GUESTS}{session_id}"


def is_guest_visitor(owner: str) -> bool:
    """Whether ``owner`` is a guest's session rather than a user."""
    return owner.startswith(GUESTS)
