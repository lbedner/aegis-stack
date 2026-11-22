---
name: execute-issue
description: Use when handed a GitHub issue (number or URL) to execute end to end. Reads the issue, classifies the work, loads the matching workflow skill, runs it against the stated acceptance criteria, and reports results.
---

# Execute issue

Turn a detailed GitHub issue into an executed change. This skill is the router:
it does not itself know how to add a service or cut a release, it classifies the
work and hands off to the workflow skill that does, then holds the run to the
issue's acceptance criteria. Issues authored with the agent-task template
(`.github/ISSUE_TEMPLATE/agent-task.yml`) map field-for-field onto this run.

## When to use

Use when given an issue number or URL and asked to execute, implement, or "do"
it.

Do NOT use to triage, comment on, or plan an issue without implementing it. If
the issue is vague enough that the scope or acceptance criteria cannot be
restated concretely, stop and ask rather than guess.

## Files that change

This skill owns no fixed file list. The files that change are whatever the
classified workflow skill dictates. Reading order:

- The issue body and comments (via `gh issue view <n> --comments`).
- The matching workflow skill under `.claude/skills/<name>/SKILL.md`, whose
  `## Files that change` section is the authoritative list for the run.

Classification map (issue work type to skill):

- New business capability (auth, AI, payment, blog, finance): `add-service`
- New infrastructure or a variant axis (worker, scheduler, database, redis, a
  `*_backend` option): `add-component`
- Locale strings, translations: `i18n`
- A command on the `aegis` tool CLI: `add-cli-command`
- Version or rc release: `release`
- Template edits or backporting from a generated project: `template-dev`

An issue may span more than one type (a service that adds a CLI command and
locale strings). Load every matching skill and follow each for its slice.

## Procedure

1. Read the issue: `gh issue view <n> --comments`. Read the comments; they often
   correct the body (a burned-rc note, a moved file). Where a comment and the
   body disagree, the comment usually wins, but verify against the code.
2. Classify the work against the map above and name the skill(s) you will load.
   State the classification back to the user in one line.
3. Load each matching workflow skill and read its `## Files that change`,
   `## Procedure`, `## Gates`, and `## Pitfalls`.
4. Restate the issue's acceptance criteria in the session as an explicit
   checklist. This is the contract the run is measured against.
5. Verify the issue's claims against the code before writing anything. If the
   issue names a file, function, or flag that does not exist or has moved, stop
   and surface the contradiction rather than coding to a false premise.
6. Write the failing test first (per the loaded skill's TDD step), then
   implement following that skill's Procedure.
7. Run the loaded skill's gates. Fix what goes red.
8. Report results against each acceptance-criterion line one by one: met, not
   met, or blocked, with the evidence (test name, gate output). Do not claim a
   criterion is met without having exercised it.

## Gates

The gates are whichever the loaded workflow skill specifies (for example
`make check` plus a `test-stacks` or `test-template` target). Run exactly those;
do not substitute a lighter target for the one the skill names as the
before-done gate.

## Pitfalls

- An issue is a claim about the code, not the code itself; coding to the issue's
  described state without checking the real tree ships fixes for problems that
  do not exist. Surface the mismatch instead.
- Reporting a criterion as met because the code "should" satisfy it is not
  evidence; a criterion counts as met only after its test or gate has actually
  run green.
- Skipping the classification step and improvising the file list loses the
  hard-won completeness the workflow skills encode; always route through a
  skill, never freehand a workflow the skills already cover.
- A multi-type issue that loads only one skill misses a slice; re-scan the issue
  for CLI, i18n, and docs work that rides along with the main change.
