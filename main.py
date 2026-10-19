
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

import httpx
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
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    """Create tables and indexes when the app starts."""

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
# 3. URL VALIDATION AND SAFETY
# ============================================================

def validate_url_format(value: str) -> str:
    """Validate URL syntax before a monitor is saved."""

    value = value.strip()

    if not value:
        raise ValueError("URL is required.")

    try:
        parsed = urlsplit(value)

        # Accessing port also validates malformed port values.
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
            "Enter a URL with a hostname, "
            "such as https://example.com."
        )

    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "URLs containing usernames or passwords are not supported."
        )

    return value


def validate_public_destination(url: str) -> None:
    """
    Reject local and private IP addresses.

    This is a safety measure to reduce the risk of a monitoring
    request being used to access internal network resources.
    """

    parsed = urlsplit(url)
    hostname = parsed.hostname

    if not hostname:
        raise ValueError("The URL does not contain a hostname.")

    port = parsed.port or (
        443 if parsed.scheme.lower() == "https" else 80
    )

    resolved_addresses: set[str] = set()

    try:
        # Check whether the hostname is already an IP address.
        literal_ip = ipaddress.ip_address(hostname)
        resolved_addresses.add(str(literal_ip))

    except ValueError:
        # Otherwise resolve the hostname through DNS.
        try:
            results = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )

        except OSError as exc:
            raise ValueError(
                "The hostname could not be resolved."
            ) from exc

        for result in results:
            address = result[4][0].split("%")[0]
            resolved_addresses.add(address)

    if not resolved_addresses:
        raise ValueError(
            "The hostname did not resolve to an IP address."
        )

    for address in resolved_addresses:
        try:
            ip = ipaddress.ip_address(address)

        except ValueError as exc:
            raise ValueError(
                "The hostname resolved to an invalid IP address."
            ) from exc

        if not ip.is_global:
            raise ValueError(
                "For safety, OpsPulse only checks publicly "
                "routable IP addresses."
            )


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
    Check a website, record its response time, and update
    the monitor's latest status.
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
        # Do not attempt a request to a private/local destination.
        validate_public_destination(monitor["url"])

        # Redirects are deliberately not followed. This avoids
        # automatically following a public URL into a private URL.
        with httpx.Client(
            timeout=CHECK_TIMEOUT_SECONDS,
            follow_redirects=False,
            headers={
                "User-Agent": "OpsPulse-Monitor/1.0"
            },
        ) as client:

            response = client.get(monitor["url"])

        status_code = response.status_code

        # HTTP 2xx and 3xx responses count as reachable.
        success = 200 <= status_code < 400

        if not success:
            error = f"HTTP {status_code}"

    except ValueError as exc:
        error = str(exc)

    except httpx.TimeoutException:
        error = (
            f"Request timed out after "
            f"{CHECK_TIMEOUT_SECONDS:g} seconds."
        )

    except httpx.HTTPError as exc:
        error = f"HTTP request failed: {type(exc).__name__}."

    except Exception as exc:
        logger.exception(
            "Unexpected error while checking monitor %s",
            monitor_id,
        )
        error = f"Unexpected check error: {type(exc).__name__}."

    latency_ms = round(
        (time.perf_counter() - started) * 1000,
        2,
    )

    success_int = int(success)

    # Save the result in the historical checks table.
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

        # Update the latest status on the monitor.
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
        datetime.now(timezone.utc) - timedelta(hours=24)
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
    Find active monitors that are due for a check.

    The scheduler wakes up every five seconds. Each monitor's
    configured interval determines when its next check is due.
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

            now = datetime.now(timezone.utc)
            due_ids: list[int] = []

            for row in rows:
                last_checked = row["last_checked_at"]

                if last_checked is None:
                    due_ids.append(int(row["id"]))
                    continue

                try:
                    last_time = datetime.fromisoformat(
                        last_checked
                    )

                    if last_time.tzinfo is None:
                        last_time = last_time.replace(
                            tzinfo=timezone.utc
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
                    # Recover monitors with malformed timestamps.
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
    """Initialize persistent storage and start the scheduler."""

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
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================
# 9. GENERAL ENDPOINTS
# ============================================================

@app.get("/", tags=["general"], include_in_schema=False)
def root() -> FileResponse:
    """Serve the OpsPulse dashboard."""
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
        datetime.now(timezone.utc) - timedelta(hours=24)
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

    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=422,
            detail=(
                "Update fields cannot be null; omit fields "
                "you do not want to change."
            ),
        )

    # Only predefined field names are allowed in the SQL.
    allowed_columns = {
        "name": "name",
        "active": "active",
        "interval_seconds": "interval_seconds",
    }

    assignments: list[str] = []
    values: list[Any] = []

    for field_name, value in changes.items():
        assignments.append(
            f"{allowed_columns[field_name]} = ?"
        )

        if field_name == "active":
            value = int(value)

        values.append(value)

    values.append(monitor_id)

    with get_db() as connection:
        fetch_monitor_or_404(
            connection,
            monitor_id,
        )

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

        monitor = monitor_to_dict(
            connection,
            updated,
        )

    return {
        "message": "Monitor updated.",
        "monitor": monitor,
    }


@app.delete("/api/monitors/{monitor_id}", tags=["monitors"])
def delete_monitor(monitor_id: int) -> dict[str, Any]:
    with get_db() as connection:
        fetch_monitor_or_404(
            connection,
            monitor_id,
        )

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

        monitor = monitor_to_dict(
            connection,
            row,
        )

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
        fetch_monitor_or_404(
            connection,
            monitor_id,
        )

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

# Serve the dashboard's CSS and JavaScript files.
app.mount(
    "/static",
    StaticFiles(directory=APP_DIR / "static"),
    name="static",
)