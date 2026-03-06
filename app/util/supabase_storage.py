import os
from typing import Optional

import httpx
from fastapi import UploadFile


SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY: Optional[str] = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_INVOICES_BUCKET: str = os.getenv("SUPABASE_INVOICES_BUCKET", "invoices")


class SupabaseNotConfiguredError(RuntimeError):
    """Raised when required Supabase settings are missing."""


def _ensure_configured() -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise SupabaseNotConfiguredError(
            "Supabase storage is not configured. "
            "Please set SUPABASE_URL and SUPABASE_SERVICE_KEY in your environment."
        )


async def upload_invoice_file(file: UploadFile, object_name: str) -> str:
    """Upload an invoice file to Supabase Storage.

    Returns the stored object path (bucket/path/filename) suitable for
    persisting as file_path in the database.
    """

    _ensure_configured()

    storage_url = (
        SUPABASE_URL.rstrip("/")
        + "/storage/v1/object/"
        + f"{SUPABASE_INVOICES_BUCKET}/{object_name}"
    )

    file_bytes = await file.read()
    content_type = file.content_type or "application/octet-stream"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            storage_url,
            content=file_bytes,
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "apikey": SUPABASE_SERVICE_KEY or "",
                "Content-Type": content_type,
                # Allow overwriting existing objects with the same name
                "x-upsert": "true",
            },
        )
        response.raise_for_status()

    # We store the relative path; front-end or another service can
    # construct a public URL if needed.
    return f"{SUPABASE_INVOICES_BUCKET}/{object_name}"
