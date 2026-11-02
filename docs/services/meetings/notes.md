# Notes, People and Series

Once the bot leaves, agents write up the call. Every item cites the transcript lines it came from. Needs the AI service on pydantic-ai with a database; without it a meeting keeps its transcript only.

| What | Written by | What it holds |
|------|------------|---------------|
| **Notes** | `meeting-notes` | Summary, decisions, action items (who, what, by when) and open questions |
| **Threads** | `meeting-notes` | Commitments, earlier commitments that came up again, things said both ways, where each person stands |
| **People** | `meeting-guide` | How to work with each person: what they care about, how they like information, how they decide |
| **Series** | `meeting-themes` | For meetings on one link: what keeps coming up, and what was settled, shifted or still open |

- **Write them again** on the page rewrites any of them, after switching models, say. A failed rewrite keeps the old ones.
- Threads gather per person across meetings: what they said they would do, and whether they did.
- Guides are only about how someone works, never health, family, politics or religion.
- The writers are agent rows under "meetings" in Overseer's Agents: edit their prompt and model there. Each call is metered in AI spend (`meetings:notes`, `meetings:guide`, `meetings:themes`).
