"""Illiana's review threads, for the conformance job in
``.github/workflows/stack-matrix.yml`` (the rules are in
``docs/services/index.md``). It reads the new places ``patterns check``
wrote (``PATTERNS_FOUND``), pointed at the templates by
``scripts/template_annotations.py --found``, each with the key the gate's
baseline knows it by, and brings her threads up to them: one per new place
the diff shows, posted as one review; fixed ones resolved, a blocking one
resolved while it stands reopened, all in one request. No file (the check
did not finish) and nothing is touched.

    python scripts/illiana_threads.py <found.json>

with ``GH_TOKEN``, ``REPO`` (owner/name), ``PR`` and ``SHA`` (the head
commit) set; it talks to GitHub through ``gh``.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
MARK = "<!-- illiana-spot: {} -->"
MARKED = re.compile(r"<!-- illiana-spot: (.+?) -->")


class Spot(NamedTuple):
    """One new place, on its template line (None: no line has its text)."""

    path: str
    line: int | None
    check: str
    title: str
    why: str
    action: str
    blocking: bool
    key: str


class Thread(NamedTuple):
    """One of her review threads, open or resolved."""

    id: str
    key: str
    resolved: bool


class Plan(NamedTuple):
    post: list[Spot]
    resolve: list[Thread]
    reopen: list[Thread]


def spots(found: Path) -> list[Spot] | None:
    """The places ``found`` holds; None when there is no file."""
    if not found.exists():
        return None
    return [
        Spot(**{field: place[field] for field in Spot._fields})
        for place in json.loads(found.read_text())["found"]
    ]


def commentable(patch: str) -> set[int]:
    """The new side's lines a diff shows (added, or around a change): the
    only lines GitHub takes a review comment on."""
    shown: set[int] = set()
    at = 0
    for row in patch.splitlines():
        if hunk := HUNK.match(row):
            at = int(hunk.group(1))
        elif row.startswith(("-", "\\")):
            continue
        elif at:
            shown.add(at)
            at += 1
    return shown


def nearest(lines: Sequence[str], text: str, line: int) -> int | None:
    """The line of ``lines`` with ``text`` nearest ``line`` (None if none)."""
    same = [n for n, there in enumerate(lines, 1) if there.strip() == text]
    return min(same, key=lambda n: abs(n - line), default=None)


def plan(found: list[Spot], shown: dict[str, set[int]], had: list[Thread]) -> Plan:
    """Post each new place the diff shows, once; resolve her open threads
    whose place is gone; reopen a blocking one resolved while it stands."""
    keys = {s.key for s in found}
    blocking = {s.key for s in found if s.blocking}
    known = {t.key for t in had}
    post: dict[str, Spot] = {}
    for spot in found:
        if spot.key not in known and spot.line in shown.get(spot.path, set()):
            post.setdefault(spot.key, spot)
    return Plan(
        post=list(post.values()),
        resolve=[t for t in had if not t.resolved and t.key not in keys],
        reopen=[t for t in had if t.resolved and t.key in blocking],
    )


def body(spot: Spot) -> str:
    """A thread's first comment, headed as her summary heads a finding
    (``pattern_review.markdown``, in the template), and keyed."""
    weight = "blocks" if spot.blocking else "advisory"
    head = f"**{spot.title}** · `{spot.check}` · {weight}"
    said = spot.why if spot.action == spot.title else f"{spot.why} {spot.action}"
    return f"{head}\n\n{said}\n\n{MARK.format(spot.key)}"


def key_of(text: str) -> str | None:
    """The place a thread is about, from its first comment."""
    return m.group(1) if (m := MARKED.search(text)) else None


def mutations(todo: Plan, sha: str) -> tuple[str, dict[str, Any]]:
    """Every reply, resolve and reopen as one GraphQL request (aliased
    mutations run in order): a fixed thread replied to, then resolved; a
    standing one reopened, then replied to."""
    # GitHub refuses a declared variable the request does not use.
    variables: dict[str, Any] = {}
    if todo.resolve:
        variables["fixed"] = f"Fixed in `{sha[:7]}`."
    if todo.reopen:
        variables["still"] = f"Still here at `{sha[:7]}`."
    steps = []
    for n, thread in enumerate(todo.resolve):
        variables[f"t{n}"] = thread.id
        steps += [_reply(f"r{n}", f"t{n}", "fixed"), _resolve(f"s{n}", f"t{n}", True)]
    for n, thread in enumerate(todo.reopen):
        variables[f"o{n}"] = thread.id
        steps += [_resolve(f"u{n}", f"o{n}", False), _reply(f"q{n}", f"o{n}", "still")]
    typed = {"fixed": "String!", "still": "String!"}
    params = ", ".join(f"${k}: {typed.get(k, 'ID!')}" for k in variables)
    return f"mutation({params}) {{\n" + "\n".join(steps) + "\n}", variables


def _reply(alias: str, thread: str, said: str) -> str:
    return (
        f"  {alias}: addPullRequestReviewThreadReply(input: "
        f"{{pullRequestReviewThreadId: ${thread}, body: ${said}}}) "
        "{ clientMutationId }"
    )


def _resolve(alias: str, thread: str, resolve: bool) -> str:
    name = "resolveReviewThread" if resolve else "unresolveReviewThread"
    return f"  {alias}: {name}(input: {{threadId: ${thread}}}) {{ clientMutationId }}"


def _gh(*args: str, payload: dict[str, Any] | None = None) -> Any:
    given = ("--input", "-") if payload is not None else ()
    run = subprocess.run(
        ["gh", "api", *args, *given],
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(run.stdout) if run.stdout.strip() else None


def _graphql(query: str, variables: dict[str, Any]) -> Any:
    return _gh("graphql", payload={"query": query, "variables": variables})["data"]


THREADS = """query($owner: String!, $name: String!, $pr: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $pr) {
    reviewThreads(first: 100) { nodes {
      id isResolved comments(first: 1) { nodes { body } } } } } } }"""


def _threads(repo: str, pr: int) -> list[Thread]:
    """Her threads: the ones whose first comment carries a key."""
    owner, name = repo.split("/")
    # ponytail: a pull request's first 100 threads; paginate if one outgrows it
    data = _graphql(THREADS, {"owner": owner, "name": name, "pr": pr})
    found = []
    for node in data["repository"]["pullRequest"]["reviewThreads"]["nodes"]:
        first = node["comments"]["nodes"]
        if first and (key := key_of(first[0]["body"])):
            found.append(Thread(node["id"], key, node["isResolved"]))
    return found


def _shown(repo: str, pr: int) -> dict[str, set[int]]:
    """Each changed file's commentable lines (``--paginate`` merges pages)."""
    files = _gh(f"repos/{repo}/pulls/{pr}/files?per_page=100", "--paginate")
    return {f["filename"]: commentable(f.get("patch") or "") for f in files}


@cache
def _lines(path: str, sha: str = "") -> tuple[str, ...]:
    """A file's lines as checked out, or at ``sha``."""
    if not sha:
        file = Path(path)
        return tuple(file.read_text().splitlines()) if file.exists() else ()
    shown = subprocess.run(
        ["git", "show", f"{sha}:{path}"], capture_output=True, text=True
    )
    return tuple(shown.stdout.splitlines()) if shown.returncode == 0 else ()


def _on_head(spot: Spot, sha: str) -> Spot:
    """``spot`` on the head commit's line with its text: CI checks out the
    merge commit, and a change on the base above it moves the line."""
    if spot.line is None:
        return spot
    here = _lines(spot.path)
    text = here[spot.line - 1].strip() if spot.line <= len(here) else ""
    return spot._replace(line=nearest(_lines(spot.path, sha), text, spot.line))


def sync(found: list[Spot], repo: str, pr: int, sha: str) -> Plan:
    """The pull request's threads brought up to ``found`` at ``sha``."""
    on_head = [_on_head(s, sha) for s in found]
    todo = plan(on_head, _shown(repo, pr), _threads(repo, pr))
    if todo.resolve or todo.reopen:
        _graphql(*mutations(todo, sha))
    if todo.post:
        review = {
            "commit_id": sha,
            "event": "COMMENT",
            "body": "New findings, each on its line.",
            "comments": [
                {"path": s.path, "line": s.line, "side": "RIGHT", "body": body(s)}
                for s in todo.post
            ],
        }
        _gh(f"repos/{repo}/pulls/{pr}/reviews", "--method", "POST", payload=review)
    return todo


def main(found_at: Path) -> str:
    """What was done, said in one line."""
    found = spots(found_at)
    if found is None:
        return "Illiana's threads: the check wrote no places; nothing touched"
    env = os.environ
    done = sync(found, env["REPO"], int(env["PR"]), env["SHA"])
    return (
        f"Illiana's threads: {len(done.post)} posted, {len(done.resolve)} "
        f"resolved, {len(done.reopen)} reopened"
    )


if __name__ == "__main__":
    print(main(Path(sys.argv[1])))
