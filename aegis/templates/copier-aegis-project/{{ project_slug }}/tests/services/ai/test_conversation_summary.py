"""A long conversation keeps what fell out of view, condensed.

The history replayed each turn is budgeted by size, cut a slab at a time,
and what was said only in the turns that fell out was gone. Those turns
fold, on the worker, into a running summary kept on the conversation,
and the summary rides ahead of the history. It moves only when the cut
does, so a prompt cache keeps reusing what the last turn sent.
"""

from typing import Any

import pytest

from app.core.cache import CacheService
from app.core.discovery import present
from app.services.ai.domains.chat import summary
from app.services.ai.domains.chat.conversation import ConversationManager
from app.services.ai.domains.chat.self_context import begin_turn_context, current_turn
from app.services.ai.jobs import fold_conversation_job
from app.services.ai.models import AIProvider, Conversation, MessageRole
from tests.services.ai._threads import built, thread

EARLIER = "Earlier in this conversation"


def _conversation(turns: int, size: int = 100) -> Conversation:
    """``turns`` messages of ``size`` characters, the first naming the dog,
    then the question being asked now."""
    texts = ["x" * size] * turns
    if texts:
        texts[0] = "Our dog is called Biscuit.".ljust(size, ".")
    return thread(texts, "What is the dog called?")


def _build(conversation: Conversation, budget: int) -> str:
    begin_turn_context()
    return built(conversation, budget)


@pytest.fixture
def folds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stack whose worker folds."""
    monkeypatch.setattr(summary, "FOLDS", True)


class TestTheSummaryRides:
    def test_an_early_turn_answers_from_the_summary(self, folds: None) -> None:
        """The dog's name fell out of the window; the summary still has it."""
        conversation = _conversation(40)
        _build(conversation, budget=1_000)
        upto = current_turn().fold_to  # type: ignore[union-attr]
        conversation.metadata[summary.SUMMARY_KEY] = {
            "text": "They have a dog called Biscuit.",
            "through": upto,
        }

        built = _build(conversation, budget=1_000)

        assert "Our dog is called Biscuit" not in built  # out of view
        assert built.index(EARLIER) < built.index("Biscuit")
        assert built.index("Biscuit") < built.index("What is the dog called?")

    def test_the_summary_never_rides_beside_turns_it_covers(self, folds: None) -> None:
        """The budget grew (a model with a longer context) and its cut
        landed before what the summary reaches: the summary rode beside
        the turns it already tells. The history starts where it ends."""
        conversation = _conversation(40)
        conversation.metadata[summary.SUMMARY_KEY] = {
            "text": "They have a dog called Biscuit.",
            "through": 30,
        }

        built = _build(conversation, budget=3_000)

        assert current_turn().messages_dropped == 30  # type: ignore[union-attr]
        assert built.index(EARLIER) < built.index("What is the dog called?")

    def test_a_thread_inside_the_window_carries_no_summary(self) -> None:
        conversation = _conversation(4)
        conversation.metadata[summary.SUMMARY_KEY] = {"text": "STALE", "through": 2}

        assert "STALE" not in _build(conversation, budget=10_000)

    def test_the_summary_moves_only_with_the_cut(self, folds: None) -> None:
        """A fold landing between two cuts would change what every turn
        replays from the summary on. The cut waits for the fold it is due,
        so the summary and the history's start change in the same turn."""
        conversation = _conversation(2)
        seen: list[tuple[str, int]] = []
        for turn in range(80):
            built = _build(conversation, budget=1_000)
            stamp = current_turn()
            assert stamp is not None
            head = built.split("\n\n")[0]
            seen.append(
                (head if head.startswith(EARLIER) else "", stamp.messages_dropped)
            )
            # The worker folds what the turn says is due before the next.
            if upto := stamp.fold_to:
                conversation.metadata[summary.SUMMARY_KEY] = {
                    "text": f"{EARLIER}: through {upto}.",
                    "through": upto,
                }
            conversation.messages[-1].content = f"question {turn}".ljust(100, ".")
            conversation.add_message(MessageRole.ASSISTANT, "a".ljust(100, "."))
            conversation.add_message(MessageRole.USER, "What is the dog called?")

        changed = [
            (a[0] != b[0], a[1] != b[1]) for a, b in zip(seen, seen[1:]) if a != b
        ]
        assert any(moved for moved, _ in changed)  # the summary did move
        assert all(start for moved, start in changed if moved)

    def test_without_a_worker_the_cut_does_not_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing folds where no worker runs: the history cuts as it
        always did, and no fold is ever due."""
        monkeypatch.setattr(summary, "FOLDS", False)

        built = _build(_conversation(40), budget=1_000)

        assert "Our dog is called Biscuit" not in built
        assert EARLIER not in built
        assert current_turn().fold_to == 0  # type: ignore[union-attr]


class TestTheFold:
    async def test_fallen_turns_fold_into_the_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conversation = _conversation(40)
        conversation.metadata[summary.SUMMARY_KEY] = {
            "text": "Earlier: hello.",
            "through": 0,
        }
        asked: list[str] = []

        async def condense(prompt: str, **_: Any) -> str:
            asked.append(prompt)
            return "They have a dog called Biscuit."

        monkeypatch.setattr(summary, "_condense", condense)

        assert await summary.fold(conversation, upto=30) is True
        kept = conversation.metadata[summary.SUMMARY_KEY]
        assert kept == {"text": "They have a dog called Biscuit.", "through": 30}
        assert "Earlier: hello." in asked[0]  # the summary so far is folded in
        assert "Our dog is called Biscuit" in asked[0]  # with the turns that fell

    async def test_a_fold_already_done_is_not_paid_for_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conversation = _conversation(40)
        conversation.metadata[summary.SUMMARY_KEY] = {"text": "Done.", "through": 30}

        async def condense(prompt: str, **_: Any) -> str:
            raise AssertionError("no model call for work already done")

        monkeypatch.setattr(summary, "_condense", condense)

        assert await summary.fold(conversation, upto=30) is False


@pytest.mark.skipif(not present("app.components.worker"), reason="no worker")
class TestOffTheRequestPath:
    async def test_a_due_fold_is_queued_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The summary does not move until a fold finishes, so every turn
        while one runs finds it due again: queued once per cut, on any
        worker engine."""
        from app.components.worker import pools

        enqueued: list[tuple[object, ...]] = []

        async def enqueue(name: str, _queue: str, *args: object, **_: object) -> None:
            enqueued.append((name, *args))

        cache = CacheService()
        monkeypatch.setattr(pools, "enqueue_task", enqueue)
        monkeypatch.setattr(summary, "get_cache", lambda: cache)
        monkeypatch.setattr(summary, "FOLDS", True)

        for _turn in range(3):
            await summary.enqueue_fold("c1", 20)
        await summary.enqueue_fold("c1", 30)

        assert enqueued == [
            ("fold_conversation_task", "c1", 20),
            ("fold_conversation_task", "c1", 30),
        ]

    async def test_a_failed_enqueue_never_fails_the_turn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.components.worker import pools

        async def broken(*_: object, **__: object) -> None:
            raise ConnectionError("redis is down")

        monkeypatch.setattr(pools, "enqueue_task", broken)
        monkeypatch.setattr(summary, "get_cache", CacheService)
        monkeypatch.setattr(summary, "FOLDS", True)

        await summary.enqueue_fold("c1", 20)


class TestATurnDoesNotUndoTheFold:
    # One conversation read back after each writer, on purpose.
    @pytest.mark.queryspy(allow_n_plus_one=True)
    async def test_the_job_writes_only_the_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A turn may land while the fold runs: the job keeps the metadata
        as it is now and adds the summary, rather than saving the whole
        conversation it read earlier."""
        manager = ConversationManager()
        conversation = await manager.create_conversation(
            provider=AIProvider.OLLAMA, model="test-model", user_id="u1"
        )
        for index in range(30):
            role = MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT
            conversation.add_message(role, f"turn {index}")
        await manager.save_conversation(conversation)

        async def condense(prompt: str, **_: Any) -> str:
            later = await manager.get_conversation(conversation.id)
            assert later is not None
            later.metadata["last_activity"] = "meanwhile"
            await manager.save_conversation(later)
            return "Thirty turns."

        monkeypatch.setattr(summary, "_condense", condense)

        assert await fold_conversation_job(conversation.id, 20) is True

        stored = await manager.get_conversation(conversation.id)
        assert stored is not None
        assert stored.metadata[summary.SUMMARY_KEY] == {
            "text": "Thirty turns.",
            "through": 20,
        }
        assert stored.metadata["last_activity"] == "meanwhile"

    # One conversation read back after each writer, on purpose.
    @pytest.mark.queryspy(allow_n_plus_one=True)
    async def test_a_stale_turn_keeps_the_newer_summary(self) -> None:
        """A turn read the conversation before the fold landed; saving it
        must not put back the older summary."""
        manager = ConversationManager()
        conversation = await manager.create_conversation(
            provider=AIProvider.OLLAMA, model="test-model", user_id="u1"
        )
        conversation.metadata[summary.SUMMARY_KEY] = {"text": "old", "through": 10}
        await manager.save_conversation(conversation)
        stale = await manager.get_conversation(conversation.id)
        newer = await manager.get_conversation(conversation.id)
        assert stale is not None and newer is not None

        newer.metadata[summary.SUMMARY_KEY] = {"text": "new", "through": 30}
        await manager.save_conversation(newer)
        stale.add_message(MessageRole.USER, "and another thing")
        await manager.save_conversation(stale)

        stored = await manager.get_conversation(conversation.id)
        assert stored is not None
        assert stored.metadata[summary.SUMMARY_KEY] == {"text": "new", "through": 30}
