from __future__ import annotations

from redis import Redis
from rq import Queue

from app.core.config import Settings


def get_redis_connection(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url)


def get_pdf_queue(settings: Settings) -> Queue:
    return Queue(settings.pdf_queue_name, connection=get_redis_connection(settings))


def get_pdf_profile_queue(settings: Settings) -> Queue:
    return Queue(settings.pdf_profile_queue_name, connection=get_redis_connection(settings))


def get_pdf_fast_queue(settings: Settings) -> Queue:
    return Queue(settings.pdf_fast_queue_name, connection=get_redis_connection(settings))


def get_pdf_ocr_queue(settings: Settings) -> Queue:
    return Queue(settings.pdf_ocr_queue_name, connection=get_redis_connection(settings))


def get_pdf_queues(settings: Settings) -> list[Queue]:
    connection = get_redis_connection(settings)
    queue_names = [
        settings.pdf_profile_queue_name,
        settings.pdf_fast_queue_name,
        settings.pdf_ocr_queue_name,
        settings.pdf_queue_name,
    ]
    unique_names = list(dict.fromkeys(queue_names))
    return [Queue(name, connection=connection) for name in unique_names]
