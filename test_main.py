
"""Automated tests for OpsPulse.

Run:
    python -m pytest -v

Coverage:
    python -m pytest --cov=main --cov-report=term-missing --cov-report=html

Each test uses an isolated temporary SQLite database.
Network responses are mocked unless a test explicitly exercises
the destination-validation or connection-construction code.
"""

import asyncio
import http.client
import socket

import pytest
from fastapi.testclient import TestClient

import main as main_module


# ============================================================
# Fixtures and test helpers
# ============================================================

@pytest.fixture
def client(tmp_path, monkeypatch):
    """Run FastAPI with a temporary database and idle scheduler."""

    test_database = tmp_path / "opspulse_test.db"
    monkeypatch.setattr(main_module, "DB_PATH", test_database)

    async def idle_scheduler():
        await asyncio.Event().wait()

    monkeypatch.setattr(
        main_module,
        "background_scheduler",
        idle_scheduler,
    )

    with TestClient(main_module.app) as test_client:
        yield test_client


def create_monitor(
    client,
    name="Test Website",
    url="https://example.com",
    interval_seconds=60,
):
    """Create a monitor and return its JSON representation."""

    response = client.post(
        "/api/monitors",
        json={
            "name": name,
            "url": url,
            "interval_seconds": interval_seconds,
        },
    )

    assert response.status_code == 201, response.text
    return response.json()["monitor"]


def install_fake_http_client(monkeypatch, status_code):
    """Mock destination validation and the outbound HTTP operation."""

    monkeypatch.setattr(
        main_module,
        "validate_public_destination",
        lambda url: "93.184.216.34",
    )

    monkeypatch.setattr(
        main_module,
        "fetch_status_code_pinned",
        lambda url, pinned_ip: status_code,
    )


def install_fake_check(monkeypatch, callback):
    """Install a fake check callback that can return or raise."""

    monkeypatch.setattr(
        main_module,
        "validate_public_destination",
        lambda url: "93.184.216.34",
    )

    monkeypatch.setattr(
        main_module,
        "fetch_status_code_pinned",
        callback,
    )


# ============================================================
# Dashboard and API basics
# ============================================================

def test_dashboard_and_health_endpoints_work(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "OpsPulse" in home.text

    stylesheet = client.get("/static/styles.css")
    assert stylesheet.status_code == 200

    javascript = client.get("/static/app.js")
    assert javascript.status_code == 200

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["database"] == "ok"


def test_create_and_list_monitors(client):
    monitor = create_monitor(
        client,
        name="Portfolio Website",
        url="https://example.com",
    )

    assert monitor["name"] == "Portfolio Website"
    assert monitor["url"] == "https://example.com"
    assert monitor["active"] is True
    assert monitor["status"] == "unknown"

    response = client.get("/api/monitors")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["monitors"][0]["id"] == monitor["id"]


def test_nonexistent_monitor_returns_404(client):
    response = client.get("/api/monitors/999999")
    assert response.status_code == 404


def test_manual_check_of_missing_monitor_returns_404(client):
    response = client.post("/api/monitors/999999/check")
    assert response.status_code == 404


def test_update_missing_monitor_returns_404(client):
    response = client.patch(
        "/api/monitors/999999",
        json={"active": False},
    )
    assert response.status_code == 404


def test_delete_missing_monitor_returns_404(client):
    response = client.delete("/api/monitors/999999")
    assert response.status_code == 404


def test_check_history_limit_is_validated(client):
    monitor = create_monitor(client)

    response = client.get(
        f"/api/monitors/{monitor['id']}/checks?limit=0"
    )

    assert response.status_code == 422


# ============================================================
# URL and request validation
# ============================================================

def test_invalid_url_scheme_is_rejected(client):
    response = client.post(
        "/api/monitors",
        json={
            "name": "Invalid Website",
            "url": "ftp://example.com",
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 422


def test_invalid_url_port_is_rejected(client):
    response = client.post(
        "/api/monitors",
        json={
            "name": "Bad Port",
            "url": "https://example.com:invalid",
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 422


def test_url_with_credentials_is_rejected(client):
    response = client.post(
        "/api/monitors",
        json={
            "name": "Credential URL",
            "url": "https://user:password@example.com/",
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 422


def test_scoped_ipv6_hostname_is_rejected(client):
    response = client.post(
        "/api/monitors",
        json={
            "name": "Scoped IPv6",
            "url": "http://[fe80::1%25eth0]/",
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 422


def test_invalid_interval_is_rejected(client):
    response = client.post(
        "/api/monitors",
        json={
            "name": "Invalid Interval",
            "url": "https://example.com",
            "interval_seconds": 10,
        },
    )

    assert response.status_code == 422


def test_blank_monitor_name_is_rejected(client):
    response = client.post(
        "/api/monitors",
        json={
            "name": "   ",
            "url": "https://example.com",
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 422


def test_patch_without_fields_is_rejected(client):
    monitor = create_monitor(client)

    response = client.patch(
        f"/api/monitors/{monitor['id']}",
        json={},
    )

    assert response.status_code == 400


def test_patch_null_values_are_rejected(client):
    monitor = create_monitor(client)

    response = client.patch(
        f"/api/monitors/{monitor['id']}",
        json={"active": None},
    )

    assert response.status_code == 422


# ============================================================
# Monitor updates and deletion
# ============================================================

def test_monitor_can_be_updated_and_paused(client):
    monitor = create_monitor(client)

    response = client.patch(
        f"/api/monitors/{monitor['id']}",
        json={
            "name": "Updated Website",
            "active": False,
            "interval_seconds": 300,
        },
    )

    assert response.status_code == 200

    updated = response.json()["monitor"]
    assert updated["name"] == "Updated Website"
    assert updated["active"] is False
    assert updated["interval_seconds"] == 300

    response = client.patch(
        f"/api/monitors/{monitor['id']}",
        json={"active": True},
    )

    assert response.status_code == 200
    assert response.json()["monitor"]["active"] is True


def test_monitor_can_be_deleted(client):
    monitor = create_monitor(client)

    response = client.delete(
        f"/api/monitors/{monitor['id']}"
    )

    assert response.status_code == 200

    assert client.get(
        f"/api/monitors/{monitor['id']}"
    ).status_code == 404

    assert client.get(
        f"/api/monitors/{monitor['id']}/checks"
    ).status_code == 404


# ============================================================
# Successful checks, failed checks, and history
# ============================================================

def test_successful_check_is_saved_in_history(client, monkeypatch):
    monitor = create_monitor(client)
    install_fake_http_client(monkeypatch, status_code=200)

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is True
    assert result["status_code"] == 200
    assert result["latency_ms"] >= 0
    assert result["error"] is None

    history = client.get(
        f"/api/monitors/{monitor['id']}/checks"
    )

    assert history.status_code == 200
    assert history.json()["count"] == 1
    assert history.json()["checks"][0]["success"] is True


def test_failed_http_response_is_saved(client, monkeypatch):
    monitor = create_monitor(client)
    install_fake_http_client(monkeypatch, status_code=503)

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is False
    assert result["status_code"] == 503
    assert result["error"] == "HTTP 503"

    monitor_response = client.get(
        f"/api/monitors/{monitor['id']}"
    )

    assert monitor_response.json()["monitor"]["status"] == "down"


def test_redirect_status_is_counted_as_reachable(client, monkeypatch):
    monitor = create_monitor(client)
    install_fake_http_client(monkeypatch, status_code=302)

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200
    assert response.json()["check"]["success"] is True
    assert response.json()["check"]["status_code"] == 302


def test_uptime_is_calculated_from_recorded_checks(client, monkeypatch):
    monitor = create_monitor(client)

    responses = iter([200, 503])

    install_fake_check(
        monkeypatch,
        lambda url, pinned_ip: next(responses),
    )

    for _ in range(2):
        response = client.post(
            f"/api/monitors/{monitor['id']}/check"
        )
        assert response.status_code == 200

    monitor_response = client.get(
        f"/api/monitors/{monitor['id']}"
    )

    assert (
        monitor_response.json()["monitor"]["uptime_24h_percent"]
        == 50.0
    )

    stats = client.get("/api/stats").json()
    assert stats["checks_last_24h"] == 2
    assert stats["uptime_last_24h_percent"] == 50.0


def test_dashboard_statistics_include_check_results(
    client,
    monkeypatch,
):
    monitor = create_monitor(client)
    install_fake_http_client(monkeypatch, status_code=200)

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    stats = client.get("/api/stats").json()

    assert stats["total_monitors"] == 1
    assert stats["active_monitors"] == 1
    assert stats["up_monitors"] == 1
    assert stats["down_monitors"] == 0
    assert stats["checks_last_24h"] == 1
    assert stats["uptime_last_24h_percent"] == 100.0
    assert stats["average_latency_last_24h_ms"] is not None


def test_empty_dashboard_statistics_are_valid(client):
    stats = client.get("/api/stats").json()

    assert stats["total_monitors"] == 0
    assert stats["active_monitors"] == 0
    assert stats["up_monitors"] == 0
    assert stats["down_monitors"] == 0
    assert stats["checks_last_24h"] == 0
    assert stats["uptime_last_24h_percent"] is None
    assert stats["average_latency_last_24h_ms"] is None


# ============================================================
# Network safety and DNS handling
# ============================================================

def test_localhost_is_rejected_by_safety_guard(client):
    monitor = create_monitor(
        client,
        name="Local Test",
        url="http://127.0.0.1/",
    )

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is False
    assert "publicly routable" in result["error"]


def test_non_global_ipv6_is_rejected(client):
    monitor = create_monitor(
        client,
        name="IPv6 Loopback Test",
        url="http://[::1]/",
    )

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is False
    assert "publicly routable" in result["error"]


def test_nonstandard_port_is_rejected(client):
    monitor = create_monitor(
        client,
        name="Custom Port Website",
        url="https://example.com:8443",
    )

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is False
    assert "standard HTTP port 80" in result["error"]


def test_mixed_public_and_private_dns_answers_are_rejected(
    client,
    monkeypatch,
):
    monitor = create_monitor(
        client,
        name="Mixed DNS Website",
        url="http://example.com/",
    )

    fake_dns_results = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", 80),
        ),
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("127.0.0.1", 80),
        ),
    ]

    monkeypatch.setattr(
        main_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: fake_dns_results,
    )

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is False
    assert "publicly routable IP addresses" in result["error"]


def test_dns_resolution_failure_is_recorded(client, monkeypatch):
    monitor = create_monitor(client)

    def fail_dns(*args, **kwargs):
        raise socket.gaierror("simulated DNS failure")

    monkeypatch.setattr(
        main_module.socket,
        "getaddrinfo",
        fail_dns,
    )

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is False
    assert "hostname could not be resolved" in result["error"]


def test_malformed_dns_answer_is_rejected(monkeypatch):
    fake_dns_results = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("not-an-ip-address", 80),
        ),
    ]

    monkeypatch.setattr(
        main_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: fake_dns_results,
    )

    with pytest.raises(ValueError, match="invalid IP address"):
        main_module.validate_public_destination(
            "http://example.com/"
        )


def test_public_ip_literal_does_not_require_dns(monkeypatch):
    def unexpected_dns(*args, **kwargs):
        pytest.fail("IP literals must not require a DNS lookup")

    monkeypatch.setattr(
        main_module.socket,
        "getaddrinfo",
        unexpected_dns,
    )

    result = main_module.validate_public_destination(
        "http://8.8.8.8/"
    )

    assert result == "8.8.8.8"


def test_check_uses_the_validated_ip(client, monkeypatch):
    monitor = create_monitor(client)
    observed = {}

    monkeypatch.setattr(
        main_module,
        "validate_public_destination",
        lambda url: "93.184.216.34",
    )

    def fake_fetch(url, pinned_ip):
        observed["url"] = url
        observed["ip"] = pinned_ip
        return 200

    monkeypatch.setattr(
        main_module,
        "fetch_status_code_pinned",
        fake_fetch,
    )

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200
    assert response.json()["check"]["success"] is True
    assert observed["url"] == "https://example.com"
    assert observed["ip"] == "93.184.216.34"


# ============================================================
# Monitoring error handling
# ============================================================

@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [
        (
            TimeoutError("simulated timeout"),
            "Request timed out",
        ),
        (
            OSError("simulated connection failure"),
            "HTTP request failed: OSError",
        ),
        (
            http.client.HTTPException("simulated protocol failure"),
            "HTTP request failed: HTTPException",
        ),
    ],
)
def test_network_errors_are_recorded(
    client,
    monkeypatch,
    exception,
    expected_error,
):
    monitor = create_monitor(client)

    def fail_request(url, pinned_ip):
        raise exception

    install_fake_check(monkeypatch, fail_request)

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is False
    assert expected_error in result["error"]

    history = client.get(
        f"/api/monitors/{monitor['id']}/checks"
    ).json()

    assert history["count"] == 1
    assert history["checks"][0]["success"] is False


def test_unexpected_check_error_is_recorded(client, monkeypatch):
    monitor = create_monitor(client)

    def fail_unexpectedly(url, pinned_ip):
        raise RuntimeError("simulated unexpected error")

    install_fake_check(monkeypatch, fail_unexpectedly)

    response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert response.status_code == 200

    result = response.json()["check"]
    assert result["success"] is False
    assert "Unexpected check error: RuntimeError" in result["error"]


# ============================================================
# Outbound HTTP request construction
# ============================================================

def test_fetch_http_request_preserves_host_and_path(monkeypatch):
    observed = {}

    class FakeResponse:
        status = 204

        def close(self):
            observed["response_closed"] = True

    class FakeConnection:
        def __init__(self, hostname, port, connect_ip, timeout):
            observed["hostname"] = hostname
            observed["port"] = port
            observed["connect_ip"] = connect_ip
            observed["timeout"] = timeout

        def request(self, method, target, headers):
            observed["method"] = method
            observed["target"] = target
            observed["headers"] = headers

        def getresponse(self):
            return FakeResponse()

        def close(self):
            observed["connection_closed"] = True

    monkeypatch.setattr(
        main_module,
        "PinnedHTTPConnection",
        FakeConnection,
    )

    result = main_module.fetch_status_code_pinned(
        "http://example.com/health?detail=1",
        "93.184.216.34",
    )

    assert result == 204
    assert observed["hostname"] == "example.com"
    assert observed["port"] == 80
    assert observed["connect_ip"] == "93.184.216.34"
    assert observed["method"] == "GET"
    assert observed["target"] == "/health?detail=1"
    assert observed["headers"]["Host"] == "example.com"
    assert observed["response_closed"] is True
    assert observed["connection_closed"] is True


def test_fetch_https_uses_original_hostname(monkeypatch):
    observed = {}

    class FakeResponse:
        status = 200

        def close(self):
            observed["response_closed"] = True

    class FakeConnection:
        def __init__(self, hostname, port, connect_ip, timeout):
            observed["hostname"] = hostname
            observed["port"] = port
            observed["connect_ip"] = connect_ip

        def request(self, method, target, headers):
            observed["method"] = method
            observed["target"] = target
            observed["headers"] = headers

        def getresponse(self):
            return FakeResponse()

        def close(self):
            observed["connection_closed"] = True

    monkeypatch.setattr(
        main_module,
        "PinnedHTTPSConnection",
        FakeConnection,
    )

    result = main_module.fetch_status_code_pinned(
        "https://example.com/health",
        "93.184.216.34",
    )

    assert result == 200
    assert observed["hostname"] == "example.com"
    assert observed["port"] == 443
    assert observed["connect_ip"] == "93.184.216.34"
    assert observed["headers"]["Host"] == "example.com"
    assert observed["target"] == "/health"
    assert observed["response_closed"] is True
    assert observed["connection_closed"] is True


def test_http_connection_connects_to_pinned_ip(monkeypatch):
    observed = {}
    fake_socket = object()

    def fake_create_connection(address, **kwargs):
        observed["address"] = address
        observed["kwargs"] = kwargs
        return fake_socket

    monkeypatch.setattr(
        main_module.socket,
        "create_connection",
        fake_create_connection,
    )

    connection = main_module.PinnedHTTPConnection(
        hostname="example.com",
        port=80,
        connect_ip="93.184.216.34",
        timeout=3.0,
    )

    connection.connect()

    assert observed["address"] == ("93.184.216.34", 80)
    assert observed["kwargs"]["timeout"] == 3.0
    assert connection.sock is fake_socket


def test_https_connection_pins_ip_and_preserves_tls_hostname(
    monkeypatch,
):
    observed = {}
    fake_raw_socket = object()
    fake_wrapped_socket = object()

    class FakeTLSContext:
        def wrap_socket(self, raw_socket, server_hostname):
            observed["raw_socket"] = raw_socket
            observed["server_hostname"] = server_hostname
            return fake_wrapped_socket

    fake_context = FakeTLSContext()

    def fake_create_connection(address, **kwargs):
        observed["address"] = address
        observed["kwargs"] = kwargs
        return fake_raw_socket

    monkeypatch.setattr(
        main_module.socket,
        "create_connection",
        fake_create_connection,
    )

    monkeypatch.setattr(
        main_module.ssl,
        "create_default_context",
        lambda: fake_context,
    )

    connection = main_module.PinnedHTTPSConnection(
        hostname="example.com",
        port=443,
        connect_ip="93.184.216.34",
        timeout=3.0,
    )

    connection.connect()

    assert observed["address"] == ("93.184.216.34", 443)
    assert observed["server_hostname"] == "example.com"
    assert observed["raw_socket"] is fake_raw_socket
    assert connection.sock is fake_wrapped_socket
