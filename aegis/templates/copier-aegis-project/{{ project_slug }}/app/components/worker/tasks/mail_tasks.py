"""Reading a file of mail as a worker task (arq form).

Registered in the system queue so no extra worker process is needed. The
body imports the mail service lazily: a worker stack without it still
imports this module and simply never receives the task.
"""

from typing import Any


async def mail_import_task(
    ctx: dict[str, Any],
    job_id: str,
    storage_key: str,
    file_name: str,
    owner_user_id: int | None,
) -> dict[str, Any]:
    from app.services.mail.jobs import run_mail_import_job

    return await run_mail_import_job(job_id, storage_key, file_name, owner_user_id)
