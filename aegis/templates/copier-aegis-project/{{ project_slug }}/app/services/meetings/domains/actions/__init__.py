"""Actions: what can be done with a moment heard in a call.

- ``registry`` - each action by name: the kinds of moment it takes, its
  label, how it frames its prompt, and where it runs (in the browser, in
  the app, or on a runner on another machine)
- ``prompt`` - what an action is given: the moment and what led to it
- ``runs`` - asking an action, claiming the run, finishing it
- ``tokens`` - what a runner shows the app to claim and finish runs
- ``ask_ai`` - the stack's own model answering (where it has one)
"""
