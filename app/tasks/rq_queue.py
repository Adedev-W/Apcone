from __future__ import annotations

from redis import Redis
from rq import Queue

from app.core.config import Settings


def get_redis_connection(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        health_check_interval=settings.redis_health_check_interval_seconds,
        socket_keepalive=True,
    )


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
