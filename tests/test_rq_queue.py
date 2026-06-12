from __future__ import annotations

from types import SimpleNamespace

from app.core.config import Settings
from app.tasks.rq_queue import get_redis_connection
from app.workers import run_worker


def test_redis_connection_uses_timeout_and_keepalive_settings():
    settings = Settings(
        redis_url="redis://redis.example.test:6390/3",
        redis_socket_timeout_seconds=7.5,
        redis_socket_connect_timeout_seconds=2.5,
        redis_health_check_interval_seconds=15,
    )

    client = get_redis_connection(settings)

    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["host"] == "redis.example.test"
    assert kwargs["port"] == 6390
    assert kwargs["db"] == 3
    assert kwargs["socket_timeout"] == 7.5
    assert kwargs["socket_connect_timeout"] == 2.5
    assert kwargs["health_check_interval"] == 15
    assert kwargs["socket_keepalive"] is True


def test_worker_uses_configured_ttl(monkeypatch):
    settings = Settings(rq_worker_ttl_seconds=90)
    queue = SimpleNamespace(connection=object())
    captured = {}

    class FakeWorker:
        def __init__(self, queues, *, connection, worker_ttl):
            captured["queues"] = queues
            captured["connection"] = connection
            captured["worker_ttl"] = worker_ttl
            captured["worked"] = False

        def work(self):
            captured["worked"] = True

    monkeypatch.setattr(run_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(run_worker, "get_pdf_queues", lambda current_settings: [queue])
    monkeypatch.setattr(run_worker, "Worker", FakeWorker)

    run_worker.main()

    assert captured == {
        "queues": [queue],
        "connection": queue.connection,
        "worker_ttl": 90,
        "worked": True,
    }
