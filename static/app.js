"use strict";

/* =========================================================
   OpsPulse — Frontend application
   ========================================================= */

const state = {
    monitors: [],
    stats: null,
    selectedMonitorId: null,
    selectedChecks: [],
    recentChecks: [],
    search: "",
    filter: "all",
    refreshing: false
};

const $ = (selector) => document.querySelector(selector);

const monitorRows = $("#monitor-rows");
const activityRows = $("#activity-rows");
const addMonitorDialog = $("#add-monitor-dialog");
const addMonitorForm = $("#add-monitor-form");


/* =========================================================
   1. API CLIENT
   ========================================================= */

async function api(path, options = {}) {
    const headers = {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {})
    };

    const response = await fetch(path, {
        ...options,
        headers
    });

    let body = null;

    try {
        body = await response.json();
    } catch {
        // Some responses may not contain JSON.
    }

    if (!response.ok) {
        const message =
            typeof body?.detail === "string"
                ? body.detail
                : `Request failed with HTTP ${response.status}.`;

        throw new Error(message);
    }

    return body;
}


/* =========================================================
   2. FORMATTING AND SAFETY HELPERS
   ========================================================= */

function escapeHTML(value) {
    const replacements = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    };

    return String(value ?? "").replace(
        /[&<>"']/g,
        (character) => replacements[character]
    );
}

function formatLatency(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
        return "—";
    }

    const latency = Number(value);

    if (latency < 1000) {
        return `${Math.round(latency)} ms`;
    }

    return `${(latency / 1000).toFixed(2)} s`;
}

function formatPercent(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
        return "—";
    }

    return `${Number(value).toFixed(2)}%`;
}

function formatDateTime(value) {
    if (!value) {
        return "Never";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "Unknown";
    }

    return date.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit"
    });
}

function formatRelativeTime(value) {
    if (!value) {
        return "Never";
    }

    const date = new Date(value);
    const timestamp = date.getTime();

    if (Number.isNaN(timestamp)) {
        return "Unknown";
    }

    const elapsedSeconds = Math.max(
        0,
        Math.floor((Date.now() - timestamp) / 1000)
    );

    if (elapsedSeconds < 10) {
        return "Just now";
    }

    if (elapsedSeconds < 60) {
        return `${elapsedSeconds}s ago`;
    }

    const elapsedMinutes = Math.floor(elapsedSeconds / 60);

    if (elapsedMinutes < 60) {
        return `${elapsedMinutes}m ago`;
    }

    const elapsedHours = Math.floor(elapsedMinutes / 60);

    if (elapsedHours < 24) {
        return `${elapsedHours}h ago`;
    }

    const elapsedDays = Math.floor(elapsedHours / 24);

    if (elapsedDays < 30) {
        return `${elapsedDays}d ago`;
    }

    return formatDateTime(value);
}

function formatInterval(seconds) {
    const value = Number(seconds);

    if (!Number.isFinite(value)) {
        return "—";
    }

    if (value < 60) {
        return `Every ${value}s`;
    }

    if (value % 3600 === 0) {
        return `Every ${value / 3600}h`;
    }

    if (value % 60 === 0) {
        return `Every ${value / 60}m`;
    }

    return `Every ${value}s`;
}

function displayStatus(monitor) {
    if (!monitor.active) {
        return "paused";
    }

    if (monitor.status === "up") {
        return "up";
    }

    if (monitor.status === "down") {
        return "down";
    }

    return "unknown";
}

function statusTitle(status) {
    const labels = {
        up: "Operational",
        down: "Down",
        unknown: "Not checked",
        paused: "Paused"
    };

    return labels[status] || "Not checked";
}


/* =========================================================
   3. STATUS INDICATORS AND NOTIFICATIONS
   ========================================================= */

function setAPIStatus(connected) {
    const indicator = $("#api-status");
    const label = $("#api-status-label");

    indicator.classList.toggle("connected", connected);
    indicator.classList.toggle("disconnected", !connected);

    label.textContent = connected
        ? "API connected"
        : "API unavailable";
}

function showToast(message, type = "success") {
    const container = $("#toast-container");
    const toast = document.createElement("div");

    toast.className = `toast ${type}`;

    const icon = document.createElement("span");
    icon.className = "toast-icon";
    icon.textContent =
        type === "success" ? "✓" :
        type === "error" ? "!" : "i";

    const text = document.createElement("span");
    text.textContent = message;

    toast.append(icon, text);
    container.appendChild(toast);

    window.setTimeout(() => {
        toast.remove();
    }, 4800);
}


/* =========================================================
   4. DASHBOARD STATISTICS
   ========================================================= */

function renderStats() {
    if (!state.stats) {
        return;
    }

    const stats = state.stats;

    $("#metric-total").textContent = stats.total_monitors ?? 0;
    $("#metric-up").textContent = stats.up_monitors ?? 0;
    $("#metric-down").textContent = stats.down_monitors ?? 0;

    $("#metric-latency").textContent =
        formatLatency(stats.average_latency_last_24h_ms);

    $("#sidebar-monitor-count").textContent =
        stats.total_monitors ?? 0;

    $("#monitor-count-badge").textContent =
        `${stats.total_monitors ?? 0} ${
            Number(stats.total_monitors) === 1 ? "monitor" : "monitors"
        }`;
}


/* =========================================================
   5. MONITOR TABLE
   ========================================================= */

function getFilteredMonitors() {
    const search = state.search.trim().toLowerCase();

    return state.monitors.filter((monitor) => {
        const status = displayStatus(monitor);

        const matchesSearch =
            !search ||
            monitor.name.toLowerCase().includes(search) ||
            monitor.url.toLowerCase().includes(search);

        const matchesFilter =
            state.filter === "all" ||
            status === state.filter;

        return matchesSearch && matchesFilter;
    });
}

function renderMonitors() {
    const monitors = getFilteredMonitors();

    $("#monitor-table-wrap").classList.toggle(
        "hidden",
        monitors.length === 0
    );

    $("#monitor-empty").classList.toggle(
        "hidden",
        monitors.length !== 0
    );

    if (monitors.length === 0) {
        const noMonitors = state.monitors.length === 0;

        $("#monitor-empty-title").textContent = noMonitors
            ? "No monitors yet"
            : "No matching monitors";

        $("#monitor-empty-text").textContent = noMonitors
            ? "Add a public website to start collecting uptime data."
            : "Try a different search or change the status filter.";

        $("#monitor-table-summary").textContent = noMonitors
            ? "No websites added yet"
            : "No results match your filters";

        monitorRows.innerHTML = "";
        $("#check-all-button").disabled = true;
        return;
    }

    const activeCount = state.monitors.filter(
        (monitor) => monitor.active
    ).length;

    $("#check-all-button").disabled = activeCount === 0;

    $("#monitor-table-summary").textContent =
        `Showing ${monitors.length} of ${state.monitors.length} monitors`;

    monitorRows.innerHTML = monitors.map((monitor) => {
        const status = displayStatus(monitor);
        const id = Number(monitor.id);
        const uptime = formatPercent(monitor.uptime_24h_percent);
        const latency = formatLatency(monitor.last_latency_ms);

        const statusHTML = `
            <span class="status-label ${status}">
                <span class="status-pip"></span>
                ${escapeHTML(statusTitle(status))}
            </span>
        `;

        return `
            <tr>
                <td>
                    <div class="monitor-cell">
                        <div class="monitor-favicon" aria-hidden="true">◎</div>
                        <div class="monitor-identity">
                            <span class="monitor-name"
                                  title="${escapeHTML(monitor.name)}">
                                ${escapeHTML(monitor.name)}
                            </span>
                            <span class="monitor-url"
                                  title="${escapeHTML(monitor.url)}">
                                ${escapeHTML(monitor.url)}
                            </span>
                        </div>
                    </div>
                </td>

                <td class="status-cell">${statusHTML}</td>

                <td class="cell-strong">${escapeHTML(latency)}</td>

                <td class="cell-strong">${escapeHTML(uptime)}</td>

                <td class="cell-muted">
                    ${escapeHTML(formatInterval(monitor.interval_seconds))}
                </td>

                <td>
                    <div class="row-actions">
                        <button
                            type="button"
                            class="table-action"
                            data-action="history"
                            data-id="${id}">
                            History
                        </button>

                        <button
                            type="button"
                            class="table-action"
                            data-action="check"
                            data-id="${id}">
                            Check
                        </button>

                        <button
                            type="button"
                            class="table-action"
                            data-action="toggle"
                            data-id="${id}">
                            ${monitor.active ? "Pause" : "Resume"}
                        </button>

                        <button
                            type="button"
                            class="table-action danger"
                            data-action="delete"
                            data-id="${id}"
                            aria-label="Delete ${escapeHTML(monitor.name)}">
                            Delete
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}


/* =========================================================
   6. MONITOR SELECTOR
   ========================================================= */

function renderMonitorSelector() {
    const select = $("#selected-monitor-select");

    if (state.monitors.length === 0) {
        select.innerHTML = `<option value="">No monitors available</option>`;
        select.disabled = true;
        return;
    }

    select.disabled = false;

    select.innerHTML = state.monitors.map((monitor) => `
        <option value="${Number(monitor.id)}">
            ${escapeHTML(monitor.name)}
        </option>
    `).join("");

    if (state.selectedMonitorId !== null) {
        select.value = String(state.selectedMonitorId);
    }
}


/* =========================================================
   7. RESPONSE-TIME CHART
   ========================================================= */

function formatAxisDate(value) {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "";
    }

    return date.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit"
    });
}

function renderLatencyChart(checks) {
    const svg = $("#latency-chart");

    const validChecks = checks
        .filter((check) =>
            Number.isFinite(Number(check.latency_ms))
        )
        .slice()
        .reverse();

    if (validChecks.length === 0) {
        svg.innerHTML = `
            <text x="450" y="115" text-anchor="middle">
                No check history yet
            </text>
            <text x="450" y="140" text-anchor="middle">
                Run a check to start collecting response-time data.
            </text>
        `;

        $("#chart-check-count").textContent = "No checks recorded yet";
        $("#chart-time-range").textContent = "Waiting for first result";
        $("#chart-latest-latency").textContent = "—";
        return;
    }

    const values = validChecks.map(
        (check) => Number(check.latency_ms)
    );

    const maximum = Math.max(...values, 10);

    const plot = {
        left: 64,
        right: 878,
        top: 25,
        bottom: 211
    };

    const plotWidth = plot.right - plot.left;
    const plotHeight = plot.bottom - plot.top;

    const points = values.map((value, index) => {
        const x = validChecks.length === 1
            ? plot.left + plotWidth / 2
            : plot.left +
              (index / (validChecks.length - 1)) * plotWidth;

        const y = plot.bottom - (value / maximum) * plotHeight;

        return { x, y, value };
    });

    const grid = [];

    for (let index = 0; index <= 4; index++) {
        const ratio = index / 4;
        const y = plot.top + ratio * plotHeight;
        const label = Math.round(maximum * (1 - ratio));

        grid.push(`
            <line
                x1="${plot.left}"
                y1="${y}"
                x2="${plot.right}"
                y2="${y}"
                stroke="#e9eef3"
                stroke-width="1"
                stroke-dasharray="4 5"
            />

            <text
                x="${plot.left - 12}"
                y="${y + 4}"
                text-anchor="end">
                ${label}
            </text>
        `);
    }

    const linePoints = points.map(
        (point) => `${point.x},${point.y}`
    ).join(" ");

    const circles = points.map((point, index) => `
        <circle
            cx="${point.x}"
            cy="${point.y}"
            r="${index === points.length - 1 ? 4 : 2.6}"
            fill="${index === points.length - 1 ? "#ffffff" : "#20b99d"}"
            stroke="#20b99d"
            stroke-width="${index === points.length - 1 ? 2.5 : 1.3}">
            <title>${formatLatency(point.value)}</title>
        </circle>
    `).join("");

    const first = validChecks[0];
    const middle = validChecks[Math.floor((validChecks.length - 1) / 2)];
    const last = validChecks[validChecks.length - 1];

    const labels = [
        {
            x: plot.left,
            value: formatAxisDate(first.checked_at),
            anchor: "start"
        },
        {
            x: plot.left + plotWidth / 2,
            value: formatAxisDate(middle.checked_at),
            anchor: "middle"
        },
        {
            x: plot.right,
            value: formatAxisDate(last.checked_at),
            anchor: "end"
        }
    ].map((label) => `
        <text
            x="${label.x}"
            y="250"
            text-anchor="${label.anchor}">
            ${escapeHTML(label.value)}
        </text>
    `).join("");

    const firstPoint = points[0];
    const lastPoint = points[points.length - 1];

    svg.innerHTML = `
        <defs>
            <linearGradient id="latency-area"
                            x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"
                      stop-color="#20b99d"
                      stop-opacity="0.19"/>
                <stop offset="100%"
                      stop-color="#20b99d"
                      stop-opacity="0.01"/>
            </linearGradient>
        </defs>

        ${grid.join("")}

        <polygon
            points="
                ${firstPoint.x},${plot.bottom}
                ${linePoints}
                ${lastPoint.x},${plot.bottom}
            "
            fill="url(#latency-area)"
        />

        <polyline
            points="${linePoints}"
            fill="none"
            stroke="#20b99d"
            stroke-width="2.6"
            stroke-linejoin="round"
            stroke-linecap="round"
        />

        ${circles}
        ${labels}
    `;

    $("#chart-latest-latency").textContent =
        formatLatency(validChecks[validChecks.length - 1].latency_ms);

    $("#chart-check-count").textContent =
        `${validChecks.length} recorded ${
            validChecks.length === 1 ? "check" : "checks"
        }`;

    $("#chart-time-range").textContent =
        `${formatAxisDate(first.checked_at)} — ${formatAxisDate(last.checked_at)}`;
}


/* =========================================================
   8. SELECTED MONITOR SNAPSHOT
   ========================================================= */

function renderSnapshot() {
    const monitor = state.monitors.find(
        (item) => Number(item.id) === Number(state.selectedMonitorId)
    );

    const checkButton = $("#snapshot-check-button");

    if (!monitor) {
        $("#snapshot-name").textContent = "No monitor selected";

        const link = $("#snapshot-url");
        link.textContent = "Add a website to begin";
        link.href = "#monitors";

        $("#snapshot-status").className = "status-pill unknown";
        $("#snapshot-status").textContent = "Not checked";

        $("#snapshot-uptime").textContent = "—";
        $("#snapshot-uptime-fill").style.width = "0%";
        $("#snapshot-lastchecked").textContent = "Never";
        $("#snapshot-http").textContent = "—";
        $("#snapshot-latency").textContent = "—";
        $("#snapshot-interval").textContent = "—";

        checkButton.disabled = true;
        return;
    }

    checkButton.disabled = false;

    $("#snapshot-name").textContent = monitor.name;

    const link = $("#snapshot-url");
    link.textContent = monitor.url;
    link.href = monitor.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";

    const status = displayStatus(monitor);
    const badge = $("#snapshot-status");

    badge.className = `status-pill ${status}`;
    badge.textContent = statusTitle(status);

    const uptime = monitor.uptime_24h_percent;

    $("#snapshot-uptime").textContent = formatPercent(uptime);

    $("#snapshot-uptime-fill").style.width =
        uptime === null || uptime === undefined
            ? "0%"
            : `${Math.max(0, Math.min(100, Number(uptime)))}%`;

    $("#snapshot-lastchecked").textContent =
        formatRelativeTime(monitor.last_checked_at);

    $("#snapshot-http").textContent =
        monitor.last_status_code === null ||
        monitor.last_status_code === undefined
            ? "—"
            : String(monitor.last_status_code);

    $("#snapshot-latency").textContent =
        formatLatency(monitor.last_latency_ms);

    $("#snapshot-interval").textContent =
        formatInterval(monitor.interval_seconds);
}


/* =========================================================
   9. CHECK HISTORY
   ========================================================= */

async function loadSelectedChecks() {
    const monitorId = state.selectedMonitorId;

    if (monitorId === null || monitorId === undefined) {
        state.selectedChecks = [];
        renderLatencyChart([]);
        renderSnapshot();
        return;
    }

    try {
        const result = await api(
            `/api/monitors/${Number(monitorId)}/checks?limit=50`
        );

        // The backend returns the newest check first.
        state.selectedChecks = result.checks || [];

        renderLatencyChart(state.selectedChecks);
        renderSnapshot();
    } catch (error) {
        console.error("Could not load selected monitor history:", error);

        state.selectedChecks = [];
        renderLatencyChart([]);
    }
}

async function loadRecentChecks() {
    // Restrict the history requests to the twelve most recently
    // checked monitors to keep the local dashboard responsive.
    const candidates = state.monitors
        .filter((monitor) => monitor.last_checked_at)
        .slice()
        .sort((a, b) =>
            new Date(b.last_checked_at).getTime() -
            new Date(a.last_checked_at).getTime()
        )
        .slice(0, 12);

    if (candidates.length === 0) {
        state.recentChecks = [];
        renderRecentChecks();
        return;
    }

    const results = await Promise.allSettled(
        candidates.map(async (monitor) => {
            const payload = await api(
                `/api/monitors/${Number(monitor.id)}/checks?limit=10`
            );

            return (payload.checks || []).map((check) => ({
                ...check,
                monitor_name: monitor.name
            }));
        })
    );

    state.recentChecks = results
        .filter((result) => result.status === "fulfilled")
        .flatMap((result) => result.value)
        .sort((a, b) =>
            new Date(b.checked_at).getTime() -
            new Date(a.checked_at).getTime()
        )
        .slice(0, 12);

    renderRecentChecks();
}

function renderRecentChecks() {
    const empty = state.recentChecks.length === 0;

    activityRows.closest("table").classList.toggle("hidden", empty);
    $("#activity-empty").classList.toggle("hidden", !empty);

    if (empty) {
        activityRows.innerHTML = "";
        return;
    }

    activityRows.innerHTML = state.recentChecks.map((check) => {
        const success = Boolean(check.success);

        return `
            <tr>
                <td>
                    <span class="activity-result ${success ? "success" : "failure"}">
                        <span class="result-indicator">
                            ${success ? "✓" : "!"}
                        </span>
                        ${success ? "Success" : "Failed"}
                    </span>
                </td>

                <td class="cell-strong">
                    ${escapeHTML(check.monitor_name)}
                </td>

                <td class="cell-muted">
                    ${escapeHTML(formatDateTime(check.checked_at))}
                </td>

                <td class="cell-strong">
                    ${check.status_code == null
                        ? "—"
                        : escapeHTML(check.status_code)}
                </td>

                <td class="cell-strong">
                    ${escapeHTML(formatLatency(check.latency_ms))}
                </td>
            </tr>
        `;
    }).join("");
}


/* =========================================================
   10. REFRESH THE APPLICATION
   ========================================================= */

async function loadDashboard(options = {}) {
    const quiet = Boolean(options.quiet);

    if (state.refreshing) {
        return;
    }

    state.refreshing = true;

    try {
        const [stats, monitorPayload] = await Promise.all([
            api("/api/stats"),
            api("/api/monitors")
        ]);

        state.stats = stats;
        state.monitors = monitorPayload.monitors || [];

        setAPIStatus(true);
        renderStats();

        const selectedStillExists = state.monitors.some(
            (monitor) =>
                Number(monitor.id) === Number(state.selectedMonitorId)
        );

        if (!selectedStillExists) {
            state.selectedMonitorId = state.monitors.length
                ? Number(state.monitors[0].id)
                : null;
        }

        renderMonitors();
        renderMonitorSelector();

        $("#selected-monitor-select").value =
            state.selectedMonitorId === null
                ? ""
                : String(state.selectedMonitorId);

        await loadSelectedChecks();
        await loadRecentChecks();

        const now = new Date();

        $("#last-updated").textContent =
            `Updated ${now.toLocaleTimeString([], {
                hour: "numeric",
                minute: "2-digit",
                second: "2-digit"
            })}`;

    } catch (error) {
        setAPIStatus(false);
        console.error("Dashboard refresh failed:", error);

        if (!quiet) {
            showToast(
                `Could not refresh OpsPulse: ${error.message}`,
                "error"
            );
        }
    } finally {
        state.refreshing = false;
    }
}


/* =========================================================
   11. ADD MONITOR
   ========================================================= */

function openAddMonitorDialog() {
    addMonitorForm.reset();
    addMonitorDialog.showModal();

    window.setTimeout(() => {
        $("#new-monitor-name").focus();
    }, 50);
}

async function submitNewMonitor(event) {
    event.preventDefault();

    const submitButton = $("#save-monitor-button");

    const payload = {
        name: $("#new-monitor-name").value.trim(),
        url: $("#new-monitor-url").value.trim(),
        interval_seconds: Number(
            $("#new-monitor-interval").value
        )
    };

    submitButton.disabled = true;
    submitButton.textContent = "Creating...";

    try {
        const result = await api("/api/monitors", {
            method: "POST",
            body: JSON.stringify(payload)
        });

        if (result.monitor?.id !== undefined) {
            state.selectedMonitorId = Number(result.monitor.id);
        }

        addMonitorDialog.close();
        addMonitorForm.reset();

        showToast(
            "Monitor created. Its first automatic check should run shortly.",
            "success"
        );

        await loadDashboard({ quiet: true });

    } catch (error) {
        showToast(`Could not create monitor: ${error.message}`, "error");
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = "Create monitor";
    }
}


/* =========================================================
   12. CHECK A MONITOR NOW
   ========================================================= */

async function checkMonitorNow(monitorId, button = null) {
    const previousText = button?.textContent;

    if (button) {
        button.disabled = true;
        button.textContent = "Checking...";
    }

    try {
        const result = await api(
            `/api/monitors/${Number(monitorId)}/check`,
            { method: "POST" }
        );

        const check = result.check;

        if (check.success) {
            showToast(
                `Check succeeded. Response time: ${formatLatency(check.latency_ms)}.`,
                "success"
            );
        } else {
            showToast(
                `Check failed: ${check.error || "The website did not respond successfully."}`,
                "error"
            );
        }

        await loadDashboard({ quiet: true });

    } catch (error) {
        showToast(`Could not run check: ${error.message}`, "error");
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = previousText || "Check";
        }
    }
}


/* =========================================================
   13. CHECK ALL ACTIVE MONITORS
   ========================================================= */

async function checkAllMonitors() {
    const button = $("#check-all-button");

    const activeMonitors = state.monitors.filter(
        (monitor) => monitor.active
    );

    if (activeMonitors.length === 0) {
        showToast("There are no active monitors to check.", "info");
        return;
    }

    const previousText = button.textContent;

    button.disabled = true;
    button.textContent = "Checking...";

    let successful = 0;
    let failed = 0;

    try {
        // Perform checks sequentially rather than sending a large
        // burst of requests at once.
        for (const monitor of activeMonitors) {
            try {
                const result = await api(
                    `/api/monitors/${Number(monitor.id)}/check`,
                    { method: "POST" }
                );

                if (result.check.success) {
                    successful++;
                } else {
                    failed++;
                }
            } catch (error) {
                failed++;
                console.error(
                    `Check failed for monitor ${monitor.id}:`,
                    error
                );
            }
        }

        await loadDashboard({ quiet: true });

        showToast(
            `Check-all finished: ${successful} succeeded, ${failed} failed.`,
            failed > 0 ? "info" : "success"
        );

    } finally {
        button.textContent = previousText;
        button.disabled = !state.monitors.some(
            (monitor) => monitor.active
        );
    }
}


/* =========================================================
   14. PAUSE OR RESUME MONITOR
   ========================================================= */

async function toggleMonitor(monitor) {
    const nextActive = !monitor.active;

    try {
        await api(`/api/monitors/${Number(monitor.id)}`, {
            method: "PATCH",
            body: JSON.stringify({
                active: nextActive
            })
        });

        showToast(
            nextActive
                ? `${monitor.name} resumed.`
                : `${monitor.name} paused.`,
            "success"
        );

        await loadDashboard({ quiet: true });

    } catch (error) {
        showToast(`Could not update monitor: ${error.message}`, "error");
    }
}


/* =========================================================
   15. DELETE MONITOR
   ========================================================= */

async function deleteMonitor(monitor) {
    const confirmed = window.confirm(
        `Delete "${monitor.name}"?\n\n` +
        "This also permanently removes its recorded check history."
    );

    if (!confirmed) {
        return;
    }

    try {
        await api(`/api/monitors/${Number(monitor.id)}`, {
            method: "DELETE"
        });

        showToast(`${monitor.name} was deleted.`, "success");

        await loadDashboard({ quiet: true });

    } catch (error) {
        showToast(`Could not delete monitor: ${error.message}`, "error");
    }
}


/* =========================================================
   16. MONITOR TABLE ACTIONS
   ========================================================= */

monitorRows.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");

    if (!button) {
        return;
    }

    const monitorId = Number(button.dataset.id);

    const monitor = state.monitors.find(
        (item) => Number(item.id) === monitorId
    );

    if (!monitor) {
        showToast("That monitor could not be found. Refresh the page.", "error");
        return;
    }

    const action = button.dataset.action;

    if (action === "check") {
        await checkMonitorNow(monitorId, button);
        return;
    }

    if (action === "toggle") {
        await toggleMonitor(monitor);
        return;
    }

    if (action === "delete") {
        await deleteMonitor(monitor);
        return;
    }

    if (action === "history") {
        state.selectedMonitorId = monitorId;

        $("#selected-monitor-select").value = String(monitorId);

        renderSnapshot();
        await loadSelectedChecks();

        $("#performance").scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
    }
});


/* =========================================================
   17. EVENT LISTENERS
   ========================================================= */

$("#add-monitor-button").addEventListener(
    "click",
    openAddMonitorDialog
);

$("#add-monitor-empty").addEventListener(
    "click",
    openAddMonitorDialog
);

$("#close-monitor-dialog").addEventListener("click", () => {
    addMonitorDialog.close();
});

$("#cancel-monitor-button").addEventListener("click", () => {
    addMonitorDialog.close();
});

addMonitorForm.addEventListener("submit", submitNewMonitor);

$("#check-all-button").addEventListener(
    "click",
    checkAllMonitors
);

$("#refresh-button").addEventListener("click", async () => {
    const button = $("#refresh-button");

    button.classList.add("spinning");
    button.disabled = true;

    try {
        await loadDashboard();
    } finally {
        button.classList.remove("spinning");
        button.disabled = false;
    }
});

$("#activity-refresh-button").addEventListener(
    "click",
    () => loadDashboard()
);

$("#monitor-search").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderMonitors();
});

$("#status-filter").addEventListener("change", (event) => {
    state.filter = event.target.value;
    renderMonitors();
});

$("#selected-monitor-select").addEventListener("change", async (event) => {
    const value = event.target.value;

    state.selectedMonitorId = value ? Number(value) : null;

    renderSnapshot();
    await loadSelectedChecks();
});

$("#snapshot-check-button").addEventListener("click", async () => {
    if (state.selectedMonitorId !== null) {
        await checkMonitorNow(state.selectedMonitorId);
    }
});

// Keyboard shortcut: Ctrl+K or Cmd+K focuses monitor search.
document.addEventListener("keydown", (event) => {
    const isSearchShortcut =
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === "k";

    if (isSearchShortcut) {
        event.preventDefault();
        $("#monitor-search").focus();
    }
});

// Highlight the current in-page navigation item.
document.querySelectorAll('.sidebar-nav a[href^="#"]').forEach((link) => {
    link.addEventListener("click", () => {
        document.querySelectorAll(".sidebar-nav .nav-link").forEach((item) => {
            item.classList.remove("active");
        });

        link.classList.add("active");
    });
});


/* =========================================================
   18. STARTUP AND AUTO-REFRESH
   ========================================================= */

async function startApplication() {
    await loadDashboard();

    // Refresh the dashboard every 30 seconds.
    // The backend independently runs the actual monitor scheduler.
    window.setInterval(() => {
        loadDashboard({ quiet: true });
    }, 30000);
}

startApplication();