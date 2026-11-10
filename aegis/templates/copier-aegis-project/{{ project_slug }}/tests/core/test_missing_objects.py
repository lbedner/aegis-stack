"""``missing_objects``: the stored objects rows name and the store lacks."""

from sqlalchemy import Table
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import FilesystemStorage, content_key, missing_objects


async def test_missing_objects_are_the_ones_rows_name_and_the_store_lacks(
    async_db_session: AsyncSession, files: FilesystemStorage, key_holder: Table
) -> None:
    """A copy that brought the database and not the store (a first deploy,
    a restore) leaves rows naming files that are not there: a broken page
    that nothing finds until someone opens it. ``AutoString`` is what a
    SQLModel ``str`` field is; a check that saw only ``String`` found none.
    A chat attachment or a paste is named inside JSON, not in a column."""
    kept = await files.put(b"kept")
    gone = content_key(b"gone")
    attached = content_key(b"an attachment")
    await async_db_session.execute(
        key_holder.insert(),
        [
            {"file_key": kept, "payee_key": "acme", "meta_data": {"a": 1}},
            {"file_key": gone, "payee_key": None, "meta_data": None},
            {
                "file_key": None,
                "payee_key": None,
                "meta_data": {"attachments": [{"key": attached}, {"key": kept}]},
            },
        ],
    )
    assert await missing_objects(async_db_session) == sorted([gone, attached])
