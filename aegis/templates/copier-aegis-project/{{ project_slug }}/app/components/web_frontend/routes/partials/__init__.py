"""htmx fragment routes.

Partials return HTML fragments rather than whole pages: a route here backs
an ``hx-get``/``hx-post`` on some element and its response is swapped into
the DOM. Keep them beside the page that uses them, under a
``/partials/...`` path. A module that only exists with a service is
mounted under that service's gate in ``routes/pages.py`` (``overseer_auth``
with auth, ``overseer_blog`` with blog), since ``main.py`` renders the same
for every stack.
"""
