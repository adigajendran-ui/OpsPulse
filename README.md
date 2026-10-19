# OpsPulse

[![Tests](https://github.com/adigajendran-ui/OpsPulse/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/adigajendran-ui/OpsPulse/actions/workflows/tests.yml)

**A local-first website uptime monitoring and performance dashboard built with Python, FastAPI, SQLite, HTML, CSS, and JavaScript.**

OpsPulse monitors website availability, records check results, and presents monitoring data through a web dashboard. The project emphasizes reliable backend behavior, automated testing, and safer outbound network requests.

## Overview

OpsPulse is a portfolio project designed to demonstrate practical backend development, API design, database integration, frontend development, testing, and continuous integration.

Rather than relying on an external monitoring service, OpsPulse runs locally and stores monitoring data in SQLite.

## Features

- **Website availability monitoring** — perform checks against configured websites and inspect their results.
- **Response-time measurement** — collect performance measurements during monitoring checks.
- **Monitoring history** — store check results in a local SQLite database.
- **Dashboard and statistics** — view monitoring information through a browser-based interface.
- **Automated monitoring** — use the application's scheduler to run checks.
- **Outbound request safeguards** — validate destinations before connecting to monitored websites.
- **Automated quality checks** — run tests and linting locally and through GitHub Actions.
- **API documentation** — inspect the FastAPI-generated documentation at `/docs` while the application is running.

## Technology Stack

| Area | Technology |
|---|---|
| Language | Python |
| Backend framework | FastAPI |
| ASGI server | Uvicorn |
| Database | SQLite |
| HTTP client | HTTPX |
| Frontend | HTML, CSS, JavaScript |
| Testing | Pytest, pytest-cov |
| Code quality | Ruff |
| Continuous integration | GitHub Actions |

## Getting Started

### Prerequisites

- Python 3.12 or 3.13
- Git
- A web browser

### 1. Clone the repository

Replace the example URL with the URL of your GitHub repository.

```powershell
git clone https://github.com/adigajendran-ui/OpsPulse.git
cd OpsPulse
```

### 2. Create a virtual environment

On Windows using PowerShell:

```powershell
py -3.12 -m venv .venv
```

Activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell prevents activation because of its execution policy, run the following command in the current terminal and try activation again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Start OpsPulse

```powershell
python -m uvicorn main:app --reload
```

Open the dashboard in your browser:

**http://127.0.0.1:8000**

To view the automatically generated API documentation, visit:

**http://127.0.0.1:8000/docs**

Keep the terminal running while using the application. Stop the development server by pressing `Ctrl+C`.

## Running Tests

OpsPulse uses Pytest to test backend behavior, including input validation and network request handling.

Run the test suite:

```powershell
python -m pytest
```

Run tests with a coverage report:

```powershell
python -m pytest --cov=main --cov-report=term-missing
```

The project enforces a minimum coverage threshold of **85%**. To run the same coverage threshold check locally:

```powershell
python -m pytest --cov=main --cov-report=term-missing --cov-fail-under=85
```

Run Ruff to check code quality:

```powershell
python -m ruff check main.py
```

All checks should pass before changes are merged into the `main` branch.

## Continuous Integration

GitHub Actions automatically runs quality checks when changes are pushed and when pull requests target `main`.

The workflow includes:

- Python 3.12 and Python 3.13 test runs.
- Ruff linting.
- Automated Pytest execution.
- Test coverage reporting.
- An enforced minimum coverage threshold of 85%.

The CI badge at the top of this README links to the workflow results. A passing badge indicates that the latest relevant workflow run succeeded; it does not guarantee that every possible issue has been ruled out.

## Project Structure

```text
OpsPulse/
├── .github/
│   └── workflows/
│       └── tests.yml
├── docs/
│   └── architecture.md
├── static/
│   └── Frontend assets
├── main.py
├── test_main.py
├── requirements.txt
└── README.md
```

| File or directory | Purpose |
|---|---|
| `main.py` | FastAPI application, monitoring logic, persistence, and scheduling |
| `test_main.py` | Automated backend tests |
| `requirements.txt` | Python dependencies |
| `static/` | HTML, CSS, JavaScript, and other frontend assets |
| `docs/architecture.md` | Architecture and design documentation |
| `.github/workflows/tests.yml` | GitHub Actions continuous integration workflow |

## Network Safety

Because OpsPulse makes outbound requests to monitored websites, validating destinations is an important part of the design.

The monitoring implementation includes safeguards such as:

- Validating target URLs and restricting supported ports.
- Resolving hostnames and rejecting destinations that resolve to non-public IP addresses.
- Connecting to a validated, pinned IP address while preserving the original hostname for HTTPS certificate verification.
- Avoiding automatic redirect following, which helps prevent redirects from bypassing destination validation.

These measures help reduce the risk of server-side request forgery (SSRF) and unsafe outbound connections. They are not a substitute for a full security review.

**Deployment note:** OpsPulse is intended for local development and portfolio demonstration. Before exposing it to an untrusted network or deploying it publicly, review authentication, access controls, configuration, resource limits, and production deployment security.

## Architecture

At a high level, the application follows this flow:

1. A user interacts with the browser-based dashboard.
2. The FastAPI backend handles application requests and monitoring operations.
3. The monitoring logic validates destinations and performs outbound HTTP or HTTPS checks.
4. Results and related monitoring data are stored in SQLite.
5. The dashboard presents information derived from the stored data.

For more detail, see [`docs/architecture.md`](docs/architecture.md).

## Development Goals

OpsPulse is an evolving project. Potential future improvements include:

- Historical response-time and uptime charts.
- Configurable alerting for downtime or degraded performance.
- Improved monitoring summaries and reporting.
- Additional integration and end-to-end tests.
- More production-oriented configuration and deployment options.

These are planned enhancements, not claims about functionality already implemented.

## Learning Outcomes

This project demonstrates practical experience with:

- Building a Python web application with FastAPI.
- Persisting application data in SQLite.
- Implementing outbound HTTP and HTTPS monitoring.
- Writing automated tests for success and failure scenarios.
- Measuring and enforcing test coverage.
- Maintaining code quality with Ruff.
- Configuring CI with GitHub Actions.
- Using Git branches and pull requests to manage changes.
- Documenting software architecture and security considerations.

## License

No license has been specified yet. Unless a license is added to the repository, reuse and redistribution are subject to the applicable default copyright rules.