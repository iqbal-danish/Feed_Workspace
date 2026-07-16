// State Variables
let feeds = [];
let config = {};
let isMerging = false;
let eventSource = null;

// Modal State
let activeTab = "url"; // "url", "file", "sftp", "api"
let selectedFilePaths = []; // Selected local file paths from native dialog

// DOM Elements
const feedsListEl = document.getElementById("feeds-list");
const btnOpenAddModal = document.getElementById("btn-open-add-modal");
const btnClearFeeds = document.getElementById("btn-clear-feeds");
const btnBrowseOutput = document.getElementById("btn-browse-output");
const btnOpenOutput = document.getElementById("btn-open-output");
const btnRun = document.getElementById("btn-run");

const outputPathEl = document.getElementById("output-path");
const chkDeleteTemp = document.getElementById("chk-delete-temp");
const chkResetDb = document.getElementById("chk-reset-db");
const progressBarContainer = document.getElementById("global-progress-bar-container");

const gaugeFill = document.getElementById("gauge-fill");
const gaugeSpeedVal = document.getElementById("gauge-speed-val");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const sidebarSourceCount = document.getElementById("sidebar-source-count");
const badgeSourceCount = document.getElementById("badge-source-count");

const metricFeeds = document.getElementById("metric-feeds");
const metricJobs = document.getElementById("metric-jobs");
const metricDuplicates = document.getElementById("metric-duplicates");
const metricTime = document.getElementById("metric-time");

const consoleBody = document.getElementById("console-body");
const btnClearConsole = document.getElementById("btn-clear-console");
const telemetryTableBody = document.getElementById("telemetry-table-body");

// Modal DOM Elements
const addSourceModal = document.getElementById("add-source-modal");
const btnCloseModal = document.getElementById("btn-close-modal");
const btnCancelModal = document.getElementById("btn-cancel-modal");
const btnSaveModal = document.getElementById("btn-save-modal");
const modalFeedType = document.getElementById("modal-feed-type");

// Modal Input Sections
const sectionUrlInput = document.getElementById("section-url-input");
const sectionFileInput = document.getElementById("section-file-input");
const sectionSftpInput = document.getElementById("section-sftp-input");
const sectionApiInput = document.getElementById("section-api-input");
const sectionBulkInput = document.getElementById("section-bulk-input");
const modalInputBulk = document.getElementById("modal-input-bulk");

// Modal Fields (URL & File)
const modalInputUrl = document.getElementById("modal-input-url");
const modalFilePickerBtn = document.getElementById("modal-file-picker-btn");
const selectedFileLabel = document.getElementById("selected-file-label");

// Modal Fields (SFTP)
const sftpHost = document.getElementById("sftp-host");
const sftpPort = document.getElementById("sftp-port");
const sftpUser = document.getElementById("sftp-user");
const sftpPass = document.getElementById("sftp-pass");
const sftpPath = document.getElementById("sftp-path");

// Modal Fields (Secure API)
const apiUrl = document.getElementById("api-url");
const apiAuthType = document.getElementById("api-auth-type");
const apiToken = document.getElementById("api-token");
const apiKeyHeader = document.getElementById("api-key-header");
const apiKeyVal = document.getElementById("api-key-val");
const apiOauthUrl = document.getElementById("api-oauth-url");
const apiOauthId = document.getElementById("api-oauth-id");
const apiOauthSecret = document.getElementById("api-oauth-secret");

// Initialize Application
async function init() {
    bindEvents();
    await fetchConfig();
    await fetchFeeds();
    logSystem("Application workspace loaded successfully.");
}

// Bind Event Handlers
function bindEvents() {
    // Top-level buttons
    btnClearFeeds.addEventListener("click", clearAllFeeds);
    btnBrowseOutput.addEventListener("click", browseOutputFile);
    btnOpenOutput.addEventListener("click", openOutputFileLocally);
    btnRun.addEventListener("click", toggleMerge);
    btnClearConsole.addEventListener("click", clearConsole);

    // Modal triggers
    btnOpenAddModal.addEventListener("click", openModal);
    btnCloseModal.addEventListener("click", closeModal);
    btnCancelModal.addEventListener("click", closeModal);
    btnSaveModal.addEventListener("click", saveModalSource);

    // Modal Dropdown Change Listener
    modalFeedType.addEventListener("change", (e) => {
        switchTab(e.target.value);
    });

    // Modal File Browser
    modalFilePickerBtn.addEventListener("click", browseLocalFeeds);

    // API Auth Type Select Toggle
    apiAuthType.addEventListener("change", toggleApiAuthFields);

    // Enter key triggers
    modalInputUrl.addEventListener("keyup", (e) => {
        if (e.key === "Enter") saveModalSource();
    });

    // Sidebar navigation scroll or tab selection
    const navWorkspace = document.getElementById("nav-workspace");
    const navConsole = document.getElementById("nav-console");

    navWorkspace.addEventListener("click", (e) => {
        e.preventDefault();
        navWorkspace.classList.add("active");
        navConsole.classList.remove("active");
        document.querySelector(".dashboard-grid").scrollIntoView({ behavior: "smooth" });
    });

    navConsole.addEventListener("click", (e) => {
        e.preventDefault();
        navConsole.classList.add("active");
        navWorkspace.classList.remove("active");
        document.getElementById("console-section").scrollIntoView({ behavior: "smooth" });
    });
}

// API: Fetch Configuration from Server
async function fetchConfig() {
    try {
        const res = await fetch("/api/config");
        config = await res.json();
        outputPathEl.value = config.output_file;
        chkDeleteTemp.checked = config.delete_temp_files;
        chkResetDb.checked = config.reset_duplicate_db;
    } catch (err) {
        logError("Failed to fetch configurations from server: " + err);
    }
}

// API: Fetch Feeds List from Server
async function fetchFeeds() {
    try {
        const res = await fetch("/api/feeds");
        feeds = await res.json();
        renderFeeds();
    } catch (err) {
        logError("Failed to fetch feeds list: " + err);
    }
}

// API: Save Feeds List to Server
async function saveFeeds() {
    try {
        await fetch("/api/feeds", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(feeds)
        });
        updateCounts();
    } catch (err) {
        logError("Failed to save feeds updates to server: " + err);
    }
}

// UI: Render Feed Cards List
function renderFeeds() {
    feedsListEl.innerHTML = "";
    if (feeds.length === 0) {
        feedsListEl.innerHTML = `
            <div class="feeds-empty">
                <i class="fa-solid fa-folder-open"></i>
                <p>No feeds loaded. Add a source to get started.</p>
            </div>
        `;
        updateCounts();
        renderPendingTelemetryTable();
        return;
    }

    feeds.forEach((feed, idx) => {
        const key = getFeedKey(feed);
        const iconClass = getFeedIconClass(feed.type);
        
        const li = document.createElement("li");
        li.className = "feed-item";
        li.innerHTML = `
            <div class="feed-info">
                <span class="feed-icon"><i class="${iconClass}"></i></span>
                <span class="feed-path" title="${key}">${key}</span>
            </div>
            <div class="feed-actions-btns">
                <button class="btn-feed-action btn-delete" data-index="${idx}" title="Remove Feed">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
        `;
        feedsListEl.appendChild(li);
    });

    // Bind delete buttons
    document.querySelectorAll(".btn-delete").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const idx = parseInt(btn.getAttribute("data-index"));
            deleteFeed(idx);
        });
    });

    updateCounts();
    renderPendingTelemetryTable();
}

// Helper to determine icon based on type
function getFeedIconClass(type) {
    if (type === "url") return "fa-solid fa-globe url-feed";
    if (type === "file") return "fa-solid fa-file-code file-feed";
    if (type === "sftp") return "fa-solid fa-server sftp-feed";
    if (type === "secure_api") return "fa-solid fa-shield-halved api-feed";
    return "fa-solid fa-folder-open";
}

// Helper to get string label representing feed configuration
function getFeedKey(feed) {
    if (feed.type === "url") return feed.url;
    if (feed.type === "file") return feed.path;
    if (feed.type === "sftp") return `sftp://${feed.host}${feed.remote_path}`;
    if (feed.type === "secure_api") return `secure-api://${feed.url}`;
    return "unknown";
}

// Modal actions: Open Modal
function openModal() {
    addSourceModal.classList.add("active");
    
    // Reset dropdown value
    modalFeedType.value = "url";
    switchTab("url");
    
    // Clear URL & File
    modalInputUrl.value = "";
    modalInputBulk.value = "";
    selectedFilePaths = [];
    selectedFileLabel.textContent = "No files selected";

    // Clear SFTP
    sftpHost.value = "";
    sftpPort.value = "22";
    sftpUser.value = "";
    sftpPass.value = "";
    sftpPath.value = "";

    // Clear Secure API
    apiUrl.value = "";
    apiAuthType.value = "none";
    apiToken.value = "";
    apiKeyHeader.value = "X-API-Key";
    apiKeyVal.value = "";
    apiOauthUrl.value = "";
    apiOauthId.value = "";
    apiOauthSecret.value = "";
    toggleApiAuthFields();
}

// Modal actions: Close Modal
function closeModal() {
    addSourceModal.classList.remove("active");
}

// Modal actions: Switch Tab
function switchTab(tab) {
    activeTab = tab;

    // Manage forms section class
    sectionUrlInput.classList.add("hidden");
    sectionFileInput.classList.add("hidden");
    sectionSftpInput.classList.add("hidden");
    sectionApiInput.classList.add("hidden");
    sectionBulkInput.classList.add("hidden");

    if (tab === "url") {
        sectionUrlInput.classList.remove("hidden");
        modalInputUrl.focus();
    } else if (tab === "file") {
        sectionFileInput.classList.remove("hidden");
    } else if (tab === "sftp") {
        sectionSftpInput.classList.remove("hidden");
        sftpHost.focus();
    } else if (tab === "api") {
        sectionApiInput.classList.remove("hidden");
        apiUrl.focus();
    } else if (tab === "bulk") {
        sectionBulkInput.classList.remove("hidden");
        modalInputBulk.focus();
    }
}

// Toggle Secure API sub forms fields depending on Auth Type Select
function toggleApiAuthFields() {
    const selectedAuth = apiAuthType.value;
    
    // Hide all
    document.querySelectorAll(".api-auth-fields").forEach(div => {
        div.classList.add("hidden");
    });

    if (selectedAuth === "bearer") {
        document.getElementById("api-bearer-fields").classList.remove("hidden");
    } else if (selectedAuth === "api_key") {
        document.getElementById("api-key-fields").classList.remove("hidden");
    } else if (selectedAuth === "oauth2") {
        document.getElementById("api-oauth2-fields").classList.remove("hidden");
    }
}

// Modal action: Save source
async function saveModalSource() {
    let feedCfg = {};

    if (activeTab === "url") {
        const url = modalInputUrl.value.trim();
        if (!url) {
            alert("Please enter a feed URL.");
            return;
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            alert("URL must start with http:// or https://");
            return;
        }
        
        feedCfg = { type: "url", url: url };
        if (feeds.some(f => getFeedKey(f) === getFeedKey(feedCfg))) {
            alert("This URL feed source already exists.");
            return;
        }
        feeds.push(feedCfg);
        logSystem(`Added URL source: ${url}`);
    } 
    else if (activeTab === "file") {
        if (selectedFilePaths.length === 0) {
            alert("Please select at least one local XML feed file.");
            return;
        }
        
        let addedCount = 0;
        selectedFilePaths.forEach(path => {
            const fileCfg = { type: "file", path: path };
            if (!feeds.some(f => getFeedKey(f) === getFeedKey(fileCfg))) {
                feeds.push(fileCfg);
                addedCount++;
            }
        });
        logSystem(`Added ${addedCount} local file source(s).`);
    } 
    else if (activeTab === "sftp") {
        const host = sftpHost.value.trim();
        const port = sftpPort.value.trim() || "22";
        const user = sftpUser.value.trim();
        const pass = sftpPass.value.trim();
        const path = sftpPath.value.trim();

        if (!host || !user || !pass || !path) {
            alert("Please fill in all SFTP parameters.");
            return;
        }

        feedCfg = {
            type: "sftp",
            host: host,
            port: parseInt(port),
            username: user,
            password: pass,
            remote_path: path
        };

        if (feeds.some(f => getFeedKey(f) === getFeedKey(feedCfg))) {
            alert("This SFTP source already exists.");
            return;
        }
        feeds.push(feedCfg);
        logSystem(`Added SFTP source: sftp://${host}${path}`);
    } 
    else if (activeTab === "api") {
        const url = apiUrl.value.trim();
        const auth = apiAuthType.value;

        if (!url) {
            alert("Please enter API Endpoint URL.");
            return;
        }

        feedCfg = {
            type: "secure_api",
            url: url,
            auth_type: auth
        };

        if (auth === "bearer") {
            const token = apiToken.value.trim();
            if (!token) {
                alert("Please enter Authorization Token.");
                return;
            }
            feedCfg.auth_token = token;
        } else if (auth === "api_key") {
            const header = apiKeyHeader.value.trim();
            const val = apiKeyVal.value.trim();
            if (!header || !val) {
                alert("Please enter API Key headers parameters.");
                return;
            }
            feedCfg.api_key_header = header;
            feedCfg.api_key_value = val;
        } else if (auth === "oauth2") {
            const tUrl = apiOauthUrl.value.trim();
            const cId = apiOauthId.value.trim();
            const cSecret = apiOauthSecret.value.trim();
            if (!tUrl || !cId || !cSecret) {
                alert("Please fill in all OAuth2 parameters.");
                return;
            }
            feedCfg.oauth2_token_url = tUrl;
            feedCfg.oauth2_client_id = cId;
            feedCfg.oauth2_client_secret = cSecret;
        }

        if (feeds.some(f => getFeedKey(f) === getFeedKey(feedCfg))) {
            alert("This Secure API source already exists.");
            return;
        }
        feeds.push(feedCfg);
        logSystem(`Added Authenticated API source: ${url}`);
    } 
    else if (activeTab === "bulk") {
        const text = modalInputBulk.value.trim();
        if (!text) {
            alert("Please paste some feed URLs or paths.");
            return;
        }
        
        const lines = text.split("\n").map(l => l.trim()).filter(l => l.length > 0);
        let addedCount = 0;
        
        lines.forEach(line => {
            let itemCfg = {};
            if (line.startsWith("http://") || line.startsWith("https://")) {
                itemCfg = { type: "url", url: line };
            } else {
                itemCfg = { type: "file", path: line };
            }
            
            if (!feeds.some(f => getFeedKey(f) === getFeedKey(itemCfg))) {
                feeds.push(itemCfg);
                addedCount++;
            }
        });
        
        logSystem(`Bulk imported ${addedCount} feed source(s).`);
    }

    renderFeeds();
    await saveFeeds();
    closeModal();
}

// Action: Trigger host native file selector for input XML feeds
async function browseLocalFeeds() {
    try {
        logSystem("Opening file browser on host computer...");
        const res = await fetch("/api/browse/input", { method: "POST" });
        const data = await res.json();
        if (data.paths && data.paths.length > 0) {
            selectedFilePaths = data.paths;
            if (selectedFilePaths.length === 1) {
                selectedFileLabel.textContent = selectedFilePaths[0];
            } else {
                selectedFileLabel.textContent = `${selectedFilePaths.length} files selected`;
            }
            logSystem(`Selected local file feeds: ${selectedFilePaths.join(", ")}`);
        } else {
            selectedFilePaths = [];
            selectedFileLabel.textContent = "No files selected";
        }
    } catch (err) {
        logError("Failed to trigger local file dialog: " + err);
    }
}

// Action: Delete Feed from List
async function deleteFeed(idx) {
    const removed = feeds.splice(idx, 1);
    renderFeeds();
    await saveFeeds();
    logSystem(`Feed source removed: ${getFeedKey(removed[0])}`);
}

// Action: Clear All Feeds
async function clearAllFeeds() {
    if (feeds.length === 0) return;
    if (!confirm("Are you sure you want to clear all feed sources?")) return;
    feeds = [];
    renderFeeds();
    await saveFeeds();
    logSystem("All feed sources cleared.");
}

// Action: Browse Output File (Triggers Tkinter dialog on Python Host)
async function browseOutputFile() {
    try {
        logSystem("Opening file browser on host computer...");
        const res = await fetch("/api/browse/output", { method: "POST" });
        const data = await res.json();
        if (data.path) {
            outputPathEl.value = data.path;
            logSystem(`Output XML destination set to: ${data.path}`);
        }
    } catch (err) {
        logError("Failed to trigger folder browser: " + err);
    }
}

// Action: Open Output File locally using native OS handler
async function openOutputFileLocally() {
    const path = outputPathEl.value;
    if (!path) {
        alert("Please configure an output path first.");
        return;
    }
    
    try {
        logSystem(`Requesting server to open file: ${path}`);
        const res = await fetch("/api/open-output", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: path })
        });
        const data = await res.json();
        if (data.status === "error") {
            alert(`Could not open file: ${data.message}`);
            logError(`Open output file failed: ${data.message}`);
        } else {
            logSystem("Merged XML opened successfully in default application.");
        }
    } catch (err) {
        logError("Open output file network failure: " + err);
    }
}

// Update counters in layout
function updateCounts() {
    const countText = `${feeds.length} source${feeds.length !== 1 ? 's' : ''}`;
    sidebarSourceCount.textContent = `${countText} configured`;
    badgeSourceCount.textContent = countText;
}

// Action: Toggle Run Merger
async function toggleMerge() {
    if (isMerging) {
        alert("A merge is currently in progress. Please wait for completion.");
        return;
    }

    if (feeds.length === 0) {
        alert("Please configure at least one feed source before starting.");
        return;
    }

    // Set UI state to merging
    setMergingState(true);
    clearMetrics();

    // Start merge on server
    try {
        const payload = {
            feeds_file: config.feeds_file || "feeds.txt",
            output_file: outputPathEl.value || "output/merged.xml",
            delete_temp_files: chkDeleteTemp.checked,
            reset_duplicate_db: chkResetDb.checked
        };

        const res = await fetch("/api/merge/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        
        if (data.status === "success") {
            logSystem("Merge pipeline orchestrated. Subscribed to telemetry event stream.");
            listenToEvents();
        } else {
            logError("Failed to initiate merger: " + data.message);
            setMergingState(false);
        }
    } catch (err) {
        logError("Network failure launching merger: " + err);
        setMergingState(false);
    }
}

// SSE: Listen to EventStream from FastAPI
function listenToEvents() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource("/api/merge/events");

    eventSource.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleEventMessage(message);
    };

    eventSource.onerror = (err) => {
        logError("Telemetry stream interrupted. Reconnecting...");
    };
}

// Handle individual SSE messages
function handleEventMessage(msg) {
    if (msg.type === "log") {
        printLogLine(msg.message);
    } else if (msg.type === "progress") {
        updateStats(msg.data);
    } else if (msg.type === "done") {
        updateStats(msg.data);
        logSystem("Merge pipeline completed successfully!");
        alert(`Success! Successfully merged ${msg.data.jobs_written} jobs.`);
        finishMerge();
    } else if (msg.type === "error") {
        logError("Pipeline aborted: " + msg.message);
        alert("Pipeline error: " + msg.message);
        finishMerge();
    }
}

// Clean up after merger completes
function finishMerge() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    setMergingState(false);
}

// UI state helper
function setMergingState(merging) {
    isMerging = merging;
    if (merging) {
        btnRun.disabled = true;
        btnRun.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Running...`;
        statusDot.className = "status-dot active";
        statusText.textContent = "Merging";
        progressBarContainer.style.display = "block";
    } else {
        btnRun.disabled = false;
        btnRun.innerHTML = `<i class="fa-solid fa-play"></i> Run Merger`;
        statusDot.className = "status-dot";
        statusText.textContent = "Ready";
        progressBarContainer.style.display = "none";
    }
}

// Telemetry values rendering
function updateStats(data) {
    metricFeeds.textContent = `${data.successful_feeds} / ${data.total_feeds}`;
    metricJobs.textContent = data.jobs_written.toLocaleString();
    metricDuplicates.textContent = data.duplicates_removed.toLocaleString();
    metricTime.textContent = `${data.elapsed_seconds.toFixed(2)}s`;
    
    // Update SVG gauge
    updateGauge(data.jobs_per_second);
    
    // Update Feeds Table
    renderTelemetryTable(data.feeds);
}

// Render dynamic telemetry table during execution
function renderTelemetryTable(feedsData) {
    if (!telemetryTableBody || !feedsData) return;
    
    let html = "";
    Object.keys(feedsData).forEach(src => {
        const info = feedsData[src];
        
        // Format size
        let sizeText = "-";
        if (info.file_size_bytes > 0) {
            const kb = info.file_size_bytes / 1024;
            if (kb < 1024) {
                sizeText = `${kb.toFixed(1)} KB`;
            } else {
                const mb = kb / 1024;
                if (mb < 1024) {
                    sizeText = `${mb.toFixed(1)} MB`;
                } else {
                    sizeText = `${(mb / 1024).toFixed(1)} GB`;
                }
            }
        }
        
        // Jobs parsed / written text
        const jobsText = `${info.jobs_parsed.toLocaleString()} / ${info.jobs_written.toLocaleString()}`;
        
        // Status class
        const statusClass = `status-pill ${info.status}`;
        
        // Shorten path for display
        let displayName = src;
        if (src.startsWith("http://") || src.startsWith("https://")) {
            try {
                const url = new URL(src);
                displayName = url.pathname.split("/").pop() || src;
            } catch(e) {}
        } else if (src.startsWith("sftp://")) {
            displayName = src.split("/").pop() || src;
        } else {
            displayName = src.split(/[\\/]/).pop() || src;
        }

        html += `
            <tr>
                <td title="${src}" style="font-weight: 500; color: var(--text-primary); max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    ${displayName}
                </td>
                <td>${sizeText}</td>
                <td>${jobsText}</td>
                <td style="text-align: right;">
                    <span class="${statusClass}">${info.status}</span>
                </td>
            </tr>
        `;
    });
    
    telemetryTableBody.innerHTML = html;
}

// Render initial/pending state of telemetry table
function renderPendingTelemetryTable() {
    if (!telemetryTableBody) return;
    if (feeds.length === 0) {
        telemetryTableBody.innerHTML = `
            <tr>
                <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 20px;">
                    No feeds configured
                </td>
            </tr>
        `;
        return;
    }
    
    let html = "";
    feeds.forEach(feed => {
        const src = getFeedKey(feed);
        let displayName = src;
        if (src.startsWith("http://") || src.startsWith("https://")) {
            try {
                const url = new URL(src);
                displayName = url.pathname.split("/").pop() || src;
            } catch(e) {}
        } else if (src.startsWith("sftp://")) {
            displayName = src.split("/").pop() || src;
        } else {
            displayName = src.split(/[\\/]/).pop() || src;
        }
        
        html += `
            <tr>
                <td title="${src}" style="font-weight: 500; color: var(--text-primary); max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    ${displayName}
                </td>
                <td>-</td>
                <td>0 / 0</td>
                <td style="text-align: right;">
                    <span class="status-pill pending">pending</span>
                </td>
            </tr>
        `;
    });
    telemetryTableBody.innerHTML = html;
}

// SVG Gauge stroke offset calculation
function updateGauge(speed) {
    gaugeSpeedVal.textContent = speed.toFixed(1);
    
    const maxSpeed = 500.0;
    const ratio = Math.min(speed / maxSpeed, 1.0);
    
    // Half circle path length is approx 126px
    const maxOffset = 126;
    const offset = maxOffset - (maxOffset * ratio);
    
    gaugeFill.style.strokeDashoffset = offset;
    
    // Shift color if extremely fast
    if (speed >= 300) {
        gaugeFill.style.stroke = "var(--green-emerald)";
    } else {
        gaugeFill.style.stroke = "var(--accent-blue)";
    }
}

// Reset stats labels
function clearMetrics() {
    metricFeeds.textContent = "0 / " + feeds.length;
    metricJobs.textContent = "0";
    metricDuplicates.textContent = "0";
    metricTime.textContent = "0.00s";
    updateGauge(0.0);
    
    // Clear details table
    if (telemetryTableBody) {
        telemetryTableBody.innerHTML = `
            <tr>
                <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 20px;">
                    Waiting for pipeline...
                </td>
            </tr>
        `;
    }
}

// Logger helpers
function printLogLine(text) {
    const line = document.createElement("div");
    line.className = "console-line";
    
    // Color coding logs based on type
    if (text.includes(" INFO ")) {
        line.classList.add("info-line");
    } else if (text.includes(" WARNING ")) {
        line.classList.add("warn-line");
    } else if (text.includes(" ERROR ") || text.includes(" Failed ")) {
        line.classList.add("error-line");
    } else {
        line.classList.add("system-line");
    }
    
    line.textContent = text;
    consoleBody.appendChild(line);
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

// System logging helpers
function logSystem(msg) {
    const time = new Date().toLocaleTimeString([], { hour12: false });
    printLogLine(`[${time}] SYSTEM: ${msg}`);
}

// Error logging helpers
function logError(msg) {
    const time = new Date().toLocaleTimeString([], { hour12: false });
    printLogLine(`[${time}] ERROR: ${msg}`);
}

function clearConsole() {
    consoleBody.innerHTML = "";
    logSystem("Console cleared.");
}

// Run initialization
window.onload = init;
