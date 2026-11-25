"""Jobs over many items, for the worker task pattern's ``fan-out`` rule:
each ``_answer`` stands for a model or provider call."""


async def _answer(item: str) -> str:
    return item


async def _answer_each(items: list[str]) -> None:
    for item in items:
        await _answer(item)


async def loops_itself() -> None:
    """A job that answers every item, one after another."""
    for item in ["a", "b"]:
        await _answer(item)


async def hands_a_loop_on() -> None:
    """A job whose service answers every item, one after another."""
    await _answer_each(["a", "b"])


async def awaits_in_a_comprehension() -> None:
    """One after another all the same."""
    _ = [await _answer(item) for item in ["a", "b"]]


class _Queue:
    async def claim(self, key: str) -> bool:
        return True

    async def enqueue_task(self, name: str, item: str) -> None:
        return None


pools = cache = _Queue()


async def fans_out() -> None:
    """A task per item, queued once each: the queue runs them."""
    for item in ["a", "b"]:
        if await cache.claim(item):
            await pools.enqueue_task("answer_task", item)
