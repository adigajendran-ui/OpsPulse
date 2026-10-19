
# OpsPulse

**A local-first website uptime monitoring and performance dashboard built with Python, FastAPI, SQLite, and JavaScript.**

OpsPulse lets developers monitor public websites, measure response times, review historical check results, and inspect availability from a single dashboard.

The project demonstrates full-stack development, REST API design, relational data storage, background scheduling, automated testing, and frontend integration.

## Features

- **Website monitoring:** Add public HTTP and HTTPS endpoints.
- **Response-time tracking:** Measure and record request latency.
- **Historical check results:** Store timestamps, status codes, success states, and errors.
- **Automatic checks:** Recheck active monitors according to their configured intervals.
- **Monitor management:** Create, view, update, pause, resume, and delete monitors.
- **Uptime statistics:** Calculate availability from recorded check results.
- **Interactive dashboard:** View monitor status, response-time history, and recent activity.
- **Search and filtering:** Find monitors by name, URL, or status.
- **REST API:** Manage monitors through documented HTTP endpoints.
- **Automated tests:** Test core API behavior using pytest and FastAPI's test client.
- **Local persistence:** Use SQLite without running a separate database server.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application and monitoring logic |
| FastAPI | REST API and application server |
| SQLite | Persistent monitor and check-history storage |
| HTTPX | HTTP requests to monitored websites |
| HTML | Dashboard structure |
| CSS | Responsive interface and visual styling |
| JavaScript | Dashboard interactions and API integration |
| pytest | Automated test suite |

## Requirements

- Python 3.12 or newer is recommended.
- Visual Studio Code or another code editor.
- An internet connection for checks against public websites.
- Git, if you want to track changes or publish the repository.

## Getting Started

### 1. Clone or download the project

If you already have this project locally, open its `OpsPulse` folder in your terminal.

If you are cloning from GitHub:

```bash
git clone YOUR_REPOSITORY_URL
cd OpsPulse
```

Replace `YOUR_REPOSITORY_URL` with your repository's actual clone URL.

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

The virtual environment keeps project dependencies separate from packages used by other Python projects.

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Start the application

From the project's root directory, run:

```bash
python -m uvicorn main:app --reload
```

Open the dashboard:

http://127.0.0.1:8000

Open the interactive API documentation:

http://127.0.0.1:8000/docs

Check application health:

http://127.0.0.1:8000/api/health

Keep the terminal running while using the application. Press `Ctrl+C` to stop the server.

## Running the Tests

Install the project dependencies first, then run:

```bash
python -m pytest -v
```

The automated tests use a temporary SQLite database and mocked HTTP responses for deterministic check tests. They are designed not to modify the normal `opspulse.db` database.

The suite verifies behavior such as:

- Dashboard and static-file delivery
- Monitor creation and listing
- Request validation
- Monitor updates and deletion
- Successful and unsuccessful checks
- Check-history persistence
- Dashboard statistics
- Local-address rejection
- Missing-monitor error responses

## API Overview

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Check application and database availability |
| GET | `/api/stats` | Retrieve dashboard statistics |
| GET | `/api/monitors` | List monitors |
| POST | `/api/monitors` | Create a monitor |
| GET | `/api/monitors/{id}` | Retrieve one monitor |
| PATCH | `/api/monitors/{id}` | Update a monitor |
| DELETE | `/api/monitors/{id}` | Delete a monitor and its check history |
| POST | `/api/monitors/{id}/check` | Trigger a manual check |
| GET | `/api/monitors/{id}/checks` | Retrieve recorded checks |

Interactive endpoint documentation is available at `/docs` while the server is running.

## Project Structure

```text
OpsPulse/
├── main.py
├── test_main.py
├── requirements.txt
├── README.md
├── .gitignore
├── opspulse.db          # Generated locally; not committed
├── docs/
│   └── architecture.md
├── static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── .venv/               # Local virtual environment; not committed
```

The database and virtual environment are created or maintained locally. They should not be required in a source-code repository.

## How Uptime Is Calculated

OpsPulse calculates uptime from recorded check results within the preceding 24 hours.

**Uptime percentage = successful checks / total recorded checks × 100**

This is an estimate based on the monitoring history collected by this instance. It does not establish historical availability from before monitoring began, and it is not a substitute for a production-grade monitoring service.

## Security and Limitations

OpsPulse is currently a local development and learning project, not a hardened production service.

- Authentication and user permissions have not been implemented.
- The monitoring engine is intended for public endpoints you own or are authorized to monitor.
- The application includes basic checks against local and private IP destinations, but the current implementation is not sufficient protection for a publicly exposed monitoring service.
- DNS rebinding and time-of-check/time-of-use risks require further mitigation before public deployment.
- Redirects are not automatically followed.
- HTTP responses with status codes from 200 through 399 count as reachable.
- The scheduler runs inside the application process. Running multiple application workers can cause duplicate monitoring loops.
- Alert delivery, durable job queues, retention policies, and production observability are not yet implemented.

Do not expose this development server directly to the public internet. Production deployment requires additional security and reliability work.

## Possible Future Improvements

- Authentication and authorization
- Email or webhook alerts
- SSL certificate-expiration monitoring
- Configurable alert thresholds
- Improved DNS resolution safeguards
- Rate limiting and request concurrency controls
- Historical uptime charts and reporting
- Database retention and cleanup policies
- CI workflows that run automated tests
- Production deployment and operational monitoring

## Learning Goals

This project is intended to demonstrate how a complete application combines:

- Frontend and backend development
- REST API design
- Relational database modeling
- Scheduled work and external HTTP requests
- Automated testing
- Input validation and defensive programming
- Documentation and version control

## License

No license has been selected for this project yet.
