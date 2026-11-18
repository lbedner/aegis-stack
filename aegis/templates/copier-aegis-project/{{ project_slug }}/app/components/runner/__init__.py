"""The runner: work the app sends out to a coding agent.

- ``runs`` - asking a run about a subject, claiming it, finishing it
- ``tokens`` - what a runner shows the app to claim and finish runs
- ``client`` - the runner itself: a process on another machine that
  claims runs over the API and answers each with a headless command

A service asks a run of an action about something of its own (a kind and
an id: a meeting's moment) and reads its runs back by that subject.
"""
