"""The whole app's request guards and logging, through the real app object.

TestClient without a `with` block never runs the lifespan, so no sync loop,
wake-word listener or migrations start here.
"""

import logging
import warnings

import pytest
from fastapi.testclient import TestClient

from app import logging_setup
from app.main import app


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost:8000")


def test_other_websites_get_no_cross_site_access(client):
    # A page in the Browser tab trying to read the calendar.
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_a_cross_site_preflight_is_not_approved(client):
    response = client.options(
        "/api/events",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_the_kiosk_page_still_reaches_the_api(client):
    assert client.get("/api/health").status_code == 200
    assert TestClient(app, base_url="http://127.0.0.1:8000").get("/api/health").status_code == 200


def test_requests_addressed_to_another_host_name_are_refused():
    # DNS rebinding: a page's own domain pointed at 127.0.0.1.
    response = TestClient(app, base_url="http://evil.example:8000").get("/api/health")

    assert response.status_code == 400


def access_record(method, status):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:5000", method, "/api/timers", "1.1", status), None)  # fmt: skip


@pytest.mark.parametrize(
    "method, status, kept",
    [
        ("GET", 200, False),  # the per-second polling
        ("GET", 304, False),
        ("GET", 404, True),  # failures stay visible
        ("GET", 500, True),
        ("POST", 200, True),  # changes stay visible
        ("DELETE", 204, True),
    ],
)
def test_only_successful_reads_are_dropped_from_the_access_log(method, status, kept):
    assert logging_setup.QuietSuccessfulReads().filter(access_record(method, status)) is kept


def test_the_apps_own_info_messages_are_logged():
    logging_setup.configure_logging()

    assert logging.getLogger("app.display").isEnabledFor(logging.INFO)
    assert logging.getLogger("app").handlers  # without one, Python only prints warnings and worse


def test_configuring_twice_adds_nothing_twice():
    logging_setup.configure_logging()
    handlers = len(logging.getLogger("app").handlers)
    filters = len(logging.getLogger("uvicorn.access").filters)

    logging_setup.configure_logging()

    assert len(logging.getLogger("app").handlers) == handlers
    assert len(logging.getLogger("uvicorn.access").filters) == filters


def test_calendar_data_stays_out_of_the_log():
    # The caldav library's warnings quote raw event text (descriptions, addresses).
    logging_setup.configure_logging()

    assert not logging.getLogger("caldav").isEnabledFor(logging.WARNING)
    assert logging.getLogger("caldav").isEnabledFor(logging.ERROR)


def test_the_no_gpu_warning_is_silenced_but_other_warnings_are_not():
    logging_setup.configure_logging()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        logging_setup.configure_logging()  # re-applies the filter inside this block
        warnings.warn("Specified provider 'CUDAExecutionProvider' is not in available provider names.", UserWarning)
        warnings.warn("something else worth seeing", UserWarning)

    assert [str(w.message) for w in caught] == ["something else worth seeing"]
