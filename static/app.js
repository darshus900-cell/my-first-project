// Active Tab Tracking
let currentTab = "dashboard";
let statsInterval = null;
let registeredUsersCache = [];

document.addEventListener("DOMContentLoaded", () => {
    // Start Clock
    updateClock();
    setInterval(updateClock, 1000);
    
    // Fetch settings and stats
    loadSettings();
    fetchStats();
    
    // Poll stats and attendance records every 3 seconds (live face recognition updates)
    statsInterval = setInterval(() => {
        fetchStats();
        if (currentTab === "logs" || currentTab === "dashboard") {
            fetchLogs();
        }
        if (currentTab === "faces") {
            fetchRegisteredFaces();
        }
    }, 3000);

    fetchLogs();
});

// --- CLOCK AND DATE ---
function updateClock() {
    const now = new Date();
    const timeLabel = document.getElementById("time-display");
    const dateLabel = document.getElementById("date-display");
    
    if (timeLabel) {
        timeLabel.innerText = now.toLocaleTimeString();
    }
    if (dateLabel) {
        const options = { month: 'long', day: 'numeric', year: 'numeric' };
        dateLabel.innerText = now.toLocaleDateString('en-US', options);
    }
}

// --- TAB NAVIGATION ---
function switchTab(tabId) {
    currentTab = tabId;
    
    // Switch active state of nav buttons
    const navButtons = document.querySelectorAll(".nav-btn");
    navButtons.forEach(btn => {
        if (btn.id === `btn-${tabId}`) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
    
    // Switch active state of tab containers
    const tabContents = document.querySelectorAll(".tab-content");
    tabContents.forEach(content => {
        if (content.id === `tab-${tabId}`) {
            content.classList.add("active");
        } else {
            content.classList.remove("active");
        }
    });

    // Specific triggers for tabs
    if (tabId === "logs") {
        fetchLogs();
    } else if (tabId === "dashboard") {
        fetchStats();
    } else if (tabId === "faces") {
        fetchRegisteredFaces();
    }
}

// --- CORE API INTERACTIONS ---

// 1. Fetch Stats & Recent Check-Ins (Dashboard)
function fetchStats() {
    fetch("/api/stats")
        .then(response => response.json())
        .then(data => {
            const regCount = document.getElementById("stat-registered-count");
            const markedCount = document.getElementById("stat-marked-count");
            const presCount = document.getElementById("stat-present-count");
            const absentCount = document.getElementById("stat-absent-count");
            const recentList = document.getElementById("recent-logs-list");
            
            if (regCount) regCount.innerText = data.total_registered;
            if (markedCount) markedCount.innerText = data.attendance_marked_today;
            if (presCount) presCount.innerText = data.present_today;
            if (absentCount) absentCount.innerText = data.absent_today;
            
            if (recentList) {
                recentList.innerHTML = "";
                if (data.recent_checkins.length === 0) {
                    recentList.innerHTML = `<li class="empty-list-msg">No attendance entries recorded today.</li>`;
                } else {
                    data.recent_checkins.forEach(log => {
                        const li = document.createElement("li");
                        li.className = "activity-item";
                        li.innerHTML = `
                            <span class="activity-name">${log.name}</span>
                            <span class="activity-time">${log.time}</span>
                        `;
                        recentList.appendChild(li);
                    });
                }
            }
        })
        .catch(err => console.error("Error fetching stats:", err));
}

// 2. Fetch Registered Faces
function fetchRegisteredFaces() {
    fetch("/api/users")
        .then(response => response.json())
        .then(users => {
            registeredUsersCache = users;
            renderRegisteredFaces(users);
        })
        .catch(err => console.error("Error fetching users:", err));
}

function renderRegisteredFaces(users) {
    const grid = document.getElementById("registered-faces-grid");
    if (!grid) return;

    grid.innerHTML = "";

    if (users.length === 0) {
        grid.innerHTML = `<div class="faces-empty-msg">No registered faces yet. Go to <strong>Register Face</strong> to add users.</div>`;
        return;
    }

    users.forEach(user => {
        const card = document.createElement("div");
        card.className = "face-card";
        card.dataset.name = user.name.toLowerCase();

        const photoUrl = user.face_image_path
            ? `/api/users/${encodeURIComponent(user.name)}/photo`
            : null;

        const statusClass = user.present_today ? "present" : "absent";
        const statusText = user.present_today ? "Present Today" : "Not Checked In";

        const imgHtml = photoUrl
            ? `<img src="${photoUrl}" alt="${user.name}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
            : "";
        const placeholderStyle = photoUrl ? "display:none" : "";

        card.innerHTML = `
            ${imgHtml}
            <div class="face-placeholder" style="${placeholderStyle}">👤</div>
            <h4>${user.name}</h4>
            <p class="reg-date">Registered: ${formatDateTime(user.created_at)}</p>
            <span class="status-badge ${statusClass}">${statusText}</span>
            <br>
            <button class="delete-btn">Remove User</button>
        `;
        card.querySelector(".delete-btn").addEventListener("click", () => deleteUser(user.name));
        grid.appendChild(card);
    });
}

function filterRegisteredFaces() {
    const query = document.getElementById("faces-search-input").value.toLowerCase().trim();
    if (!query) {
        renderRegisteredFaces(registeredUsersCache);
        return;
    }
    const filtered = registeredUsersCache.filter(u => u.name.toLowerCase().includes(query));
    renderRegisteredFaces(filtered);
}

function deleteUser(name) {
    if (!confirm(`Remove '${name}' from the system?`)) return;

    fetch(`/api/users/${encodeURIComponent(name)}`, { method: "DELETE" })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                fetchRegisteredFaces();
                fetchStats();
            } else {
                alert(`Error: ${data.message}`);
            }
        })
        .catch(err => console.error("Delete error:", err));
}

function formatDateTime(isoStr) {
    if (!isoStr) return "—";
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleString();
}

// 3. Fetch All Logs (Logs Tab)
function fetchLogs(dateFilter = "") {
    let url = "/api/attendance";
    if (dateFilter) {
        url += `?date=${dateFilter}`;
    }
    
    fetch(url)
        .then(response => response.json())
        .then(logs => {
            const tableBody = document.getElementById("attendance-table-body");
            if (!tableBody) return;
            
            tableBody.innerHTML = "";
            
            if (logs.length === 0) {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="6" class="table-empty">No registered users yet. Register faces first.</td>
                    </tr>
                `;
                return;
            }
            
            logs.forEach(log => {
                const tr = document.createElement("tr");
                const status = log.status || "Present";
                const statusClass = status === "Present" ? "present" : (status === "Absent" ? "absent" : "registered");
                tr.innerHTML = `
                    <td>${log.name}</td>
                    <td style="text-align: center;">${formatDateTime(log.registered_at)}</td>
                    <td style="text-align: center;">${log.date}</td>
                    <td style="text-align: center;">${log.time}</td>
                    <td style="text-align: center;">${log.check_in_method || "—"}</td>
                    <td style="text-align: center;"><span class="status-badge ${statusClass}">${status}</span></td>
                `;
                tableBody.appendChild(tr);
            });
        })
        .catch(err => console.error("Error fetching logs:", err));
}

// 3. Submit Registration AJAX
function submitRegistration() {
    const nameInput = document.getElementById("reg-name-input");
    const statusMsg = document.getElementById("registration-status-message");
    
    if (!nameInput || !statusMsg) return;
    
    const name = nameInput.value.trim();
    if (!name) {
        showStatusMessage(statusMsg, "Please enter a name for registration.", "error");
        return;
    }
    
    showStatusMessage(statusMsg, "Processing facial capture... Keep looking at the camera.", "info");
    
    const registerBtn = document.getElementById("btn-register-submit");
    if (registerBtn) {
        registerBtn.disabled = true;
        registerBtn.innerText = "Capturing face...";
    }

    fetch("/api/register", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ name: name })
    })
    .then(async (response) => {
        const data = await response.json();
        if (data.success) {
            showStatusMessage(statusMsg, `Success! ${data.message}`, "success");
            nameInput.value = "";
            const dateFilter = document.getElementById("logs-date-filter");
            if (dateFilter) dateFilter.value = "";
            const logsSearch = document.getElementById("logs-search-input");
            if (logsSearch) logsSearch.value = "";
            fetchStats();
            fetchLogs();
            fetchRegisteredFaces();
        } else {
            showStatusMessage(statusMsg, `Error: ${data.message}`, "error");
        }
    })
    .catch(err => {
        console.error("Error during registration:", err);
        showStatusMessage(statusMsg, "Server not running. Start with: python main.py", "error");
    })
    .finally(() => {
        if (registerBtn) {
            registerBtn.disabled = false;
            registerBtn.innerText = "Capture & Register Face";
        }
    });
}

// 4. Save Settings AJAX
function saveSettings() {
    const camSelect = document.getElementById("setting-camera-index");
    const livenessCb = document.getElementById("setting-liveness-toggle");
    const toleranceSlider = document.getElementById("setting-tolerance-slider");
    const statusMsg = document.getElementById("settings-status-message");
    
    if (!camSelect || !livenessCb || !toleranceSlider || !statusMsg) return;
    
    const payload = {
        camera_index: parseInt(camSelect.value),
        check_liveness: livenessCb.checked,
        tolerance: parseFloat(toleranceSlider.value)
    };
    
    showStatusMessage(statusMsg, "Applying settings & restarting camera source...", "info");
    
    fetch("/api/settings", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showStatusMessage(statusMsg, "Settings saved and applied successfully.", "success");
        } else {
            showStatusMessage(statusMsg, `Failed: ${data.message}`, "error");
        }
    })
    .catch(err => {
        console.error("Error saving settings:", err);
        showStatusMessage(statusMsg, "Failed to connect to the configuration service.", "error");
    });
}

// 5. Load Settings Config
function loadSettings() {
    fetch("/api/settings")
        .then(response => response.json())
        .then(settings => {
            const camSelect = document.getElementById("setting-camera-index");
            const livenessCb = document.getElementById("setting-liveness-toggle");
            const toleranceSlider = document.getElementById("setting-tolerance-slider");
            const valBadge = document.getElementById("tolerance-val-badge");
            
            if (camSelect) camSelect.value = settings.camera_index.toString();
            if (livenessCb) livenessCb.checked = settings.check_liveness;
            if (toleranceSlider) {
                toleranceSlider.value = settings.tolerance;
                if (valBadge) valBadge.innerText = settings.tolerance.toFixed(2);
            }
        })
        .catch(err => console.error("Error loading settings:", err));
}

// 6. Export Logs to CSV
function exportLogs() {
    const exportBtn = document.getElementById("btn-export-csv");
    const downloadBtn = document.getElementById("btn-download-csv");
    
    if (exportBtn) exportBtn.innerText = "⏳ Exporting...";
    
    fetch("/api/export")
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert("Logs successfully generated! Click 'Download CSV' to fetch it.");
                if (exportBtn) exportBtn.innerText = "✅ Exported";
                if (downloadBtn) downloadBtn.classList.remove("hidden");
            } else {
                alert(`Export failed: ${data.message}`);
                if (exportBtn) exportBtn.innerText = "❌ Failed";
            }
        })
        .catch(err => {
            console.error("Error exporting logs:", err);
            alert("Connection error while exporting logs.");
            if (exportBtn) exportBtn.innerText = "❌ Error";
        });
}


// --- TABLE FILTERING AND UTILITIES ---

function filterLogsTable() {
    const query = document.getElementById("logs-search-input").value.toLowerCase().trim();
    const rows = document.querySelectorAll("#attendance-table-body tr");
    
    rows.forEach(row => {
        if (row.querySelector(".table-empty")) return;
        const text = row.innerText.toLowerCase();
        if (text.includes(query)) {
            row.style.display = "";
        } else {
            row.style.display = "none";
        }
    });
}

function filterLogsByDate() {
    const dateVal = document.getElementById("logs-date-filter").value;
    fetchLogs(dateVal);
}

function clearLogsFilter() {
    document.getElementById("logs-search-input").value = "";
    document.getElementById("logs-date-filter").value = "";
    fetchLogs();
}

function updateToleranceValueLabel(val) {
    const badge = document.getElementById("tolerance-val-badge");
    if (badge) {
        badge.innerText = parseFloat(val).toFixed(2);
    }
}

// Helper: Show nice status messages below forms
function showStatusMessage(element, message, type) {
    element.className = "form-status-msg"; // Reset classes
    element.innerText = message;
    
    // Set style class
    if (type === "success") {
        element.classList.add("success");
    } else if (type === "error") {
        element.classList.add("error");
    } else {
        // Info or processing state
        element.style.color = "#a1a1aa";
        element.style.backgroundColor = "rgba(63, 63, 70, 0.15)";
        element.style.border = "1px solid rgba(63, 63, 70, 0.25)";
        element.style.padding = "10px 14px";
    }
}
