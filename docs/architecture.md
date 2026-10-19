
# OpsPulse Architecture

## 1. Overview

OpsPulse is a small, local-first web application for monitoring public HTTP and HTTPS endpoints.

It has four main components:

1. A browser-based dashboard.
2. A FastAPI application exposing a REST API.
3. A SQLite database storing monitors and historical checks.
4. A background scheduler that triggers checks for active monitors.

The dashboard and API are served by the same application.

## 2. System Diagram

```text
                       User's Browser
                             |
                             | HTTP
                             v
                  +----------------------+
                  | OpsPulse Dashboard   |
                  | HTML / CSS / JS      |
                  +----------------------+
                             |
                             | Fetch API requests
                             v
                  +----------------------+
                  | FastAPI Application  |
                  | Validation / Routes  |
                  +----------------------+
                     |              |
                     |              |
                     v              v
            +---------------+  +----------------+
            | SQLite        |  | Monitoring     |
            | monitors      |  | Engine         |
            | checks        |  +----------------+
            +---------------+          |
                                       | HTTP(S)
                                       v
                              Public Website or API
```

## 3. Frontend

The frontend lives in `static/`.

### `index.html`

Defines the dashboard structure, including:

- Statistics cards
- Monitor table
- Search and status filters
- Response-time chart
- Selected-monitor details
- Recent check activity
- Monitor creation dialog

### `styles.css`

Provides layout, colors, responsive behavior, status indicators, and visual states.

### `app.js`

Calls the API using `fetch`, renders monitor data, manages dashboard interactions, and displays notifications.

The browser does not directly open the SQLite database. It receives JSON responses from FastAPI.

## 4. Backend

`main.py` defines the application routes, data models, monitoring engine, scheduler, and database operations.

### Request validation

Pydantic models validate incoming monitor data, including names, URL formats, and allowed check intervals.

### API handlers

FastAPI routes handle monitor CRUD operations, dashboard statistics, check-history retrieval, and manual checks.

### Monitoring engine

`run_check()` retrieves the monitor configuration, applies destination checks, sends an HTTP request, measures elapsed time, and records the outcome.

The current implementation does not follow redirects. HTTP status codes from 200 through 399 are classified as successful reachability results.

### Background scheduler

The scheduler periodically searches for active monitors whose configured intervals have elapsed. It invokes checks in worker threads so blocking network calls do not directly block the scheduler's event loop.

The scheduler is process-local. A multi-worker deployment would require a different design to prevent duplicate scheduled checks.

## 5. Database Model

The application uses SQLite.

### `monitors`

Stores the latest configuration and result for each monitored endpoint.

Important fields include:

- `id`: primary key
- `name`: display name
- `url`: monitored address
- `created_at`: creation timestamp
- `active`: whether automatic monitoring is enabled
- `interval_seconds`: configured check frequency
- `last_checked_at`: most recent check timestamp
- `last_status_code`: most recent HTTP status
- `last_latency_ms`: most recent measured latency
- `last_success`: outcome of the most recent check
- `last_error`: error information when applicable

### `checks`

Stores one historical record per attempt.

Important fields include:

- `id`: primary key
- `monitor_id`: related monitor
- `checked_at`: check timestamp
- `status_code`: HTTP status, when available
- `latency_ms`: measured elapsed time
- `success`: whether the check met the application's success rule
- `error`: recorded error details, when applicable

Each check references a monitor. Deleting a monitor also deletes its associated checks through the database's foreign-key cascade.

### Indexes

Indexes support looking up a monitor's most recent check history and retrieving recent checks efficiently.

## 6. Check Lifecycle

A check follows these steps:

1. Load the monitor from SQLite.
2. Record the start time.
3. Validate the destination's resolved IP addresses.
4. Send an HTTP request with a finite timeout and without automatic redirect following.
5. Classify the response or record the error.
6. Calculate elapsed time.
7. Insert a historical check record.
8. Update the monitor's latest status fields.
9. Return the result to the API caller.

Scheduled checks and manual checks use the same monitoring function.

## 7. Uptime Calculation

For a monitor, the application selects checks recorded within the last 24 hours.

```text
Uptime percentage =
    successful checks / total checks * 100
```

When there are no check records within that period, uptime is returned as `null` and displayed as unavailable.

This is based on the checks that were actually recorded. It cannot establish availability during periods before monitoring began or during gaps in data collection.

## 8. API and Browser Interaction

The dashboard retrieves:

- `/api/health` for application and database health
- `/api/stats` for dashboard metrics
- `/api/monitors` for monitor records
- `/api/monitors/{id}/checks` for monitor history

It creates monitors through `POST`, updates them through `PATCH`, and deletes them through `DELETE`.

Manual checks use `POST /api/monitors/{id}/check`.

The `/docs` page exposes interactive API documentation while the server is running.

## 9. Testing Strategy

`test_main.py` uses pytest and FastAPI's test client.

Tests override the database path with a temporary file and replace the scheduler with an idle task. This isolates test data from the local database and avoids background checks interfering with test assertions.

Network results are mocked for deterministic success and HTTP-failure tests. The suite also verifies static-file delivery, API validation, database persistence, statistics, deletion behavior, and local-address rejection.

Run the suite with:

```bash
python -m pytest -v
```

## 10. Security Considerations

The current project is intended for local development.

The destination checks provide basic protection but are not a complete Server-Side Request Forgery (SSRF) defense. A production implementation must address DNS rebinding, time-of-check/time-of-use risks, redirects, address pinning, access controls, rate limits, and outbound-network restrictions.

The application does not currently provide authentication or authorization. A publicly exposed deployment must not rely on the current safeguards alone.

## 11. Scaling Considerations

SQLite and an in-process scheduler are appropriate for a learning project and modest local workloads.

A larger deployment would likely need:

- A managed relational database
- A persistent job queue
- Dedicated monitoring workers
- Concurrency and per-target rate controls
- Durable alert delivery
- Retention and archival policies
- Authentication and role-based authorization
- Centralized logging and health monitoring

These changes would separate API availability from monitoring execution and make scheduled work more reliable across restarts.
