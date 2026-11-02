# Meetings CLI Commands

**Part of the Generated Project CLI** - See [CLI Reference](../../cli-reference.md#service-clis) for complete overview.

## Command Overview

```bash
# Agents
my-app meetings login                    # Sign the bot's Google account in, once
my-app meetings login --agent work       # Sign in another agent (--name, --email)

# Meetings
my-app meetings join <link>              # Send the bot in and wait (--agent, --bot-name)
my-app meetings leave <id>               # Ask it to leave
my-app meetings list                     # Newest first (-n LIMIT)
my-app meetings show <id>                # Status and transcript
my-app meetings look-over [ID...]        # Read calls over again for moments (--series, --all)

# Runner
my-app meetings runner                   # Answer waiting runs on this machine
my-app meetings runner-token create <name>   # A token, shown once (--owner)
my-app meetings runner-token list            # The live tokens
my-app meetings runner-token revoke <id>     # Revoke one
```

## Runner options

```bash
--command CMD    # Required: the command each run runs; {prompt} is its prompt (stdin without it)
--repo PATH      # Answer from a fresh worktree of this repository
--ref REF        # What each worktree checks out (origin/main)
--action NAME    # An action this runner answers (agent); repeat for more
--url URL        # The app (API_BASE_URL by default)
--token TOKEN    # Its runner token (or MEETINGS_RUNNER_TOKEN)
--once           # Answer one waiting run and stop
--poll SECONDS   # How often it looks while idle
```

See [The runner](moments.md#the-runner).
