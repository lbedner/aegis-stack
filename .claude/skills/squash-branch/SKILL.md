---
name: squash-branch
description: Use when collapsing a feature branch into a single commit before opening or merging a PR. Covers the non-interactive squash, dropping co-author trailers, and verifying the tree is unchanged.
---

# Squash branch

Collapse all of a branch's commits into one, authored by the committer, with a
clean message and no co-author trailers. Interactive rebase (`git rebase -i`)
is not available in this environment, so the squash uses `git reset --soft`
against the base, which produces the identical end state.

## When to use

Use when a feature branch has several work-in-progress commits that should land
as one commit.

Do NOT use on a shared branch others have based work on (rewriting its history
breaks their clones).

## Files that change

None. This operates on git history, not the working tree. The tree at HEAD is
byte-for-byte identical before and after; only the commit history collapses.

## Procedure

1. Confirm the base and that the branch is ahead of it with nothing behind:
   `git rev-list --count <base>..HEAD` (commits to squash) and
   `git rev-list --count HEAD..<base>` (must be 0; rebase onto `<base>` first if
   not).
2. Record the current tree to verify the squash later:
   `git rev-parse HEAD^{tree}`.
3. Collapse to staged changes without moving the working tree:
   `git reset --soft <base>`.
4. Stage any intended uncommitted additions with `git add`, leaving unrelated
   working-tree changes out.
5. Commit once with a clean message and no co-author or generated-by trailers:
   `git commit`. The commit is authored by the configured git identity.
6. Verify nothing changed: `git rev-parse HEAD^{tree}` must equal the value from
   step 2, and `git log --oneline <base>..HEAD` must show exactly one commit.

## Gates

- The post-squash tree hash must equal the pre-squash tree hash (step 6); a
  mismatch means content was dropped or added, not just recommitted.
- `git log --oneline <base>..HEAD` shows a single commit.

## Pitfalls

- `git reset --soft` leaves the index and working tree untouched, so
  uncommitted or untracked files are still present after it; stage deliberately
  in step 4 so unrelated changes do not get folded into the squash.
- Squashing rewrites history, so a branch already pushed needs a force push
  (`--force-with-lease`), which is an outward-facing action the user must
  approve.
- Writing a fresh commit message drops any co-author or generated-by trailers
  from the original commits, which is the intended cleanup; do not carry them
  forward.
