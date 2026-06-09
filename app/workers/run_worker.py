from __future__ import annotations

from rq import Worker

from app.core.config import get_settings
from app.tasks.rq_queue import get_pdf_queue


def main() -> None:
    settings = get_settings()
    queue = get_pdf_queue(settings)
    worker = Worker([queue], connection=queue.connection)
    worker.work()


if __name__ == "__main__":
    main()
