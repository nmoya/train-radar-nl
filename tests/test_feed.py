from __future__ import annotations

import requests

from google.transit import gtfs_realtime_pb2

import src.feed as feed_module
from src.feed import FeedFetchResult, FeedPoller, fetch_feed

from .support import make_feed


class StubResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._raise_error = raise_error

    def raise_for_status(self) -> None:
        if self._raise_error is not None:
            raise self._raise_error


def test_fetch_feed_handles_not_modified(app_config) -> None:
    class Session:
        def get(self, url, headers, timeout):
            assert url == app_config.feed_url
            assert headers["If-None-Match"] == "etag"
            assert headers["If-Modified-Since"] == "last"
            assert headers["User-Agent"] == app_config.user_agent
            assert timeout == 30
            return StubResponse(status_code=304)

    result = fetch_feed(Session(), app_config, "etag", "last")

    assert result == FeedFetchResult(feed=None, etag="etag", last_modified="last")


def test_fetch_feed_parses_protobuf_and_headers(app_config) -> None:
    feed = make_feed(timestamp=123)

    class Session:
        def get(self, url, headers, timeout):
            assert url == app_config.feed_url
            return StubResponse(
                content=feed.SerializeToString(),
                headers={"ETag": "new", "Last-Modified": "date"},
            )

    result = fetch_feed(Session(), app_config, None, None)

    assert isinstance(result.feed, gtfs_realtime_pb2.FeedMessage)
    assert result.feed.header.timestamp == 123
    assert result.etag == "new"
    assert result.last_modified == "date"


def test_feed_poller_load_static_gtfs_reports_errors(app_config, monkeypatch) -> None:
    poller = FeedPoller(app_config, session=object())
    monkeypatch.setattr(feed_module, "load_static_gtfs", lambda session, config: "ok")
    assert poller.load_static_gtfs().data == "ok"

    def raise_request_error(session, config):
        raise requests.RequestException("boom")

    monkeypatch.setattr(feed_module, "load_static_gtfs", raise_request_error)
    assert poller.load_static_gtfs().error == "Static GTFS load failed: boom"

    def raise_parse_error(session, config):
        raise RuntimeError("bad zip")

    monkeypatch.setattr(feed_module, "load_static_gtfs", raise_parse_error)
    assert poller.load_static_gtfs().error == "Static GTFS parse failed: bad zip"


def test_feed_poller_update_fetches_and_caches_feed(app_config, monkeypatch) -> None:
    session = object()
    poller = FeedPoller(app_config, session=session)
    feed = make_feed(timestamp=1234)
    calls: list[tuple[object, object, object, object]] = []

    def fake_fetch(session_arg, config_arg, etag, last_modified):
        calls.append((session_arg, config_arg, etag, last_modified))
        return FeedFetchResult(feed=feed, etag="etag-2", last_modified="lm-2")

    times = iter([100.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(feed_module, "fetch_feed", fake_fetch)
    monkeypatch.setattr(feed_module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(feed_module.time, "time", lambda: 9999)

    update = poller.update()

    assert calls == [(session, app_config, None, None)]
    assert update.feed is feed
    assert update.feed_timestamp == 1234
    assert update.version == 1
    assert poller._etag == "etag-2"
    assert poller._last_modified == "lm-2"


def test_feed_poller_update_respects_poll_interval_and_errors(app_config, monkeypatch) -> None:
    session = object()
    poller = FeedPoller(app_config, session=session)
    poller._cached_feed = make_feed(timestamp=50)
    poller._cached_feed_timestamp = 50
    poller._version = 3
    poller._last_poll_started_at = 90.0
    monotonic_values = iter([100.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(feed_module.time, "monotonic", lambda: next(monotonic_values))

    update = poller.update()

    assert update.feed_timestamp == 50
    assert update.version == 3
    assert update.next_poll_in_seconds == 20

    poller._last_poll_started_at = None
    monkeypatch.setattr(
        feed_module,
        "fetch_feed",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("down")),
    )
    monkeypatch.setattr(feed_module.time, "monotonic", lambda: 100.0)
    error_update = poller.update()

    assert error_update.error == "Feed update failed: down"
    assert error_update.feed_timestamp == 50
    assert error_update.version == 3


def test_feed_poller_close_only_closes_owned_session(app_config) -> None:
    external_closed = []

    class ExternalSession:
        def close(self):
            external_closed.append(True)

    owned_closed = []

    class OwnedSession:
        def close(self):
            owned_closed.append(True)

    external_session = ExternalSession()
    poller = FeedPoller(app_config, session=external_session)
    poller.close()
    assert external_closed == []

    original_session_factory = feed_module.requests.Session
    feed_module.requests.Session = OwnedSession
    try:
        owned_poller = FeedPoller(app_config)
        owned_poller.close()
    finally:
        feed_module.requests.Session = original_session_factory

    assert owned_closed == [True]
