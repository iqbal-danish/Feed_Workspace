/**
 * XML & JSON Validator Pro — Front-end Javascript Controller.
 * Communicates with PySide6 backend via QWebChannel.
 */

"use strict";

document.addEventListener("DOMContentLoaded", () => {
    let pyBridge = null;
    let selectedFileOrUrl = null;
    let isValidationRunning = false;
    let validationErrors = [];
    let currentTheme = "dark";

    // SVG Icons
    const docIcon = `<svg xmlns="http://www.w3.org/2000/svg" style="width:16px;height:16px;" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>`;

    // ── Helper formatters ──────────────────────────────────────────────────
    function formatBytes(bytes) {
        if (!bytes) return "0 Bytes";
        const k = 1024;
        const sizes = ["Bytes", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
    }

    function formatDuration(sec) {
        if (sec === undefined || sec === null || isNaN(sec)) return "—";
        if (sec < 60) return sec.toFixed(1) + "s";
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${m}m ${s}s`;
    }

    // ── QWebChannel Setup ─────────────────────────────────────────────────
    if (typeof qt !== "undefined") {
        new QWebChannel(qt.webChannelTransport, (channel) => {
            pyBridge = channel.objects.pyBridge;
            console.log("QWebChannel connected successfully!");
            
            // Register bridge signals
            pyBridge.file_info_ready.connect((jsonStr) => { onFileInfoReady(JSON.parse(jsonStr)); });
            pyBridge.progress_updated.connect((jsonStr) => { onProgressUpdated(JSON.parse(jsonStr)); });
            pyBridge.error_found.connect((jsonStr) => { onErrorFound(JSON.parse(jsonStr)); });
            pyBridge.validation_complete.connect((jsonStr) => { onValidationComplete(JSON.parse(jsonStr)); });
            pyBridge.validation_failed.connect(onValidationFailed);
            pyBridge.recent_files_updated.connect((jsonStr) => { renderRecentFiles(JSON.parse(jsonStr)); });

            // Load initial settings and history
            pyBridge.load_settings((settingsJson) => {
                const settings = JSON.parse(settingsJson);
                currentTheme = settings.theme || "dark";
                document.body.className = currentTheme === "dark" ? "" : "light-theme";
                
                document.getElementById("setting-context").value = settings.context_line_count || 10;
                renderRecentFiles(settings.recent_files || []);
            });
        });
    } else {
        console.warn("Qt web channel transport is missing. Running in browser sandbox.");
    }

    // ── UI Updates ─────────────────────────────────────────────────────────
    function onFileInfoReady(info) {
        document.getElementById("meta-name").textContent = info.filename || "—";
        document.getElementById("meta-size").textContent = formatBytes(info.file_size) || "—";
        document.getElementById("meta-encoding").textContent = info.encoding || "—";
        document.getElementById("meta-root").textContent = (info.xml_version === "JSON" ? "JSON / " : "XML / ") + (info.root_element || "—");
    }

    function onProgressUpdated(progress) {
        // Check for download state (sentinel errors_found = -1)
        if (progress.errors_found === -1) {
            document.getElementById("validation-status").textContent = "Downloading...";
            document.getElementById("validation-status").style.color = "var(--warning)";
            
            document.getElementById("stat-speed").textContent = progress.processing_speed_mbps.toFixed(2) + " MB/s";
            document.getElementById("stat-bytes").textContent = formatBytes(progress.bytes_processed) + " / " + formatBytes(progress.total_bytes);
            document.getElementById("stat-eta").textContent = formatDuration(progress.estimated_remaining_seconds);
            
            setProgress(progress.percent_complete);
            return;
        }

        document.getElementById("validation-status").textContent = "Validating...";
        document.getElementById("validation-status").style.color = "var(--accent)";

        document.getElementById("stat-bytes").textContent = formatBytes(progress.bytes_processed) + " / " + formatBytes(progress.total_bytes);
        document.getElementById("stat-line").textContent = progress.current_line > 0 ? progress.current_line.toLocaleString() : "—";
        document.getElementById("stat-speed").textContent = progress.processing_speed_mbps.toFixed(2) + " MB/s";
        document.getElementById("stat-eta").textContent = formatDuration(progress.estimated_remaining_seconds);
        document.getElementById("stat-errors").textContent = progress.errors_found;
        
        if (progress.errors_found > 0) {
            document.getElementById("stat-errors").style.color = "var(--error)";
        }

        setProgress(progress.percent_complete);
    }

    function onErrorFound(error) {
        validationErrors.push(error);
        
        // Remove placeholder row if first error
        const tbody = document.getElementById("errors-tbody");
        if (validationErrors.length === 1) {
            tbody.innerHTML = "";
        }

        const tr = document.createElement("tr");
        tr.style.cursor = "pointer";
        tr.dataset.index = validationErrors.length - 1;

        const severityLower = (error.severity_name || "error").toLowerCase();
        let badgeClass = "badge-error";
        if (severityLower === "fatal") badgeClass = "badge-fatal";
        if (severityLower === "warning") badgeClass = "badge-warning";

        tr.innerHTML = `
            <td>${validationErrors.length}</td>
            <td><span class="badge ${badgeClass}">${error.severity_name || "ERROR"}</span></td>
            <td>${error.line.toLocaleString()}</td>
            <td>${error.column.toLocaleString()}</td>
            <td style="font-weight:600; color:var(--text-muted);">${error.category_name || "Syntax"}</td>
            <td style="word-break:break-all;">${error.message}</td>
        `;

        tr.addEventListener("click", () => {
            // Unselect previous
            const selected = tbody.querySelector(".selected");
            if (selected) selected.classList.remove("selected");
            tr.classList.add("selected");

            showContext(error);
        });

        tbody.appendChild(tr);
        document.getElementById("stat-errors").textContent = validationErrors.length;
        document.getElementById("stat-errors").style.color = "var(--error)";
    }

    function onValidationComplete(result) {
        isValidationRunning = false;
        setControlsState(false);

        document.getElementById("meta-duration").textContent = formatDuration(result.duration_seconds);

        const statusLabel = document.getElementById("validation-status");
        if (result.was_cancelled) {
            statusLabel.textContent = "Cancelled";
            statusLabel.style.color = "var(--warning)";
        } else if (result.has_errors) {
            statusLabel.textContent = "Complete (Errors Found)";
            statusLabel.style.color = "var(--error)";
        } else {
            statusLabel.textContent = "Complete (Valid Document)";
            statusLabel.style.color = "var(--success)";
            
            // Draw clean table empty state
            const tbody = document.getElementById("errors-tbody");
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; color: var(--success); font-weight: 600; padding: 40px 0;">
                        No errors! File is fully valid.
                    </td>
                </tr>
            `;
        }

        setProgress(100);
        document.getElementById("btn-export").disabled = false;
    }

    function onValidationFailed(msg) {
        isValidationRunning = false;
        setControlsState(false);

        document.getElementById("validation-status").textContent = "Failed";
        document.getElementById("validation-status").style.color = "var(--error)";
        
        alert("Validation Crashed:\n\n" + msg);
    }

    // Set SVG indicator offset
    function setProgress(percent) {
        const circle = document.getElementById("progress-indicator");
        const radius = circle.r.baseVal.value;
        const circumference = 2 * Math.PI * radius;
        
        const offset = circumference - (percent / 100) * circumference;
        circle.style.strokeDashoffset = offset;
        document.getElementById("progress-value").textContent = Math.round(percent) + "%";
    }

    function showContext(error) {
        const viewer = document.getElementById("context-viewer");
        viewer.innerHTML = "";

        const category     = error.category_name  || "Other";
        const severity     = error.severity_name   || "ERROR";
        const message      = error.message         || "Unknown error";
        const line         = error.line            || 0;
        const col          = error.column          || 0;
        const tagName      = error.tag_name        || "";
        const refTag       = error.reference_tag   || "";
        const refLine      = error.reference_line  || 0;

        // ── 1. Error Banner ──────────────────────────────────────────────────
        const severityLower = severity.toLowerCase();
        let bannerClass = "ctx-banner ctx-banner--error";
        if (severityLower === "fatal")   bannerClass = "ctx-banner ctx-banner--fatal";
        if (severityLower === "warning") bannerClass = "ctx-banner ctx-banner--warning";

        const banner = document.createElement("div");
        banner.className = bannerClass;
        banner.innerHTML = `
            <div class="ctx-banner-header">
                <span class="ctx-badge ctx-badge--${severityLower}">${severity}</span>
                <span class="ctx-category">${category}</span>
                <span class="ctx-location">Line ${line.toLocaleString()}, Col ${col.toLocaleString()}</span>
            </div>
            <div class="ctx-message">${escapeHtml(message)}</div>
        `;
        viewer.appendChild(banner);

        // ── 2. Tag Reference Callout ─────────────────────────────────────────
        // Show whenever we have a tag name — explains what's wrong and where the partner is
        if (tagName) {
            const refBox = document.createElement("div");
            refBox.className = "ctx-tag-ref";

            let refHtml = `
                <div class="ctx-tag-ref-row">
                    <span class="ctx-tag-ref-label">Problematic field / tag</span>
                    <code class="ctx-tag-pill ctx-tag-pill--bad">&lt;${escapeHtml(tagName)}&gt;</code>
                </div>`;

            if (refTag && refLine > 0) {
                // Tag mismatch — we know the partner
                refHtml += `
                <div class="ctx-tag-ref-row">
                    <span class="ctx-tag-ref-label">Opening tag found at</span>
                    <code class="ctx-tag-pill ctx-tag-pill--ref">&lt;${escapeHtml(refTag)}&gt;</code>
                    <span class="ctx-tag-ref-line">line ${refLine.toLocaleString()}</span>
                </div>
                <div class="ctx-tag-ref-hint">
                    The closing tag <code>&lt;/${escapeHtml(tagName)}&gt;</code> does not match
                    the opening tag <code>&lt;${escapeHtml(refTag)}&gt;</code> opened on line ${refLine.toLocaleString()}.
                    These must be the same name.
                </div>`;
            } else if (refTag) {
                refHtml += `
                <div class="ctx-tag-ref-row">
                    <span class="ctx-tag-ref-label">Paired tag</span>
                    <code class="ctx-tag-pill ctx-tag-pill--ref">&lt;${escapeHtml(refTag)}&gt;</code>
                </div>`;
            } else {
                // Unclosed / undefined — no partner info
                refHtml += `
                <div class="ctx-tag-ref-hint">
                    No matching closing tag was found for
                    <code>&lt;${escapeHtml(tagName)}&gt;</code> in the document.
                    Verify it is properly closed with <code>&lt;/${escapeHtml(tagName)}&gt;</code>.
                </div>`;
            }

            refBox.innerHTML = refHtml;
            viewer.appendChild(refBox);
        }

        // ── 3. Source Code Context ───────────────────────────────────────────
        if (!error.context_lines || error.context_lines.length === 0) {
            const noCtx = document.createElement("div");
            noCtx.className = "ctx-no-context";
            noCtx.textContent = `No source lines available for line ${line.toLocaleString()}.`;
            viewer.appendChild(noCtx);
            return;
        }

        const codeHeader = document.createElement("div");
        codeHeader.className = "ctx-code-header";
        codeHeader.textContent = "Source Context";
        viewer.appendChild(codeHeader);

        const codeBlock = document.createElement("div");
        codeBlock.className = "ctx-code-block";

        const maxLineno = Math.max(...error.context_lines.map(cl => cl.line_number));
        const pad = String(maxLineno).length;

        error.context_lines.forEach((cl) => {
            const lineDiv = document.createElement("div");
            lineDiv.className = "context-row" + (cl.is_error_line ? " error-line" : "");

            const lineNo = document.createElement("span");
            lineNo.className = "line-no";
            lineNo.textContent = String(cl.line_number).padStart(pad, " ");

            const textSpan = document.createElement("span");
            textSpan.className = "ctx-code-text";
            // Highlight the problematic tag name inside the source line
            if (tagName) {
                textSpan.innerHTML = highlightTagInLine(cl.text, tagName);
            } else {
                textSpan.textContent = cl.text;
            }

            lineDiv.appendChild(lineNo);
            lineDiv.appendChild(textSpan);
            codeBlock.appendChild(lineDiv);

            // ── Column pointer arrow under the error character ───────────────
            if (cl.is_error_line && col > 0) {
                const pointerDiv = document.createElement("div");
                pointerDiv.className = "ctx-col-pointer";
                const gutterWidth = pad + 3; // pad + " │ "
                const spaces = "\u00A0".repeat(gutterWidth + col - 1);
                pointerDiv.innerHTML = `<span class="ctx-pointer-spaces">${spaces}</span><span class="ctx-pointer-arrow">▲ col ${col}</span>`;
                codeBlock.appendChild(pointerDiv);
            }
        });

        viewer.appendChild(codeBlock);
    }

    /** Escape HTML special chars, then wrap every occurrence of <tagName> or </tagName> with a highlight mark. */
    function highlightTagInLine(rawText, tagName) {
        const escaped   = escapeHtml(rawText);
        const tagEsc    = escapeHtml(tagName);
        // Escape all regular expression special characters to avoid SyntaxError crashes
        const safeTag   = tagEsc.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        // Match opening <tag>, closing </tag>, and self-closing <tag ... />
        // Works on already-escaped text so we match &lt; and &gt;
        const re = new RegExp(
            `(&lt;/?)(${safeTag})((?:\\s[^&]*?)?)(&gt;)`,
            "g"
        );
        return escaped.replace(
            re,
            `$1<mark class="ctx-tag-mark">$2</mark>$3$4`
        );
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }




    function renderRecentFiles(list) {
        const recentBox = document.getElementById("recent-list");
        recentBox.innerHTML = "";

        if (!list || list.length === 0) {
            recentBox.innerHTML = `<span style="font-size:0.8rem; color:var(--text-muted); text-align:center;">No recent files</span>`;
            return;
        }

        list.forEach((filePath) => {
            const item = document.createElement("div");
            item.className = "recent-item";
            
            // Extract filename
            const parts = filePath.split(/[\\/]/);
            const name = parts[parts.length - 1];

            item.innerHTML = `
                ${docIcon}
                <span title="${filePath}">${name}</span>
            `;

            item.addEventListener("click", () => {
                if (isValidationRunning) return;
                selectFile(filePath);
            });

            recentBox.appendChild(item);
        });
    }

    // Select target
    function selectFile(path) {
        selectedFileOrUrl = path;
        
        // Remove dragover highlights
        document.getElementById("dropzone").classList.remove("dragover");
        
        // Reset metrics
        document.getElementById("meta-name").textContent = path.split(/[\\/]/).pop();
        document.getElementById("meta-size").textContent = "—";
        document.getElementById("meta-encoding").textContent = "—";
        document.getElementById("meta-root").textContent = "—";
        document.getElementById("meta-duration").textContent = "—";
        
        resetDashboard();

        document.getElementById("btn-validate").disabled = false;
    }

    function resetDashboard() {
        setProgress(0);
        document.getElementById("validation-status").textContent = "Ready";
        document.getElementById("validation-status").style.color = "var(--text-muted)";
        
        document.getElementById("stat-bytes").textContent = "—";
        document.getElementById("stat-line").textContent = "—";
        document.getElementById("stat-speed").textContent = "—";
        document.getElementById("stat-eta").textContent = "—";
        document.getElementById("stat-errors").textContent = "0";
        document.getElementById("stat-errors").style.color = "var(--success)";

        document.getElementById("errors-tbody").innerHTML = `
            <tr>
                <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 40px 0;">
                    No errors. Run validation.
                </td>
            </tr>
        `;
        document.getElementById("context-viewer").innerHTML =
            `<div style="color: var(--text-muted); font-style: italic; font-size: 0.85rem; padding: 20px 4px;">` +
            `← Click any error row to see a full explanation, fix suggestions, and source context.</div>`;
        validationErrors = [];
    }

    function setControlsState(running) {
        isValidationRunning = running;
        
        document.getElementById("btn-validate").style.display = running ? "none" : "block";
        document.getElementById("btn-cancel").style.display = running ? "block" : "none";
        document.getElementById("btn-browse").disabled = running;
        document.getElementById("url-input").disabled = running;
        document.getElementById("btn-fetch").disabled = running;
        document.getElementById("btn-export").disabled = running;
        document.getElementById("setting-context").disabled = running;
    }

    // ── Event Handlers ─────────────────────────────────────────────────────

    // Drag & Drop
    const dropzone = document.getElementById("dropzone");
    
    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("dragover");
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");

        if (isValidationRunning) return;

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            // Pass file path to Python via slot
            // Since HTML drag and drop doesn't expose absolute local paths for security reasons,
            // we let the PySide6 container handle dropEvents at the main window level.
            // But we keep this listener in case we want to notify or style.
        }
    });

    dropzone.addEventListener("click", () => {
        if (isValidationRunning) return;
        if (pyBridge) {
            pyBridge.open_file_dialog((path) => {
                if (path) selectFile(path);
            });
        }
    });

    document.getElementById("btn-browse").addEventListener("click", () => {
        if (pyBridge) {
            pyBridge.open_file_dialog((path) => {
                if (path) selectFile(path);
            });
        }
    });

    document.getElementById("btn-fetch").addEventListener("click", () => {
        const urlVal = document.getElementById("url-input").value.trim();
        if (urlVal) {
            selectFile(urlVal);
        }
    });

    document.getElementById("btn-validate").addEventListener("click", () => {
        if (!selectedFileOrUrl || isValidationRunning) return;
        
        resetDashboard();
        setControlsState(true);

        const ctxLines = parseInt(document.getElementById("setting-context").value) || 10;
        
        if (pyBridge) {
            pyBridge.start_validation(selectedFileOrUrl, ctxLines);
        }
    });

    document.getElementById("btn-cancel").addEventListener("click", () => {
        if (pyBridge) {
            pyBridge.cancel_validation();
        }
    });

    document.getElementById("btn-export").addEventListener("click", () => {
        if (pyBridge) {
            pyBridge.show_export_dialog();
        }
    });

    document.getElementById("btn-clear-recent").addEventListener("click", () => {
        if (pyBridge) {
            pyBridge.clear_recent_files();
            renderRecentFiles([]);
        }
    });


    // Save context setting on change
    document.getElementById("setting-context").addEventListener("change", (e) => {
        const val = parseInt(e.target.value) || 10;
        if (pyBridge) {
            pyBridge.save_setting("context_line_count", val);
        }
    });

    // Expose file selection function globally for drag & drop integration in Python MainWindow
    window.selectFile = selectFile;
});
