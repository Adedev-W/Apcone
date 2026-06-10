from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile


class FileStorageService:
    COPY_BUFFER_SIZE = 1024 * 1024

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def save_upload(self, job_id: UUID, upload_file: UploadFile) -> Path:
        job_dir = self.base_dir / str(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        filename = self._sanitize_filename(upload_file.filename or "upload.bin")
        destination = job_dir / filename
        with destination.open("wb") as output:
            shutil.copyfileobj(upload_file.file, output, length=self.COPY_BUFFER_SIZE)
        return destination

    def resolve(self, stored_path: str) -> Path:
        return Path(stored_path)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        safe = filename.replace("\\", "_").replace("/", "_").strip()
        return safe or "upload.bin"
