from __future__ import annotations

from rq import Worker

from app.core.config import get_settings
from app.tasks.rq_queue import get_pdf_queues


def main() -> None:
    settings = get_settings()
    queues = get_pdf_queues(settings)
    worker = Worker(queues, connection=queues[0].connection)
    worker.work()


if __name__ == "__main__":
    main()
