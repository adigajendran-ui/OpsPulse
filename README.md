
# OpsPulse

**A local-first website uptime monitoring and performance dashboard built with Python, FastAPI, SQLite, and JavaScript.**

OpsPulse lets developers monitor public websites, measure response times, review historical check results, and inspect availability from a dashboard.

The project demonstrates full-stack development, REST API design, database persistence, background scheduling, automated testing, defensive network programming, and frontend integration.

## Features

- **Website monitoring:** Add public HTTP and HTTPS endpoints.
- **Response-time tracking:** Measure and record request latency.
- **Historical check results:** Store timestamps, status codes, outcomes, and errors.
- **Automatic checks:** Recheck active monitors according to configured intervals.
- **Monitor management:** Create, view, update, pause, resume, and delete monitors.
- **Uptime statistics:** Calculate availability from recorded checks.
- **Interactive dashboard:** View monitor status, response-time history, and recent activity.
- **Search and filtering:** Find monitors by name, URL, or status.
- **REST API:** Manage monitors through documented HTTP endpoints.
- **Automated tests:** Verify important API and monitoring behavior with pytest.
- **Local persistence:** Use SQLite without running a separate database server.
- **Outbound request safeguards:** Validate DNS results, reject non-global addresses, restrict ports, and pin connections to a validated IP.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend and monitoring logic |
| FastAPI | REST API and application server |
| SQLite | Monitor and check-history storage |
| Python standard library | Pinned HTTP/HTTPS connections |
| HTML | Dashboard structure |
| CSS | Responsive interface |
| JavaScript | Dashboard interactions and API integration |
| pytest | Automated testing |
| Git | Version control |

## Requirements

- Python 3.12 or newer is recommended.
- Visual Studio Code or another code editor.
- Git for source control.
- An internet connection for real checks against public websites.

## Getting Started

### 1. Clone the repository

Replace the example repository URL with your actual GitHub repository URL.

```bash
git clone https://github.com/YOUR_USERNAME/OpsPulse.git
cd OpsPulse
```

If the project is already on your computer, open its existing folder instead of cloning it again.

### 2. Create a virtual environment

**Windows PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS or Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Run the application

From the root directory, run:

```bash
python -m uvicorn main:app --reload
```

Open the dashboard:

http://127.0.0.1:8000

Open interactive API documentation:

http://127.0.0.1:8000/docs

Check application health:

http://127.0.0.1:8000/api/health

Keep the terminal open while using the app. Press `Ctrl+C` to stop the server.

The application creates its local SQLite database when it starts.

## Running Automated Tests

With the virtual environment activated, run:

```bash
python -m pytest -v
```

The tests use a temporary database and mocked website responses to keep test results repeatable and avoid modifying the normal local monitoring database.

The suite covers:

- Dashboard and static-file delivery
- Monitor creation and listing
- Invalid URLs, names, and check intervals
- Monitor updates and deletion
- Successful and unsuccessful simulated HTTP checks
- Historical check storage and dashboard statistics
- Rejection of localhost and private-address destinations
- Rejection of unsupported ports
- Rejection of mixed public/private DNS results
- Verification that outbound requests use the IP returned by validation

## API Overview

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Check application and database availability |
| GET | `/api/stats` | Retrieve dashboard statistics |
| GET | `/api/monitors` | List monitors |
| POST | `/api/monitors` | Create a monitor |
| GET | `/api/monitors/{id}` | Retrieve a monitor |
| PATCH | `/api/monitors/{id}` | Update a monitor |
| DELETE | `/api/monitors/{id}` | Delete a monitor and its history |
| POST | `/api/monitors/{id}/check` | Trigger a manual check |
| GET | `/api/monitors/{id}/checks` | Retrieve check history |

Use `/docs` to explore and test API endpoints interactively.

## Project Structure

```text
OpsPulse/
├── main.py
├── test_main.py
├── requirements.txt
├── README.md
├── .gitignore
├── opspulse.db
├── docs/
│   └── architecture.md
├── static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── .venv/
```

`opspulse.db` and `.venv/` are local artifacts. They should not be committed to the repository.

## How Monitoring Works

A check performs the following operations:

1. Load the monitor configuration.
2. Validate the URL and destination.
3. Resolve the hostname and reject any non-global DNS result.
4. Connect to the selected validated IP address rather than resolving the hostname again during connection.
5. For HTTPS, retain hostname verification for the TLS certificate.
6. Make one GET request without following redirects.
7. Record status, response time, success state, and any error.
8. Update the monitor's latest result.

HTTP status codes from 200 through 399 count as reachable. Other responses are recorded as unsuccessful checks.

The uptime percentage is based on recorded checks in the preceding 24 hours:

```text
Uptime = successful checks / total recorded checks * 100
```

If there are no checks for the period, uptime is unavailable rather than zero.

## Security and Limitations

OpsPulse is currently a local development and learning project, not a hardened production service.

- Destination checks reject non-global IP addresses, including private and loopback destinations.
- Requests are restricted to standard HTTP port 80 and HTTPS port 443.
- Connections use the validated IP address to reduce DNS-rebinding exposure.
- HTTPS certificate verification uses the original hostname.
- Redirects are not automatically followed.
- The application does not currently implement user authentication or authorization.
- The destination safeguards are not a complete Server-Side Request Forgery (SSRF) defense.
- Public deployment would require further network egress restrictions, rate limits, concurrency controls, authorization, and independent security testing.
- The scheduler runs inside the application process. Multiple application workers can cause duplicate monitoring loops.
- Alert delivery, durable job queues, retention policies, and production observability are not implemented.

Do not expose the development server directly to the public internet.

## Possible Future Improvements

- Authentication and role-based authorization
- Email or webhook alerts
- SSL certificate-expiration alerts
- Configurable alert thresholds
- Improved DNS and outbound-network protections
- Rate limits and concurrency controls
- Historical uptime reports
- Database retention and cleanup policies
- GitHub Actions continuous integration
- Production deployment with independent monitoring

## Learning Goals

OpsPulse provides hands-on experience with:

- Frontend and backend development
- REST API design
- Relational database modeling
- Background scheduling and external HTTP requests
- Automated testing and regression checks
- Input validation and defensive programming
- Documentation and version control

## License

No license has been selected for this project yet.
