"""A thread for the history builder's tests, and the builder run on it."""

from app.services.ai.models import AIProvider, Conversation, MessageRole


def thread(texts: list[str], asking: str) -> Conversation:
    """A conversation of ``texts``, oldest first, the user and the
    assistant taking turns (the user first), then ``asking``: the question
    being asked now."""
    conversation = Conversation(id="c1", provider=AIProvider.OLLAMA, model="test-model")
    for index, text in enumerate(texts):
        role = MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT
        conversation.add_message(role, text)
    conversation.add_message(MessageRole.USER, asking)
    return conversation


def built(conversation: Conversation, budget: int) -> str:
    """The history builder, which reads nothing off ``self``."""
    from app.services.ai.service.prompt import PromptMixin

    return PromptMixin._build_conversation_context(  # type: ignore[arg-type]
        None, conversation, history_budget=budget
    )
