"""The Overseer dashboard bootstrap, in pieces.

``main.setup_dashboard`` used to be one 1,100-line function holding the
whole screen: the header chrome, the three view containers, the refresh
cycle, the background loops and the card factory, all of it wired
together by closure capture. This package is those pieces with their
dependencies named as parameters instead:

* ``chrome`` - the header and the buttons on it
* ``body`` - stack / cards / diagram, and the toggle that cycles them
* ``cards`` - one component card, and reading a status payload
* ``refresh`` - one pass over ``/health/detailed``
* ``loops`` - the tasks that keep calling it

``setup_dashboard`` is now construction plus wiring, which is all it
ever should have been.
"""
