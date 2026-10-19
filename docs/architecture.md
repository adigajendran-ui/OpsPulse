
# OpsPulse Architecture

## 1. Overview

OpsPulse is a local-first web application that monitors public HTTP and HTTPS endpoints.

The application has four primary components:

1. A browser-based dashboard.
2. A FastAPI application exposing a REST API.
3. A SQLite database storing monitors and historical checks.
4. An in-process scheduler that starts checks for active monitors.

The browser and API are served by the same application process.

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

The frontend is located in `static/`.

### `index.html`

Defines the dashboard interface, including:

- Statistics cards
- Monitor table
- Search and status filters
- Response-time chart
- Selected-monitor details
- Recent check activity
- Monitor creation dialog

### `styles.css`

Provides layout, colors, responsive behavior, status indicators, and component styling.

### `app.js`

Uses the browser Fetch API to communicate with FastAPI, render monitor data, control dashboard interactions, and display notifications.

The browser does not access SQLite directly. It receives data through the API.

## 4. Backend

`main.py` defines the application routes, request models, database helpers, monitoring engine, outbound connection safeguards, and scheduler.

### Request validation

Pydantic models validate submitted monitor names, URL formats, and allowed check intervals.

### API handlers

FastAPI routes manage monitors, return dashboard statistics, expose check history, and trigger manual checks.

### Monitoring engine

`run_check()` performs these operations:

1. Retrieve the monitor configuration.
2. Record a timestamp and start time.
3. Validate and resolve the destination.
4. Reject non-global IP addresses.
5. Use a pinned connection to contact the selected IP.
6. Record the HTTP status or error.
7. Calculate elapsed response time.
8. Save the check in SQLite.
9. Update the monitor's latest result.

Manual and scheduled checks share the same monitoring function.

## 5. Outbound Connection Safety

### Destination validation

`validate_public_destination()` resolves a URL's hostname and checks the resulting IP addresses.

The current policy rejects:

- Loopback addresses
- Private network addresses
- Link-local and other non-global addresses
- Hostnames associated with local or internal environments
- Non-standard HTTP and HTTPS ports

The function rejects the hostname if any returned DNS address is non-global.

### IP-pinned connections

A conventional HTTP client can resolve a hostname once during validation and again during connection. If the DNS answer changes between those operations, the application could contact a different destination from the one validated.

OpsPulse reduces this risk by passing a validated IP address to `PinnedHTTPConnection` or `PinnedHTTPSConnection`. These classes establish the TCP connection to that address instead of resolving the original hostname again.

### HTTPS hostname verification

For HTTPS, the TCP connection goes to the pinned IP address, while TLS uses the original hostname for Server Name Indication and certificate hostname verification.

This preserves ordinary certificate verification while separating the network destination from the hostname used by TLS.

### Redirect behavior

The monitoring engine makes a single GET request and does not automatically follow redirects. A redirect response is recorded according to the application's reachability rule rather than causing a second request to an unvalidated destination.

### Important limitation

These are useful defensive controls, but they are not a comprehensive security boundary. A publicly operated monitoring service also needs network-level outbound restrictions, authorization, rate limits, concurrency controls, independent security testing, and careful handling of DNS and socket behavior.

## 6. Database Model

OpsPulse uses SQLite.

### `monitors`

Stores each monitor's configuration and latest status.

Important fields include:

- `id`: primary key
- `name`: display name
- `url`: monitored address
- `created_at`: creation timestamp
- `active`: whether automatic monitoring is enabled
- `interval_seconds`: configured check interval
- `last_checked_at`: most recent check timestamp
- `last_status_code`: latest HTTP status
- `last_latency_ms`: latest measured latency
- `last_success`: latest result
- `last_error`: latest error information

### `checks`

Stores one historical row for each attempt.

Important fields include:

- `id`: primary key
- `monitor_id`: related monitor
- `checked_at`: check timestamp
- `status_code`: HTTP status when a response is received
- `latency_ms`: elapsed request time
- `success`: result according to the application's HTTP-status rule
- `error`: recorded error message, if applicable

Each check references a monitor. The foreign-key cascade deletes associated history when its monitor is removed.

### Indexes

Indexes support lookups of monitor-specific check history and recent check records.

## 7. Monitoring Scheduler

The scheduler repeatedly looks for active monitors that are due for a check.

A monitor is due when it has never been checked or its configured interval has elapsed since the previous check.

Blocking network requests run through worker threads so that they do not directly block the scheduler's event loop.

The scheduler is process-local. Running multiple application workers can start duplicate schedulers. A larger deployment should use a separate scheduler or persistent job queue with coordination between workers.

## 8. Uptime Calculation

The application calculates uptime from checks recorded during the preceding 24 hours.

```text
Uptime percentage =
    successful checks / total recorded checks * 100
```

If no checks exist in the period, the uptime result is `null` and the dashboard displays an unavailable value.

This is an estimate based on recorded check attempts. It does not establish availability before monitoring began or during periods when no checks were recorded.

## 9. API and Browser Interaction

The dashboard uses the following endpoints:

- `/api/health` for application and database health
- `/api/stats` for dashboard metrics
- `/api/monitors` to list or create monitors
- `/api/monitors/{id}` to retrieve, update, or delete a monitor
- `/api/monitors/{id}/check` to initiate a check
- `/api/monitors/{id}/checks` to retrieve history

The `/docs` route provides interactive API documentation while the server is running.

## 10. Testing Strategy

`test_main.py` uses pytest and FastAPI's test client.

The test fixture:

- Overrides the SQLite path with a temporary database.
- Replaces the background scheduler with an idle coroutine.
- Prevents test data from entering the normal local database.

HTTP responses are mocked in success and failure tests so that outcomes do not depend on external website availability.

The test suite covers:

- Dashboard and static-file delivery
- Monitor creation and listing
- Request validation
- Monitor updates and deletion
- Successful and unsuccessful simulated checks
- Check-history persistence
- Statistics
- Rejection of local destinations
- Rejection of non-standard ports
- Rejection of mixed public/private DNS results
- Verification that the outbound request uses the IP address returned by validation

Run the suite using:

```bash
python -m pytest -v
```

## 11. Known Limitations

This implementation is intended for learning and local development.

It does not currently provide:

- User authentication or authorization
- Production alert delivery
- A durable task queue
- Distributed scheduling
- Database retention and archival policies
- Complete protection against SSRF or DNS-related attacks
- Production-scale monitoring concurrency controls
- Comprehensive production observability

The development server should not be exposed directly to the public internet.

## 12. Future Improvements

Potential extensions include:

- Authentication and role-based permissions
- Email and webhook alerts
- SSL certificate-expiration alerts
- Configurable incident thresholds
- Stronger network egress controls
- Concurrency and rate limiting
- Historical uptime reports
- Database migrations and retention policies
- GitHub Actions automated testing
- Production deployment and monitoring
