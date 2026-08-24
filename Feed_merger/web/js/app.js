// State Variables
let feeds = [];
let config = {};
let isMerging = false;
let eventSource = null;
let lastProgressData = null;
let feedFilterText = "";
let telemetryFilterText = "";
let rafScheduled = false;

// Modal State
let activeTab = "url";
let selectedFilePaths = [];

// DOM Elements
const feedsListEl = document.getElementById("feeds-list");
const searchFeedsInput = document.getElementById("search-feeds-input");
const searchTelemetryInput = document.getElementById("search-telemetry-input");
const btnOpenAddModal = document.getElementById("btn-open-add-modal");
const btnClearFeeds = document.getElementById("btn-clear-feeds");
const btnBrowseOutput = document.getElementById("btn-browse-output");
const btnOpenOutput = document.getElementById("btn-open-output");
const btnRun = document.getElementById("btn-run");

const outputPathEl = document.getElementById("output-path");
const chkDeleteTemp = document.getElementById("chk-delete-temp");
const chkResetDb = document.getElementById("chk-reset-db");
const chkTagSource = document.getElementById("chk-tag-source");
const progressBarContainer = document.getElementById("global-progress-bar-container");
const globalProgressBar = document.getElementById("global-progress-bar");
const progressPercentageText = document.getElementById("progress-percentage-text");
const progressStatusSubtitle = document.getElementById("progress-status-subtitle");

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

// Add Source Modal DOM Elements
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

// Modal Fields
const modalInputUrl = document.getElementById("modal-input-url");
const modalFilePickerBtn = document.getElementById("modal-file-picker-btn");
const selectedFileLabel = document.getElementById("selected-file-label");

const sftpHost = document.getElementById("sftp-host");
const sftpPort = document.getElementById("sftp-port");
const sftpUser = document.getElementById("sftp-user");
const sftpPass = document.getElementById("sftp-pass");
const sftpPath = document.getElementById("sftp-path");

const apiUrl = document.getElementById("api-url");
const apiAuthType = document.getElementById("api-auth-type");
const apiToken = document.getElementById("api-token");
const apiKeyHeader = document.getElementById("api-key-header");
const apiKeyVal = document.getElementById("api-key-val");
const apiOauthUrl = document.getElementById("api-oauth-url");
const apiOauthId = document.getElementById("api-oauth-id");
const apiOauthSecret = document.getElementById("api-oauth-secret");

// Summary Modal DOM Elements
const mergeCompleteModal = document.getElementById("merge-complete-modal");
const btnCloseSummaryModal = document.getElementById("btn-close-summary-modal");
const btnOpenSummaryFile = document.getElementById("btn-open-summary-file");
const btnCopySummaryPath = document.getElementById("btn-copy-summary-path");
const summaryHeroJobs = document.getElementById("summary-hero-jobs");
const summaryFeedsRatio = document.getElementById("summary-feeds-ratio");
const summaryDuplicatesCount = document.getElementById("summary-duplicates-count");
const summaryParsedCount = document.getElementById("summary-parsed-count");
const summaryElapsedTime = document.getElementById("summary-elapsed-time");
const summaryOutputFilename = document.getElementById("summary-output-filename");
const summaryOutputPath = document.getElementById("summary-output-path");
const summaryFileSize = document.getElementById("summary-file-size");
const failedFeedsSection = document.getElementById("failed-feeds-section");
const failedHeaderToggle = document.getElementById("failed-header-toggle");
const failedCountLabel = document.getElementById("failed-count-label");
const failedChevron = document.getElementById("failed-chevron");
const failedListWrapper = document.getElementById("failed-list-wrapper");
const failedList = document.getElementById("failed-list");

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

    // Search filters
    if (searchFeedsInput) {
        searchFeedsInput.addEventListener("input", (e) => {
            feedFilterText = e.target.value.toLowerCase().trim();
            renderFeeds();
        });
    }

    if (searchTelemetryInput) {
        searchTelemetryInput.addEventListener("input", (e) => {
            telemetryFilterText = e.target.value.toLowerCase().trim();
            if (lastProgressData) {
                renderTelemetryTable(lastProgressData.feeds);
            } else {
                renderPendingTelemetryTable();
            }
        });
    }

    // Modal triggers
    btnOpenAddModal.addEventListener("click", openModal);
    btnCloseModal.addEventListener("click", closeModal);
    btnCancelModal.addEventListener("click", closeModal);
    btnSaveModal.addEventListener("click", saveModalSource);

    // Modal Dropdown Change Listener
    modalFeedType.addEventListener("change", (e) => {
        switchTab(e.target.value);
    });

    // Modal Bulk live typing listener
    if (modalInputBulk) {
        modalInputBulk.addEventListener("input", updateBulkPreview);
        modalInputBulk.addEventListener("paste", () => {
            setTimeout(updateBulkPreview, 50);
        });
    }

    // Modal File Browser
    modalFilePickerBtn.addEventListener("click", browseLocalFeeds);

    // API Auth Type Select Toggle
    apiAuthType.addEventListener("change", toggleApiAuthFields);

    // Summary modal handlers
    if (btnCloseSummaryModal) {
        btnCloseSummaryModal.addEventListener("click", () => {
            mergeCompleteModal.classList.remove("active");
        });
    }
    if (btnOpenSummaryFile) {
        btnOpenSummaryFile.addEventListener("click", openOutputFileLocally);
    }
    if (btnCopySummaryPath) {
        btnCopySummaryPath.addEventListener("click", copySummaryPathToClipboard);
    }
    if (failedHeaderToggle) {
        failedHeaderToggle.addEventListener("click", () => {
            const isHidden = failedListWrapper.classList.contains("hidden");
            if (isHidden) {
                failedListWrapper.classList.remove("hidden");
                failedChevron.style.transform = "rotate(180deg)";
            } else {
                failedListWrapper.classList.add("hidden");
                failedChevron.style.transform = "rotate(0deg)";
            }
        });
    }

    // Enter key triggers
    modalInputUrl.addEventListener("keyup", (e) => {
        if (e.key === "Enter") saveModalSource();
    });

    // Sidebar navigation
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

// API: Fetch Configuration
async function fetchConfig() {
    try {
        const res = await fetch("/api/config");
        config = await res.json();
        outputPathEl.value = config.output_file;
        chkDeleteTemp.checked = config.delete_temp_files;
        chkResetDb.checked = config.reset_duplicate_db;
        if (chkTagSource) {
            chkTagSource.checked = config.tag_source_feed || false;
        }
    } catch (err) {
        logError("Failed to fetch configurations from server: " + err);
    }
}

// API: Fetch Feeds List
async function fetchFeeds() {
    try {
        const res = await fetch("/api/feeds");
        feeds = await res.json();
        renderFeeds();
    } catch (err) {
        logError("Failed to fetch feeds list: " + err);
    }
}

// API: Save Feeds List
async function saveFeeds() {
    try {
        await fetch("/api/feeds", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(feeds)
        });
        updateCounts();
    } catch (err) {
        logError("Failed to save feeds updates: " + err);
    }
}

// UI: High-Performance Feeds List Rendering
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

    const filtered = feedFilterText
        ? feeds.filter(f => getFeedKey(f).toLowerCase().includes(feedFilterText))
        : feeds;

    if (filtered.length === 0) {
        feedsListEl.innerHTML = `
            <div class="feeds-empty" style="padding: 20px;">
                <p style="color: var(--text-muted);">No feeds matching "${feedFilterText}"</p>
            </div>
        `;
        updateCounts();
        return;
    }

    // Limit initial rendered items to 100 for instant UI responsiveness with 1,000+ feeds
    const displayItems = filtered.slice(0, 150);
    const fragment = document.createDocumentFragment();

    displayItems.forEach((feed) => {
        const key = getFeedKey(feed);
        const idx = feeds.indexOf(feed);
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
        fragment.appendChild(li);
    });

    if (filtered.length > displayItems.length) {
        const moreLi = document.createElement("li");
        moreLi.style.textAlign = "center";
        moreLi.style.padding = "10px";
        moreLi.style.color = "var(--text-muted)";
        moreLi.style.fontSize = "11px";
        moreLi.textContent = `... and ${filtered.length - displayItems.length} more feeds (filter above to search)`;
        fragment.appendChild(moreLi);
    }

    feedsListEl.appendChild(fragment);

    // Event delegation for delete buttons
    feedsListEl.querySelectorAll(".btn-delete").forEach(btn => {
        btn.onclick = () => {
            const idx = parseInt(btn.getAttribute("data-index"));
            deleteFeed(idx);
        };
    });

    updateCounts();
    if (!isMerging && !lastProgressData) {
        renderPendingTelemetryTable();
    }
}

function getFeedIconClass(type) {
    if (type === "url") return "fa-solid fa-globe url-feed";
    if (type === "file") return "fa-solid fa-file-code file-feed";
    if (type === "sftp") return "fa-solid fa-server sftp-feed";
    if (type === "secure_api") return "fa-solid fa-shield-halved api-feed";
    return "fa-solid fa-folder-open";
}

function getFeedKey(feed) {
    if (feed.type === "url") return feed.url;
    if (feed.type === "file") return feed.path;
    if (feed.type === "sftp") return `sftp://${feed.host}${feed.remote_path}`;
    if (feed.type === "secure_api") return `secure-api://${feed.url}`;
    return "unknown";
}

// Modal actions
function openModal() {
    addSourceModal.classList.add("active");
    modalFeedType.value = "url";
    switchTab("url");
    modalInputUrl.value = "";
    modalInputBulk.value = "";
    selectedFilePaths = [];
    selectedFileLabel.textContent = "No files selected";
    sftpHost.value = "";
    sftpPort.value = "22";
    sftpUser.value = "";
    sftpPass.value = "";
    sftpPath.value = "";
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

function closeModal() {
    addSourceModal.classList.remove("active");
}

function switchTab(tab) {
    activeTab = tab;
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

function toggleApiAuthFields() {
    const selectedAuth = apiAuthType.value;
    document.querySelectorAll(".api-auth-fields").forEach(div => div.classList.add("hidden"));
    if (selectedAuth === "bearer") {
        document.getElementById("api-bearer-fields").classList.remove("hidden");
    } else if (selectedAuth === "api_key") {
        document.getElementById("api-key-fields").classList.remove("hidden");
    } else if (selectedAuth === "oauth2") {
        document.getElementById("api-oauth2-fields").classList.remove("hidden");
    }
}

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
    } else if (activeTab === "file") {
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
    } else if (activeTab === "sftp") {
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
    } else if (activeTab === "api") {
        const url = apiUrl.value.trim();
        const auth = apiAuthType.value;

        if (!url) {
            alert("Please enter API Endpoint URL.");
            return;
        }

        feedCfg = { type: "secure_api", url: url, auth_type: auth };
        if (auth === "bearer") {
            const token = apiToken.value.trim();
            if (!token) { alert("Please enter Authorization Token."); return; }
            feedCfg.auth_token = token;
        } else if (auth === "api_key") {
            const header = apiKeyHeader.value.trim();
            const val = apiKeyVal.value.trim();
            if (!header || !val) { alert("Please enter API Key parameters."); return; }
            feedCfg.api_key_header = header;
            feedCfg.api_key_value = val;
        } else if (auth === "oauth2") {
            const tUrl = apiOauthUrl.value.trim();
            const cId = apiOauthId.value.trim();
            const cSecret = apiOauthSecret.value.trim();
            if (!tUrl || !cId || !cSecret) { alert("Please fill in all OAuth2 parameters."); return; }
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
    } else if (activeTab === "bulk") {
        const text = modalInputBulk ? modalInputBulk.value : "";
        const parsed = extractFeedsFromText(text);

        if (parsed.items.length === 0) {
            alert("No valid URLs or file paths detected. Please paste your feed sources.");
            return;
        }

        let addedCount = 0;
        parsed.items.forEach(itemCfg => {
            if (!feeds.some(f => getFeedKey(f) === getFeedKey(itemCfg))) {
                feeds.push(itemCfg);
                addedCount++;
            }
        });

        logSystem(`Bulk extracted and imported ${addedCount} feed source(s) (${parsed.dupeCount} batch duplicates skipped).`);
    }

    renderFeeds();
    await saveFeeds();
    closeModal();
}

// Smart Multi-URL and Local File Extractor
function extractFeedsFromText(rawText) {
    if (!rawText || !rawText.trim()) {
        return { items: [], urlsCount: 0, filesCount: 0, dupeCount: 0 };
    }

    let text = rawText.trim();
    // Separate glued URLs (e.g. https://site.com/a.xmlhttps://site.com/b.xml)
    text = text.replace(/([^\s,;"'<>()[\]{}|]+)(https?:\/\/)/gi, '$1 $2');
    // Decode HTML entities
    text = text.replace(/&amp;/gi, '&').replace(/&#38;/gi, '&');

    // Tokenize by spaces, tabs, newlines, commas, semicolons, pipes, or quotes
    const rawTokens = text.match(/(?:[^\s,;"'<>[\]{}|]+|"[^"]*"|'[^']*')+/g) || [];

    const extracted = [];
    const seenInBatch = new Set();
    let urlsCount = 0;
    let filesCount = 0;
    let dupeCount = 0;

    rawTokens.forEach(token => {
        let clean = token.trim();
        // Remove surrounding quotes, brackets, angles, or slashes
        clean = clean.replace(/^["'\[\]()<>{}\\]+|["'\[\]()<>{}\\]+$/g, '').trim();
        // Strip trailing punctuation (commas, periods, semicolons)
        clean = clean.replace(/[,;.:]+$/, '').trim();

        if (!clean) return;

        let itemCfg = null;
        if (/^https?:\/\//i.test(clean)) {
            itemCfg = { type: "url", url: clean };
            urlsCount++;
        } else if (
            /^[a-zA-Z]:[\\\/]/i.test(clean) ||
            clean.startsWith("/") ||
            clean.startsWith("./") ||
            clean.startsWith("../") ||
            /\.(xml|json|jsonl|gz)$/i.test(clean)
        ) {
            itemCfg = { type: "file", path: clean };
            filesCount++;
        } else if (clean.includes(".") && !clean.includes(" ") && clean.length > 4) {
            if (clean.includes("/") || clean.includes("\\")) {
                itemCfg = { type: "file", path: clean };
                filesCount++;
            } else {
                itemCfg = { type: "url", url: "https://" + clean };
                urlsCount++;
            }
        }

        if (itemCfg) {
            const key = getFeedKey(itemCfg);
            if (seenInBatch.has(key)) {
                dupeCount++;
            } else {
                seenInBatch.add(key);
                extracted.push(itemCfg);
            }
        }
    });

    return { items: extracted, urlsCount, filesCount, dupeCount };
}

// Update Live Detection Badges & Preview in Modal
function updateBulkPreview() {
    const raw = modalInputBulk ? modalInputBulk.value : "";
    const parsed = extractFeedsFromText(raw);

    const badgeTotal = document.getElementById("bulk-badge-total");
    const badgeUrls = document.getElementById("bulk-badge-urls");
    const badgeFiles = document.getElementById("bulk-badge-files");
    const previewWrap = document.getElementById("bulk-preview-wrap");
    const previewCount = document.getElementById("bulk-preview-count");
    const previewList = document.getElementById("bulk-preview-list");

    if (badgeTotal) badgeTotal.textContent = `${parsed.items.length} items detected`;
    if (badgeUrls) badgeUrls.textContent = `${parsed.urlsCount} URLs`;
    if (badgeFiles) badgeFiles.textContent = `${parsed.filesCount} Files`;

    if (!previewWrap || !previewList) return;

    if (parsed.items.length === 0) {
        previewWrap.style.display = "none";
        previewList.innerHTML = "";
        return;
    }

    previewWrap.style.display = "block";
    if (previewCount) previewCount.textContent = parsed.items.length;

    // Show first 24 chips in preview
    const sample = parsed.items.slice(0, 24);
    let html = "";
    sample.forEach(item => {
        const key = getFeedKey(item);
        const isUrl = item.type === "url";
        const icon = isUrl ? "fa-globe" : "fa-file-code";
        const chipClass = isUrl ? "chip-url" : "chip-file";
        const short = isUrl ? (key.split("/").pop() || key) : (key.split(/[\\/]/).pop() || key);
        html += `<span class="bulk-chip ${chipClass}" title="${key}"><i class="fa-solid ${icon}"></i> ${short}</span>`;
    });

    if (parsed.items.length > 24) {
        html += `<span class="bulk-chip" style="color: var(--text-muted);">+ ${parsed.items.length - 24} more</span>`;
    }

    previewList.innerHTML = html;
}

async function browseLocalFeeds() {
    try {
        logSystem("Opening file browser on host...");
        const res = await fetch("/api/browse/input", { method: "POST" });
        const data = await res.json();
        if (data.paths && data.paths.length > 0) {
            selectedFilePaths = data.paths;
            selectedFileLabel.textContent = selectedFilePaths.length === 1
                ? selectedFilePaths[0]
                : `${selectedFilePaths.length} files selected`;
            logSystem(`Selected local file feeds: ${selectedFilePaths.join(", ")}`);
        } else {
            selectedFilePaths = [];
            selectedFileLabel.textContent = "No files selected";
        }
    } catch (err) {
        logError("Failed to trigger local file dialog: " + err);
    }
}

async function deleteFeed(idx) {
    const removed = feeds.splice(idx, 1);
    renderFeeds();
    await saveFeeds();
    logSystem(`Feed source removed: ${getFeedKey(removed[0])}`);
}

async function clearAllFeeds() {
    if (feeds.length === 0) return;
    if (!confirm("Are you sure you want to clear all feed sources?")) return;
    feeds = [];
    renderFeeds();
    await saveFeeds();
    logSystem("All feed sources cleared.");
}

async function browseOutputFile() {
    try {
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

async function openOutputFileLocally() {
    const path = outputPathEl.value || "output/merged.xml";
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
            logSystem("Merged XML opened successfully.");
        }
    } catch (err) {
        logError("Open output file network failure: " + err);
    }
}

function copySummaryPathToClipboard() {
    const path = outputPathEl.value || "output/merged.xml";
    navigator.clipboard.writeText(path).then(() => {
        btnCopySummaryPath.innerHTML = `<i class="fa-solid fa-check"></i> Copied!`;
        setTimeout(() => {
            btnCopySummaryPath.innerHTML = `<i class="fa-solid fa-copy"></i> Copy Path`;
        }, 2000);
    });
}

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

    setMergingState(true);
    clearMetrics();

    try {
        const payload = {
            feeds_file: config.feeds_file || "feeds.txt",
            output_file: outputPathEl.value || "output/merged.xml",
            delete_temp_files: chkDeleteTemp.checked,
            reset_duplicate_db: chkResetDb.checked,
            tag_source_feed: chkTagSource ? chkTagSource.checked : false,
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

// SSE: EventStream listener
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
        if (!isMerging) return;
        logError("Telemetry stream reconnecting...");
    };
}

function handleEventMessage(msg) {
    if (msg.type === "log") {
        printLogLine(msg.message);
    } else if (msg.type === "progress") {
        lastProgressData = msg.data;
        scheduleStatsRender(msg.data);
    } else if (msg.type === "done") {
        lastProgressData = msg.data;
        updateStatsImmediate(msg.data);
        if (globalProgressBar) {
            globalProgressBar.style.width = "100%";
            globalProgressBar.style.background = "#10b981";
        }
        if (progressPercentageText) {
            progressPercentageText.textContent = "100%";
        }
        if (progressStatusSubtitle) {
            progressStatusSubtitle.textContent = `Completed all ${msg.data.total_feeds} feeds!`;
        }
        logSystem(`Merge pipeline complete: ${msg.data.jobs_written.toLocaleString()} unique jobs written.`);
        finishMerge();
        showCompletionModal(msg.data);
    } else if (msg.type === "error") {
        logError("Pipeline aborted: " + msg.message);
        alert("Pipeline error: " + msg.message);
        finishMerge();
    }
}

function finishMerge() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    setMergingState(false);
}

function setMergingState(merging) {
    isMerging = merging;
    if (merging) {
        btnRun.disabled = true;
        btnRun.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Merging...`;
        statusDot.className = "status-dot active";
        statusText.textContent = "Merging";
        progressBarContainer.style.display = "block";
        globalProgressBar.style.background = "linear-gradient(90deg, #3b82f6, #06b6d4, #10b981)";
        globalProgressBar.style.width = "0%";
        progressPercentageText.textContent = "0%";
        progressStatusSubtitle.textContent = "Connecting to feed sources...";
    } else {
        btnRun.disabled = false;
        btnRun.innerHTML = `<i class="fa-solid fa-play"></i> Run Merger`;
        statusDot.className = "status-dot";
        statusText.textContent = "Ready";
    }
}

// Throttled stats rendering with requestAnimationFrame to eliminate UI stutter & flickering
function scheduleStatsRender(data) {
    if (!rafScheduled) {
        rafScheduled = true;
        requestAnimationFrame(() => {
            updateStatsImmediate(data);
            rafScheduled = false;
        });
    }
}

function updateStatsImmediate(data) {
    const total = data.total_feeds || feeds.length || 1;
    const completed = (data.successful_feeds || 0) + (data.failed_feeds || 0);
    const pct = Math.min(100, Math.round((completed / total) * 100));

    // Progress Bar
    globalProgressBar.style.width = `${pct}%`;
    progressPercentageText.textContent = `${pct}%`;
    progressStatusSubtitle.textContent = `Processed ${completed} of ${total} feeds (${pct}%)`;

    // Metrics Cards
    metricFeeds.textContent = `${data.successful_feeds} / ${total}`;
    metricJobs.textContent = data.jobs_written.toLocaleString();
    metricDuplicates.textContent = data.duplicates_removed.toLocaleString();
    metricTime.textContent = `${data.elapsed_seconds.toFixed(1)}s`;

    // SVG Speed Gauge
    updateGauge(data.jobs_per_second);

    // Optimized Telemetry Table Rendering
    renderTelemetryTable(data.feeds);
}

// Fast Telemetry Table: Renders only active or filtered rows to keep DOM lightweight
function renderTelemetryTable(feedsData) {
    if (!telemetryTableBody || !feedsData) return;

    const sources = Object.keys(feedsData);
    if (sources.length === 0) return;

    const filteredSources = telemetryFilterText
        ? sources.filter(s => s.toLowerCase().includes(telemetryFilterText))
        : sources;

    // Show up to 100 visible rows at once to guarantee 60fps scrolling
    const displaySources = filteredSources.slice(0, 100);
    let html = "";

    for (let i = 0; i < displaySources.length; i++) {
        const src = displaySources[i];
        const info = feedsData[src];

        let sizeText = "-";
        if (info.file_size_bytes > 0) {
            const kb = info.file_size_bytes / 1024;
            if (kb < 1024) sizeText = `${kb.toFixed(1)} KB`;
            else sizeText = `${(kb / 1024).toFixed(1)} MB`;
        }

        const jobsText = `${info.jobs_parsed.toLocaleString()} / ${info.jobs_written.toLocaleString()}`;
        const statusClass = `status-pill ${info.status}`;

        let displayName = src;
        if (src.startsWith("http://") || src.startsWith("https://")) {
            try {
                const url = new URL(src);
                displayName = url.pathname.split("/").pop() || src;
            } catch (e) {}
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
    }

    if (filteredSources.length > displaySources.length) {
        html += `
            <tr>
                <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 8px; font-size: 11px;">
                    ... and ${filteredSources.length - displaySources.length} more feeds (filter above)
                </td>
            </tr>
        `;
    }

    telemetryTableBody.innerHTML = html;
}

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

    const displayFeeds = feeds.slice(0, 100);
    let html = "";
    displayFeeds.forEach(feed => {
        const src = getFeedKey(feed);
        let displayName = src;
        if (src.startsWith("http://") || src.startsWith("https://")) {
            try {
                const url = new URL(src);
                displayName = url.pathname.split("/").pop() || src;
            } catch (e) {}
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

    if (feeds.length > displayFeeds.length) {
        html += `
            <tr>
                <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 8px; font-size: 11px;">
                    ... and ${feeds.length - displayFeeds.length} more feeds
                </td>
            </tr>
        `;
    }

    telemetryTableBody.innerHTML = html;
}

function updateGauge(speed) {
    const val = speed || 0;
    gaugeSpeedVal.textContent = val.toFixed(1);
    const maxSpeed = 1000.0;
    const ratio = Math.min(val / maxSpeed, 1.0);
    const maxOffset = 126;
    const offset = maxOffset - (maxOffset * ratio);
    gaugeFill.style.strokeDashoffset = offset;

    if (val >= 500) {
        gaugeFill.style.stroke = "var(--green-emerald)";
    } else {
        gaugeFill.style.stroke = "var(--accent-blue)";
    }
}

function clearMetrics() {
    metricFeeds.textContent = "0 / " + feeds.length;
    metricJobs.textContent = "0";
    metricDuplicates.textContent = "0";
    metricTime.textContent = "0.0s";
    updateGauge(0.0);
    if (globalProgressBar) {
        globalProgressBar.style.width = "0%";
        globalProgressBar.style.background = "linear-gradient(90deg, #3b82f6, #06b6d4, #10b981)";
    }
    if (progressPercentageText) progressPercentageText.textContent = "0%";
    if (progressStatusSubtitle) progressStatusSubtitle.textContent = "Ready to merge";
    lastProgressData = null;
    renderPendingTelemetryTable();
}

// Show Post-Merge Completion Modal with exact verified job count
function showCompletionModal(data) {
    if (!mergeCompleteModal) return;

    summaryHeroJobs.textContent = (data.jobs_written || 0).toLocaleString();
    summaryFeedsRatio.textContent = `${data.successful_feeds || 0} / ${data.total_feeds || feeds.length}`;
    summaryDuplicatesCount.textContent = (data.duplicates_removed || 0).toLocaleString();
    summaryParsedCount.textContent = (data.jobs_parsed || 0).toLocaleString();
    summaryElapsedTime.textContent = `${(data.elapsed_seconds || 0).toFixed(1)}s`;

    const outPath = outputPathEl.value || "output/merged.xml";
    summaryOutputPath.textContent = outPath;
    summaryOutputFilename.textContent = outPath.split(/[\\/]/).pop() || "merged.xml";

    // Failed feeds checking
    const failedSources = [];
    if (data.feeds) {
        Object.keys(data.feeds).forEach(k => {
            if (data.feeds[k].status === "failed") {
                failedSources.push({ url: k, error: data.feeds[k].error || "Download/parse timeout" });
            }
        });
    }

    if (failedSources.length > 0) {
        failedFeedsSection.classList.remove("hidden");
        failedCountLabel.textContent = `${failedSources.length} Feed(s) Failed`;
        failedList.innerHTML = failedSources.map(f => `
            <li class="failed-item">
                <span class="failed-url">${f.url}</span>
                <span class="failed-err">${f.error}</span>
            </li>
        `).join("");
    } else {
        failedFeedsSection.classList.add("hidden");
    }

    mergeCompleteModal.classList.add("active");
}

// Capped Logger helpers (max 400 lines in DOM to keep memory optimal)
function printLogLine(text) {
    const line = document.createElement("div");
    line.className = "console-line";

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

    // Cap terminal DOM nodes to 400
    while (consoleBody.childNodes.length > 400) {
        consoleBody.removeChild(consoleBody.firstChild);
    }
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

function logSystem(msg) {
    const time = new Date().toLocaleTimeString([], { hour12: false });
    printLogLine(`[${time}] SYSTEM: ${msg}`);
}

function logError(msg) {
    const time = new Date().toLocaleTimeString([], { hour12: false });
    printLogLine(`[${time}] ERROR: ${msg}`);
}

function clearConsole() {
    consoleBody.innerHTML = "";
    logSystem("Console cleared.");
}

window.onload = init;
