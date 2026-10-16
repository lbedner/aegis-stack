"""``storage``: the object store, checked against the rows that name it.

``check`` prints each missing key alone on stdout, so a script (``aegis
deploy-upload-storage``) reads them as a list; what a person reads goes
to stderr.
"""

import typer

from app.cli import theme
from app.core.db import get_async_session
from app.core.storage import get_storage, missing_objects

app = typer.Typer(help="Check the object store against the rows that name it.")


@app.command()
async def check() -> None:
    """Every stored file a row names is in the store; exits 1 naming any
    that are not."""
    async with get_async_session() as session:
        missing = await missing_objects(session)
    backend = get_storage().backend_name
    if not missing:
        theme.good(
            f"Every stored file a row names is in the {backend} store.", err=True
        )
        return
    for key in missing:
        typer.echo(key)
    theme.bad(
        f"{len(missing)} stored files are missing from the {backend} store.", err=True
    )
    raise typer.Exit(1)
