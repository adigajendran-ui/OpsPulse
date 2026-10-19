
"""Automated tests for OpsPulse.

Run:
    python -m pytest -v

Every test uses an isolated temporary SQLite database.
HTTP responses are mocked except where the test explicitly
checks that unsafe destinations are rejected before connecting.
"""

import asyncio
import socket

import pytest
from fastapi.testclient import TestClient

import main as main_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Run the application with a temporary database and idle scheduler."""

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
    """Simulate destination validation and HTTP responses."""

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


def test_dashboard_and_health_endpoints_work(client):
    """The dashboard, assets, and health endpoint are served."""

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


def test_invalid_url_is_rejected(client):
    response = client.post(
        "/api/monitors",
        json={
            "name": "Invalid Website",
            "url": "ftp://example.com",
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

    assert monitor_response.status_code == 200
    assert monitor_response.json()["monitor"]["status"] == "down"


def test_dashboard_statistics_include_check_results(
    client,
    monkeypatch,
):
    monitor = create_monitor(client)
    install_fake_http_client(monkeypatch, status_code=200)

    check_response = client.post(
        f"/api/monitors/{monitor['id']}/check"
    )

    assert check_response.status_code == 200

    response = client.get("/api/stats")

    assert response.status_code == 200

    stats = response.json()

    assert stats["total_monitors"] == 1
    assert stats["active_monitors"] == 1
    assert stats["up_monitors"] == 1
    assert stats["down_monitors"] == 0
    assert stats["checks_last_24h"] == 1
    assert stats["uptime_last_24h_percent"] == 100.0
    assert stats["average_latency_last_24h_ms"] is not None


def test_localhost_is_rejected_by_safety_guard(client):
    """Loopback destinations are rejected without making a request."""

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


def test_nonexistent_monitor_returns_404(client):
    response = client.get("/api/monitors/999999")

    assert response.status_code == 404


def test_monitor_can_be_deleted(client):
    monitor = create_monitor(client)

    response = client.delete(
        f"/api/monitors/{monitor['id']}"
    )

    assert response.status_code == 200

    response = client.get(
        f"/api/monitors/{monitor['id']}"
    )

    assert response.status_code == 404

    response = client.get(
        f"/api/monitors/{monitor['id']}/checks"
    )

    assert response.status_code == 404


def test_patch_without_fields_is_rejected(client):
    monitor = create_monitor(client)

    response = client.patch(
        f"/api/monitors/{monitor['id']}",
        json={},
    )

    assert response.status_code == 400


def test_manual_check_of_missing_monitor_returns_404(client):
    response = client.post("/api/monitors/999999/check")

    assert response.status_code == 404


def test_nonstandard_port_is_rejected(client):
    """Only standard HTTP and HTTPS ports are permitted."""

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
    """One private answer causes the full DNS result to be rejected."""

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


def test_check_uses_the_validated_ip(client, monkeypatch):
    """The outbound request uses the IP returned by validation."""

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