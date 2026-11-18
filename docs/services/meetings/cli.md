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
my-app meetings show <id>                # Status, notes and transcript
my-app meetings search "<words>"         # Lines and notes with any of the words (-n LIMIT)
my-app meetings series [ID]              # The series, or one in full
my-app meetings look-over [ID...]        # Read calls over again for moments (--series, --all)

```

## The runner

The runner and its tokens are the [runner component](../../components/runner.md)'s: `my-app runner run` and `my-app runner token`.
