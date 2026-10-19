
from __future__ import annotations

import asyncio
import http.client
import ipaddress
import logging
import socket
import sqlite3
import ssl
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# ============================================================
# 1. CONFIGURATION
# ============================================================

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "opspulse.db"

CHECK_TIMEOUT_SECONDS = 10.0
SCHEDULER_POLL_SECONDS = 5
MIN_INTERVAL_SECONDS = 30
MAX_INTERVAL_SECONDS = 3600

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("opspulse")


# ============================================================
# 2. DATABASE HELPERS
# ============================================================

def utc_now() -> str:
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Open a database connection and always close it."""
    connection = sqlite3.connect(str(DB_PATH), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    """Create tables and indexes if they do not exist."""

    with get_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
                    CHECK (active IN (0, 1)),
                interval_seconds INTEGER NOT NULL DEFAULT 60,
                last_checked_at TEXT,
                last_status_code INTEGER,
                last_latency_ms REAL,
                last_success INTEGER
                    CHECK (
                        last_success IN (0, 1)
                        OR last_success IS NULL
                    ),
                last_error TEXT
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                status_code INTEGER,
                latency_ms REAL NOT NULL,
                success INTEGER NOT NULL
                    CHECK (success IN (0, 1)),
                error TEXT,
                FOREIGN KEY (monitor_id)
                    REFERENCES monitors(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checks_monitor_time
            ON checks(monitor_id, checked_at DESC)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checks_time
            ON checks(checked_at DESC)
            """
        )


# ============================================================
# 3. URL VALIDATION AND OUTBOUND NETWORK SAFETY
# ============================================================

def validate_url_format(value: str) -> str:
    """Validate URL syntax before a monitor is created."""

    value = value.strip()

    if not value:
        raise ValueError("URL is required.")

    try:
        parsed = urlsplit(value)
        _ = parsed.port

    except ValueError as exc:
        raise ValueError(
            "Enter a valid URL, including its protocol, "
            "such as https://example.com."
        ) from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(
            "Only http:// and https:// URLs are supported."
        )

    if not parsed.hostname:
        raise ValueError(
            "Enter a URL containing a hostname."
        )

    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "URLs containing usernames or passwords are not supported."
        )

    if "%" in parsed.hostname:
        raise ValueError(
            "Scoped or percent-encoded hostnames are not supported."
        )

    return value


def validate_public_destination(url: str) -> str:
    """
    Resolve and validate a URL's destination.

    Returns a validated IP address. The caller must connect to
    this exact address instead of resolving the hostname again.

    This is a security control, not a complete SSRF defense.
    """

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        requested_port = parsed.port

    except ValueError as exc:
        raise ValueError("The URL contains invalid syntax.") from exc

    scheme = parsed.scheme.lower()

    if scheme not in {"http", "https"} or not hostname:
        raise ValueError(
            "Only valid HTTP and HTTPS URLs are allowed."
        )

    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "URLs containing credentials are not allowed."
        )

    if "%" in hostname:
        raise ValueError(
            "Scoped or percent-encoded hostnames are not supported."
        )

    default_port = 443 if scheme == "https" else 80

    if requested_port not in (None, default_port):
        raise ValueError(
            "For safety, only standard HTTP port 80 and "
            "HTTPS port 443 are allowed."
        )

    port = default_port

    try:
        literal_ip = ipaddress.ip_address(hostname)
        addresses = [str(literal_ip)]

    except ValueError:
        try:
            hostname_ascii = hostname.encode("idna").decode("ascii").lower()

        except UnicodeError as exc:
            raise ValueError("The hostname is invalid.") from exc

        normalized_hostname = hostname_ascii.rstrip(".")

        if (
            normalized_hostname == "localhost"
            or normalized_hostname.endswith(
                (".localhost", ".local", ".internal", ".test")
            )
        ):
            raise ValueError(
                "Local and internal hostnames are not allowed."
            )

        try:
            results = socket.getaddrinfo(
                hostname_ascii,
                port,
                type=socket.SOCK_STREAM,
            )

        except OSError as exc:
            raise ValueError(
                "The hostname could not be resolved."
            ) from exc

        addresses = list(
            dict.fromkeys(
                result[4][0].split("%", 1)[0]
                for result in results
            )
        )

    if not addresses:
        raise ValueError(
            "The hostname did not resolve to an IP address."
        )

    validated_addresses: list[str] = []

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)

        except ValueError as exc:
            raise ValueError(
                "The hostname resolved to an invalid IP address."
            ) from exc

        # Reject the complete DNS answer set if even one answer
        # is private, loopback, link-local, reserved, or non-global.
        if not ip.is_global:
            raise ValueError(
                "For safety, OpsPulse only checks publicly "
                "routable IP addresses."
            )

        validated_addresses.append(str(ip))

    # The request layer uses this exact address for the TCP socket.
    return validated_addresses[0]


class PinnedHTTPConnection(http.client.HTTPConnection):
    """
    HTTP connection that connects to a specific validated IP.
    """

    def __init__(
        self,
        hostname: str,
        port: int,
        connect_ip: str,
        timeout: float,
    ):
        super().__init__(
            host=hostname,
            port=port,
            timeout=timeout,
        )
        self.connect_ip = connect_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self.connect_ip, self.port),
            timeout=self.timeout,
            source_address=self.source_address,
        )


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """
    HTTPS connection that pins the TCP destination.

    The original hostname is retained for TLS SNI and certificate
    hostname validation.
    """

    def __init__(
        self,
        hostname: str,
        port: int,
        connect_ip: str,
        timeout: float,
    ):
        super().__init__(
            host=hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self.connect_ip = connect_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self.connect_ip, self.port),
            timeout=self.timeout,
            source_address=self.source_address,
        )

        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )

        except Exception:
            raw_socket.close()
            raise


def fetch_status_code_pinned(
    url: str,
    pinned_ip: str,
) -> int:
    """
    Send one GET request to an already validated destination.

    Redirects are not followed. HTTPS certificate verification
    uses the original hostname rather than the pinned IP.
    """

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        requested_port = parsed.port

    except ValueError as exc:
        raise ValueError("The URL contains invalid syntax.") from exc

    if not hostname:
        raise ValueError("The URL does not contain a hostname.")

    scheme = parsed.scheme.lower()

    if scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS are supported.")

    default_port = 443 if scheme == "https" else 80
    port = requested_port or default_port

    hostname_ascii = hostname.encode("idna").decode("ascii")

    try:
        hostname_ip = ipaddress.ip_address(hostname_ascii)

        host_header = (
            f"[{hostname_ascii}]"
            if hostname_ip.version == 6
            else hostname_ascii
        )

    except ValueError:
        host_header = hostname_ascii

    if scheme == "https":
        connection = PinnedHTTPSConnection(
            hostname=hostname_ascii,
            port=port,
            connect_ip=pinned_ip,
            timeout=CHECK_TIMEOUT_SECONDS,
        )

    else:
        connection = PinnedHTTPConnection(
            hostname=hostname_ascii,
            port=port,
            connect_ip=pinned_ip,
            timeout=CHECK_TIMEOUT_SECONDS,
        )

    request_target = parsed.path or "/"

    if parsed.query:
        request_target += f"?{parsed.query}"

    try:
        connection.request(
            "GET",
            request_target,
            headers={
                "Host": host_header,
                "User-Agent": "OpsPulse-Monitor/1.0",
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )

        response = connection.getresponse()

        try:
            return response.status
        finally:
            response.close()

    finally:
        connection.close()


# ============================================================
# 4. API REQUEST MODELS
# ============================================================

class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=2048)

    interval_seconds: int = Field(
        default=60,
        ge=MIN_INTERVAL_SECONDS,
        le=MAX_INTERVAL_SECONDS,
        description="Check interval in seconds: 30–3600",
    )

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Name cannot be blank.")

        return value

    @field_validator("url")
    @classmethod
    def clean_url(cls, value: str) -> str:
        return validate_url_format(value)


class MonitorUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )

    active: bool | None = None

    interval_seconds: int | None = Field(
        default=None,
        ge=MIN_INTERVAL_SECONDS,
        le=MAX_INTERVAL_SECONDS,
    )

    @field_validator("name")
    @classmethod
    def clean_optional_name(
        cls,
        value: str | None,
    ) -> str | None:

        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Name cannot be blank.")

        return value


# ============================================================
# 5. WEBSITE MONITORING ENGINE
# ============================================================

def run_check(monitor_id: int) -> dict[str, Any] | None:
    """
    Check a website, record the result, and update the monitor.

    Both manual and scheduled checks use this function.
    """

    with get_db() as connection:
        monitor = connection.execute(
            """
            SELECT id, url
            FROM monitors
            WHERE id = ?
            """,
            (monitor_id,),
        ).fetchone()

    if monitor is None:
        return None

    checked_at = utc_now()
    started = time.perf_counter()

    status_code: int | None = None
    success = False
    error: str | None = None

    try:
        pinned_ip = validate_public_destination(monitor["url"])

        status_code = fetch_status_code_pinned(
            monitor["url"],
            pinned_ip,
        )

        # Treat HTTP 2xx and 3xx responses as reachable.
        success = 200 <= status_code < 400

        if not success:
            error = f"HTTP {status_code}"

    except ValueError as exc:
        error = str(exc)

    except TimeoutError:
        error = (
            f"Request timed out after "
            f"{CHECK_TIMEOUT_SECONDS:g} seconds."
        )

    except (OSError, http.client.HTTPException) as exc:
        error = (
            f"HTTP request failed: {type(exc).__name__}."
        )

    except Exception as exc:
        logger.exception(
            "Unexpected error while checking monitor %s",
            monitor_id,
        )
        error = (
            f"Unexpected check error: {type(exc).__name__}."
        )

    latency_ms = round(
        (time.perf_counter() - started) * 1000,
        2,
    )

    success_int = int(success)

    with get_db() as connection:
        connection.execute(
            """
            INSERT INTO checks (
                monitor_id,
                checked_at,
                status_code,
                latency_ms,
                success,
                error
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                monitor_id,
                checked_at,
                status_code,
                latency_ms,
                success_int,
                error,
            ),
        )

        connection.execute(
            """
            UPDATE monitors
            SET last_checked_at = ?,
                last_status_code = ?,
                last_latency_ms = ?,
                last_success = ?,
                last_error = ?
            WHERE id = ?
            """,
            (
                checked_at,
                status_code,
                latency_ms,
                success_int,
                error,
                monitor_id,
            ),
        )

    return {
        "monitor_id": monitor_id,
        "checked_at": checked_at,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "success": success,
        "error": error,
    }


# ============================================================
# 6. MONITOR RESPONSE HELPERS
# ============================================================

def monitor_to_dict(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    """Build a monitor response, including 24-hour uptime."""

    cutoff = (
        datetime.now(UTC) - timedelta(hours=24)
    ).isoformat(timespec="seconds")

    counts = connection.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(success), 0) AS successful
        FROM checks
        WHERE monitor_id = ?
          AND checked_at >= ?
        """,
        (row["id"], cutoff),
    ).fetchone()

    total = int(counts["total"])
    successful = int(counts["successful"])

    uptime = (
        round(successful * 100 / total, 2)
        if total
        else None
    )

    last_success = row["last_success"]

    if last_success is None:
        current_status = "unknown"
    elif last_success == 1:
        current_status = "up"
    else:
        current_status = "down"

    return {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "created_at": row["created_at"],
        "active": bool(row["active"]),
        "interval_seconds": row["interval_seconds"],
        "last_checked_at": row["last_checked_at"],
        "last_status_code": row["last_status_code"],
        "last_latency_ms": row["last_latency_ms"],
        "last_success": (
            None
            if last_success is None
            else bool(last_success)
        ),
        "last_error": row["last_error"],
        "status": current_status,
        "uptime_24h_percent": uptime,
    }


def fetch_monitor_or_404(
    connection: sqlite3.Connection,
    monitor_id: int,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT *
        FROM monitors
        WHERE id = ?
        """,
        (monitor_id,),
    ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Monitor not found.",
        )

    return row


# ============================================================
# 7. AUTOMATIC MONITORING SCHEDULER
# ============================================================

async def background_scheduler() -> None:
    """
    Find active monitors whose check intervals have elapsed.

    This scheduler runs within this application process.
    Production deployments need a dedicated and coordinated
    scheduling design.
    """

    while True:
        try:
            with get_db() as connection:
                rows = connection.execute(
                    """
                    SELECT id, interval_seconds, last_checked_at
                    FROM monitors
                    WHERE active = 1
                    """
                ).fetchall()

            now = datetime.now(UTC)
            due_ids: list[int] = []

            for row in rows:
                last_checked = row["last_checked_at"]

                if last_checked is None:
                    due_ids.append(int(row["id"]))
                    continue

                try:
                    last_time = datetime.fromisoformat(last_checked)

                    if last_time.tzinfo is None:
                        last_time = last_time.replace(
                            tzinfo=UTC
                        )

                    due = (
                        now - last_time
                        >= timedelta(
                            seconds=int(row["interval_seconds"])
                        )
                    )

                    if due:
                        due_ids.append(int(row["id"]))

                except (TypeError, ValueError):
                    due_ids.append(int(row["id"]))

            if due_ids:
                results = await asyncio.gather(
                    *(
                        asyncio.to_thread(run_check, monitor_id)
                        for monitor_id in due_ids
                    ),
                    return_exceptions=True,
                )

                for result in results:
                    if isinstance(result, Exception):
                        logger.error(
                            "A scheduled check failed unexpectedly: %s",
                            result,
                        )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Background scheduler iteration failed"
            )

        await asyncio.sleep(SCHEDULER_POLL_SECONDS)


# ============================================================
# 8. APPLICATION STARTUP AND SHUTDOWN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SQLite and start the background scheduler."""

    initialize_database()

    scheduler_task = asyncio.create_task(
        background_scheduler()
    )

    try:
        yield

    finally:
        scheduler_task.cancel()

        with suppress(asyncio.CancelledError):
            await scheduler_task


app = FastAPI(
    title="OpsPulse API",
    description=(
        "A local-first website uptime monitoring service. "
        "Add public websites, run checks, inspect response "
        "history, and view uptime statistics."
    ),
    version="1.1.0",
    lifespan=lifespan,
)


# ============================================================
# 9. GENERAL ENDPOINTS
# ============================================================

@app.get("/", tags=["general"], include_in_schema=False)
def root() -> FileResponse:
    """Serve the dashboard."""
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/api/health", tags=["general"])
def health() -> dict[str, str]:
    with get_db() as connection:
        connection.execute("SELECT 1").fetchone()

    return {
        "status": "ok",
        "database": "ok",
        "app": "OpsPulse",
    }


# ============================================================
# 10. DASHBOARD STATISTICS
# ============================================================

@app.get("/api/stats", tags=["dashboard"])
def get_stats() -> dict[str, Any]:
    cutoff = (
        datetime.now(UTC) - timedelta(hours=24)
    ).isoformat(timespec="seconds")

    with get_db() as connection:
        monitor_rows = connection.execute(
            """
            SELECT active, last_success
            FROM monitors
            """
        ).fetchall()

        check_stats = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(success), 0) AS successful,
                AVG(latency_ms) AS average_latency_ms
            FROM checks
            WHERE checked_at >= ?
            """,
            (cutoff,),
        ).fetchone()

    total_monitors = len(monitor_rows)

    active_monitors = sum(
        1 for row in monitor_rows
        if row["active"] == 1
    )

    checked_rows = [
        row for row in monitor_rows
        if row["last_success"] is not None
    ]

    up_monitors = sum(
        1 for row in checked_rows
        if row["last_success"] == 1
    )

    down_monitors = sum(
        1 for row in checked_rows
        if row["last_success"] == 0
    )

    checks_total = int(check_stats["total"])
    checks_successful = int(check_stats["successful"])

    uptime = (
        round(checks_successful * 100 / checks_total, 2)
        if checks_total
        else None
    )

    average_latency = check_stats["average_latency_ms"]

    return {
        "total_monitors": total_monitors,
        "active_monitors": active_monitors,
        "up_monitors": up_monitors,
        "down_monitors": down_monitors,
        "unchecked_monitors": (
            total_monitors - len(checked_rows)
        ),
        "checks_last_24h": checks_total,
        "uptime_last_24h_percent": uptime,
        "average_latency_last_24h_ms": (
            round(average_latency, 2)
            if average_latency is not None
            else None
        ),
    }


# ============================================================
# 11. CREATE AND LIST MONITORS
# ============================================================

@app.get("/api/monitors", tags=["monitors"])
def list_monitors() -> dict[str, Any]:
    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM monitors
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()

        monitors = [
            monitor_to_dict(connection, row)
            for row in rows
        ]

    return {
        "count": len(monitors),
        "monitors": monitors,
    }


@app.post(
    "/api/monitors",
    status_code=status.HTTP_201_CREATED,
    tags=["monitors"],
)
def create_monitor(
    payload: MonitorCreate,
) -> dict[str, Any]:
    with get_db() as connection:
        cursor = connection.execute(
            """
            INSERT INTO monitors (
                name,
                url,
                created_at,
                active,
                interval_seconds
            )
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                payload.name,
                payload.url,
                utc_now(),
                payload.interval_seconds,
            ),
        )

        monitor_id = int(cursor.lastrowid)

        row = fetch_monitor_or_404(
            connection,
            monitor_id,
        )

        monitor = monitor_to_dict(connection, row)

    return {
        "message": (
            "Monitor created. Its first automatic check "
            "will run shortly."
        ),
        "monitor": monitor,
    }


# ============================================================
# 12. RETRIEVE, UPDATE, AND DELETE MONITORS
# ============================================================

@app.get("/api/monitors/{monitor_id}", tags=["monitors"])
def get_monitor(monitor_id: int) -> dict[str, Any]:
    with get_db() as connection:
        row = fetch_monitor_or_404(
            connection,
            monitor_id,
        )

        monitor = monitor_to_dict(connection, row)

    return {"monitor": monitor}


@app.patch("/api/monitors/{monitor_id}", tags=["monitors"])
def update_monitor(
    monitor_id: int,
    payload: MonitorUpdate,
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one field to update.",
        )

    allowed_columns = {
        "name": "name",
        "active": "active",
        "interval_seconds": "interval_seconds",
    }

    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=422,
            detail=(
                "Update fields cannot be null; omit fields "
                "you do not want to change."
            ),
        )

    assignments: list[str] = []
    values: list[Any] = []

    for field_name, value in changes.items():
        assignments.append(f"{allowed_columns[field_name]} = ?")

        if field_name == "active":
            value = int(value)

        values.append(value)

    values.append(monitor_id)

    with get_db() as connection:
        fetch_monitor_or_404(connection, monitor_id)

        connection.execute(
            f"""
            UPDATE monitors
            SET {', '.join(assignments)}
            WHERE id = ?
            """,
            values,
        )

        updated = fetch_monitor_or_404(
            connection,
            monitor_id,
        )

        monitor = monitor_to_dict(connection, updated)

    return {
        "message": "Monitor updated.",
        "monitor": monitor,
    }


@app.delete("/api/monitors/{monitor_id}", tags=["monitors"])
def delete_monitor(monitor_id: int) -> dict[str, Any]:
    with get_db() as connection:
        fetch_monitor_or_404(connection, monitor_id)

        connection.execute(
            "DELETE FROM monitors WHERE id = ?",
            (monitor_id,),
        )

    return {
        "message": "Monitor deleted.",
        "id": monitor_id,
    }


# ============================================================
# 13. MANUAL CHECKS AND CHECK HISTORY
# ============================================================

@app.post(
    "/api/monitors/{monitor_id}/check",
    tags=["checks"],
)
def check_monitor_now(
    monitor_id: int,
) -> dict[str, Any]:
    result = run_check(monitor_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Monitor not found.",
        )

    with get_db() as connection:
        row = fetch_monitor_or_404(
            connection,
            monitor_id,
        )

        monitor = monitor_to_dict(connection, row)

    return {
        "monitor": monitor,
        "check": result,
    }


@app.get(
    "/api/monitors/{monitor_id}/checks",
    tags=["checks"],
)
def list_monitor_checks(
    monitor_id: int,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of results (1–200)",
    ),
) -> dict[str, Any]:
    with get_db() as connection:
        fetch_monitor_or_404(connection, monitor_id)

        rows = connection.execute(
            """
            SELECT
                id,
                monitor_id,
                checked_at,
                status_code,
                latency_ms,
                success,
                error
            FROM checks
            WHERE monitor_id = ?
            ORDER BY checked_at DESC, id DESC
            LIMIT ?
            """,
            (monitor_id, limit),
        ).fetchall()

    checks = [
        {
            "id": row["id"],
            "monitor_id": row["monitor_id"],
            "checked_at": row["checked_at"],
            "status_code": row["status_code"],
            "latency_ms": row["latency_ms"],
            "success": bool(row["success"]),
            "error": row["error"],
        }
        for row in rows
    ]

    return {
        "monitor_id": monitor_id,
        "count": len(checks),
        "checks": checks,
    }


# ============================================================
# 14. STATIC FRONTEND ASSETS
# ============================================================

app.mount(
    "/static",
    StaticFiles(directory=APP_DIR / "static"),
    name="static",
)