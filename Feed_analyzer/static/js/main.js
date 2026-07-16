// Global Dashboard State
let flatFields = [];
let activeFilters = [];
let activeGroupBy = [];
let resultsDataTable = null;
let searchDataTable = null;
let currentChart = null;
let currentFieldPath = "";
let allValuesDataTable = null;

// Initialize on load
document.addEventListener("DOMContentLoaded", () => {
    // 1. Process flat fields from schema tree
    flatFields = extractPaths(rawSchemaTree);
    
    // 2. Render Structure tree
    const treeContainer = document.getElementById("treeContainer");
    if (treeContainer) {
        renderSchemaTree(rawSchemaTree, treeContainer);
    }
    
    // 3. Populate select lists in builders
    populateSelectors();
    
    // 4. Initialize first filter row by default
    addFilterRow();
});

// Extract paths recursively from hierarchical tree object
function extractPaths(node, currentPath = "") {
    let paths = [];
    for (const key in node) {
        const newPath = currentPath ? `${currentPath}/${key}` : key;
        const isLeaf = Object.keys(node[key]).length === 0;
        paths.push({ path: newPath, isLeaf: isLeaf });
        
        // Traverse deeper
        const subPaths = extractPaths(node[key], newPath);
        paths = paths.concat(subPaths);
    }
    return paths;
}

// Render Collapsible Schema tree
function renderSchemaTree(tree, container) {
    container.innerHTML = "";
    
    const rootUl = document.createElement("div");
    rootUl.className = "tree-root";
    
    for (const key in tree) {
        renderTreeNode(tree[key], key, rootUl);
    }
    container.appendChild(rootUl);
}

function renderTreeNode(node, name, parentEl) {
    const hasChildren = Object.keys(node).length > 0;
    const nodeEl = document.createElement("div");
    nodeEl.className = "tree-node";
    if (hasChildren) {
        nodeEl.classList.add("tree-collapsed");
    }
    
    const labelEl = document.createElement("span");
    labelEl.className = "tree-node-label";
    
    // Icon configuration
    const icon = hasChildren 
        ? '<i class="bi bi-folder-fill text-warning me-2"></i>' 
        : '<i class="bi bi-tag text-secondary me-2"></i>';
    labelEl.innerHTML = icon + name;
    
    nodeEl.appendChild(labelEl);
    
    if (hasChildren) {
        const childrenEl = document.createElement("div");
        childrenEl.className = "tree-children";
        
        // Toggle folder state on label click
        labelEl.addEventListener("click", (e) => {
            e.stopPropagation();
            nodeEl.classList.toggle("tree-collapsed");
            const folderIcon = labelEl.querySelector("i");
            if (nodeEl.classList.contains("tree-collapsed")) {
                folderIcon.className = "bi bi-folder-fill text-warning me-2";
            } else {
                folderIcon.className = "bi bi-folder-open-fill text-warning me-2";
            }
        });
        
        for (const childKey in node) {
            renderTreeNode(node[childKey], childKey, childrenEl);
        }
        nodeEl.appendChild(childrenEl);
    } else {
        // Leaf Node click explores field stats
        labelEl.addEventListener("click", (e) => {
            e.stopPropagation();
            const fullPath = getPathFromElement(labelEl);
            exploreField(fullPath);
        });
    }
    parentEl.appendChild(nodeEl);
}

// Climb DOM to construct path string, e.g. Location/City
function getPathFromElement(element) {
    const segments = [];
    let current = element;
    
    while (current) {
        const node = current.closest(".tree-node");
        if (!node) break;
        
        // Get the label text (excluding icons)
        const label = node.querySelector(".tree-node-label").innerText.trim();
        segments.unshift(label);
        
        // Go to parent node
        const parentNode = node.parentElement.closest(".tree-node");
        current = parentNode ? parentNode.querySelector(".tree-node-label") : null;
    }
    return segments.join("/");
}

// Field Statistics Viewer
function exploreField(fieldPath) {
    currentFieldPath = fieldPath; // Store globally
    const statsPanel = document.getElementById("fieldStatsPanel");
    statsPanel.classList.remove("d-none");
    
    document.getElementById("statFieldPath").innerText = fieldPath;
    
    // Fetch stats
    fetch(`/api/field_stats/${taskId}?field=${encodeURIComponent(fieldPath)}`)
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                alert(data.error);
                return;
            }
            
            // Populate stats text
            document.getElementById("statCompletion").innerText = data.completion_rate + "%";
            document.getElementById("statPresent").innerText = data.present_count;
            document.getElementById("statMissing").innerText = data.missing_count;
            document.getElementById("statUnique").innerText = data.unique_count;
            document.getElementById("statAvgLen").innerText = data.avg_length + " ch";
            document.getElementById("statMaxLen").innerText = data.max_length + " ch";
            
            // Populate common values
            const topList = document.getElementById("statTopValuesList");
            topList.innerHTML = "";
            data.top_values.forEach(item => {
                const li = document.createElement("li");
                li.className = "list-group-item d-flex justify-content-between align-items-center text-white bg-transparent border-secondary border-opacity-25";
                li.innerHTML = `<span class="text-truncate" style="max-width:80%;" title="${item.value}">${item.value}</span> <span class="badge bg-indigo rounded-pill">${item.count}</span>`;
                topList.appendChild(li);
            });
            
            const bottomList = document.getElementById("statBottomValuesList");
            bottomList.innerHTML = "";
            data.bottom_values.forEach(item => {
                const li = document.createElement("li");
                li.className = "list-group-item d-flex justify-content-between align-items-center text-white bg-transparent border-secondary border-opacity-25";
                li.innerHTML = `<span class="text-truncate" style="max-width:80%;" title="${item.value}">${item.value}</span> <span class="badge bg-secondary rounded-pill">${item.count}</span>`;
                bottomList.appendChild(li);
            });
            
            // Scroll stats panel into view smoothly
            statsPanel.scrollIntoView({ behavior: 'smooth' });
        });
}

function closeFieldExplorer() {
    document.getElementById("fieldStatsPanel").classList.add("d-none");
}

// Select lists populate
function populateSelectors() {
    const listGroupField = document.getElementById("selectGroupByField");
    const searchField = document.getElementById("searchField");
    const dupSelectField = document.getElementById("duplicateSelectField");
    
    // Sort leaf paths for cleanliness
    const leafFields = flatFields.filter(f => f.isLeaf).map(f => f.path).sort();
    
    leafFields.forEach(path => {
        const opt1 = new Option(path, path);
        if (listGroupField) listGroupField.add(opt1);
        
        const opt2 = new Option(path, path);
        if (searchField) searchField.add(opt2);
        
        const opt3 = new Option(path, path);
        if (dupSelectField) dupSelectField.add(opt3);
    });
}

// Visual Filter rows builder
function addFilterRow() {
    const container = document.getElementById("filterList");
    const rowId = `filter_row_${Date.now()}`;
    
    const row = document.createElement("div");
    row.className = "row g-2 align-items-center filter-row";
    row.id = rowId;
    
    // Fields dropdown options
    let fieldsHtml = flatFields.map(f => `<option value="${f.path}">${f.path}</option>`).join("");
    
    row.innerHTML = `
        <div class="col-md-4">
            <select class="form-select form-select-sm filter-field-select">
                <option value="">-- Select Field --</option>
                ${fieldsHtml}
            </select>
        </div>
        <div class="col-md-3">
            <select class="form-select form-select-sm filter-operator-select" onchange="toggleFilterValueInput('${rowId}')">
                <option value="Equals">Equals</option>
                <option value="Not Equals">Not Equals</option>
                <option value="Contains">Contains</option>
                <option value="Starts With">Starts With</option>
                <option value="Ends With">Ends With</option>
                <option value="Greater Than">Greater Than</option>
                <option value="Less Than">Less Than</option>
                <option value="Exists">Exists</option>
                <option value="Missing">Missing</option>
                <option value="In List">In List (comma separated)</option>
                <option value="Not In List">Not In List</option>
                <option value="Regex">Regex Match</option>
            </select>
        </div>
        <div class="col-md-4">
            <input type="text" class="form-control form-control-sm filter-value-input" placeholder="Enter matching value...">
        </div>
        <div class="col-md-1 text-center">
            <button type="button" class="btn btn-sm btn-outline-danger border-0" onclick="removeFilterRow('${rowId}')">
                <i class="bi bi-x-lg"></i>
            </button>
        </div>
    `;
    
    container.appendChild(row);
}

function removeFilterRow(rowId) {
    const row = document.getElementById(rowId);
    if (row) row.remove();
}

function clearAllFilters() {
    document.getElementById("filterList").innerHTML = "";
    addFilterRow();
}

function toggleFilterValueInput(rowId) {
    const row = document.getElementById(rowId);
    const op = row.querySelector(".filter-operator-select").value;
    const input = row.querySelector(".filter-value-input");
    
    if (op === "Exists" || op === "Missing") {
        input.value = "";
        input.setAttribute("disabled", "true");
    } else {
        input.removeAttribute("disabled");
    }
}

// Group By Visual builder
function addGroupByLevel() {
    const selector = document.getElementById("selectGroupByField");
    const field = selector.value;
    if (!field || activeGroupBy.includes(field)) return;
    
    activeGroupBy.push(field);
    selector.value = ""; // Reset dropdown
    
    renderGroupByChips();
}

function removeGroupByLevel(index) {
    activeGroupBy.splice(index, 1);
    renderGroupByChips();
}

function renderGroupByChips() {
    const container = document.getElementById("groupByList");
    container.innerHTML = "";
    
    activeGroupBy.forEach((field, idx) => {
        const chip = document.createElement("span");
        chip.className = "badge badge-custom d-inline-flex align-items-center py-2 px-3 fs-6";
        chip.innerHTML = `
            ${idx + 1}. ${field}
            <i class="bi bi-x-circle-fill ms-2 cursor-pointer text-danger" onclick="removeGroupByLevel(${idx})"></i>
        `;
        container.appendChild(chip);
    });
}

// Extract visual builder arrays
function compileBuilderData() {
    const filters = [];
    const rows = document.querySelectorAll(".filter-row");
    
    rows.forEach(row => {
        const field = row.querySelector(".filter-field-select").value;
        const operator = row.querySelector(".filter-operator-select").value;
        const value = row.querySelector(".filter-value-input").value;
        
        if (field && operator) {
            filters.push({ field, operator, value });
        }
    });
    
    return {
        filters: filters,
        group_by: activeGroupBy
    };
}

// Execute Visual Query
function runQueryAnalysis() {
    const payload = compileBuilderData();
    
    document.getElementById("queryDefaultPlaceholder").classList.add("d-none");
    const runBtn = document.getElementById("runQueryBtn");
    runBtn.setAttribute("disabled", "true");
    runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Executing...';
    
    fetch(`/api/query/${taskId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        runBtn.removeAttribute("disabled");
        runBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Run Analysis';
        
        if (data.error) {
            alert("Query failed: " + data.error);
            return;
        }
        
        // Toggle cards depending on type
        const chartCard = document.getElementById("chartCard");
        const tableCard = document.getElementById("resultsTableCard");
        const exportButtons = document.getElementById("queryExportButtons");
        
        if (data.type === "grouped") {
            // Grouped results -> Show Chart & Grouped details
            chartCard.classList.remove("d-none");
            tableCard.classList.remove("d-none");
            exportButtons.classList.remove("d-none");
            
            renderChart(data.chart_data);
            renderGroupedTable(data.data, data.group_by);
        } else {
            // Record results -> Hide Chart, Show grid
            chartCard.classList.add("d-none");
            tableCard.classList.remove("d-none");
            exportButtons.classList.remove("d-none");
            
            renderRecordsTable(data.records, data.total_matches);
        }
    })
    .catch(() => {
        runBtn.removeAttribute("disabled");
        runBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Run Analysis';
        alert("Server communication error.");
    });
}

// Render Chart.js
function renderChart(chartData) {
    const ctx = document.getElementById("analyticsChart").getContext("2d");
    
    if (currentChart) {
        currentChart.destroy();
    }
    
    currentChart = new Chart(ctx, {
        type: activeGroupBy.length > 1 ? "bar" : "pie", // Bar for nested, Pie for single
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "right",
                    labels: { color: "#e2e8f0" }
                }
            },
            scales: activeGroupBy.length > 1 ? {
                y: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#e2e8f0" } },
                x: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#e2e8f0" } }
            } : {}
        }
    });
}

// Render table for group counts
function renderGroupedTable(groupedData, groupColumns) {
    // Destroy existing table
    if ($.fn.DataTable.isDataTable('#resultsGridTable')) {
        $('#resultsGridTable').DataTable().destroy();
        $('#resultsGridTable').empty();
    }
    
    const headerTr = document.getElementById("resultsTableHeader");
    headerTr.innerHTML = "";
    
    // Headers
    groupColumns.forEach(col => {
        const th = document.createElement("th");
        th.innerText = col;
        headerTr.appendChild(th);
    });
    const countTh = document.createElement("th");
    countTh.innerText = "Count";
    headerTr.appendChild(countTh);
    
    // Rows
    const tbody = document.getElementById("resultsTableBody");
    tbody.innerHTML = "";
    
    groupedData.forEach(row => {
        const tr = document.createElement("tr");
        row.keys.forEach(val => {
            const td = document.createElement("td");
            td.innerText = val;
            tr.appendChild(td);
        });
        const cntTd = document.createElement("td");
        cntTd.innerHTML = `<span class="badge bg-indigo rounded-pill px-3">${row.count}</span>`;
        tr.appendChild(cntTd);
        tbody.appendChild(tr);
    });
    
    document.getElementById("resultsMatchesCount").innerText = groupedData.length;
    document.getElementById("resultsLimitWarning").innerText = "Group-by aggregate count.";
    
    // Initialize DataTable for paging grouped entries
    resultsDataTable = $('#resultsGridTable').DataTable({
        pageLength: 10,
        lengthMenu: [5, 10, 25, 50],
        ordering: true,
        order: [[groupColumns.length, "desc"]], // Sort by count column descending
        language: { search: "_INPUT_", searchPlaceholder: "Search summary..." }
    });
}

// Render dynamic results table for records
function renderRecordsTable(records, totalMatches) {
    if ($.fn.DataTable.isDataTable('#resultsGridTable')) {
        $('#resultsGridTable').DataTable().destroy();
        $('#resultsGridTable').empty();
    }
    
    const headerTr = document.getElementById("resultsTableHeader");
    headerTr.innerHTML = "";
    
    // Dynamic columns selection
    // Let's filter out metadata columns starting with '_'
    const sampleRecord = records[0] || {};
    const dataKeys = Object.keys(sampleRecord).filter(k => !k.startsWith('_'));
    
    // Headers
    const actionTh = document.createElement("th");
    actionTh.innerText = "Inspect";
    headerTr.appendChild(actionTh);
    
    dataKeys.slice(0, 8).forEach(key => { // Show first 8 columns to avoid extreme horizontal stretching
        const th = document.createElement("th");
        th.innerText = key;
        headerTr.appendChild(th);
    });
    
    // Rows
    const tbody = document.getElementById("resultsTableBody");
    tbody.innerHTML = "";
    
    records.forEach(rec => {
        const tr = document.createElement("tr");
        
        // Inspect action
        const actionTd = document.createElement("td");
        actionTd.innerHTML = `<button onclick="inspectRecord(${rec._row_id}, ${escapeHtml(JSON.stringify(rec))})" class="btn btn-sm btn-outline-primary py-1 px-2"><i class="bi bi-eye-fill"></i></button>`;
        tr.appendChild(actionTd);
        
        // Field values
        dataKeys.slice(0, 8).forEach(key => {
            const td = document.createElement("td");
            let val = rec[key];
            if (val === null || val === undefined) {
                td.innerHTML = '<span class="text-muted small">[Missing]</span>';
            } else if (typeof val === 'object') {
                td.innerText = JSON.stringify(val);
                td.title = JSON.stringify(val);
            } else {
                td.innerText = val;
                td.title = val;
            }
            td.className = "text-truncate";
            td.style.maxWidth = "160px";
            tr.appendChild(td);
        });
        
        tbody.appendChild(tr);
    });
    
    document.getElementById("resultsMatchesCount").innerText = totalMatches;
    document.getElementById("resultsLimitWarning").innerText = `Showing first ${records.length} records.`;
    
    resultsDataTable = $('#resultsGridTable').DataTable({
        pageLength: 10,
        lengthMenu: [10, 25, 50, 100],
        ordering: false, // Turn off ordering since we truncate at 1000 items
        language: { search: "_INPUT_", searchPlaceholder: "Filter preview rows..." }
    });
}

// HTML Escape helper
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const s = String(str);
    return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Launch record inspector drawer
function inspectRecord(rowId, recordObj) {
    const drawerEl = document.getElementById("jobInspectorDrawer");
    const drawer = new bootstrap.Offcanvas(drawerEl);
    
    document.getElementById("inspectRecordId").innerText = `Record ID: ${rowId}`;
    
    // Populate raw code tab
    const rawContent = recordObj._raw_content;
    const isXml = rawContent.trim().startsWith("<");
    const codeEl = document.getElementById("inspectRawContentCode");
    codeEl.innerText = rawContent;
    codeEl.className = isXml ? "language-xml" : "language-json";
    
    // Populate Fields table
    const tableBody = document.getElementById("inspectFieldsTableBody");
    tableBody.innerHTML = "";
    
    Object.keys(recordObj).forEach(key => {
        if (key.startsWith("_")) return; // skip row id and raw XML
        
        const tr = document.createElement("tr");
        const val = recordObj[key];
        
        tr.innerHTML = `
            <td class="fw-bold text-secondary" style="width: 35%;">${key}</td>
            <td class="text-white">${val !== null ? escapeHtml(String(val)) : '<span class="text-muted small">[Missing]</span>'}</td>
        `;
        tableBody.appendChild(tr);
    });
    
    drawer.show();
}

// Exporter fetch trigger
function exportData(format) {
    const payload = compileBuilderData();
    payload.export_type = "query";
    
    fetch(`/export/${taskId}/${format}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    })
    .then(res => res.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `feed_query_export.${format}`;
        a.click();
    })
    .catch(() => alert("Export failed."));
}

// Search Panel execution
function runSearchAnalysis() {
    const field = document.getElementById("searchField").value;
    const matchType = document.getElementById("searchMatchType").value;
    const queryText = document.getElementById("searchTerm").value.trim();
    
    if (!queryText) {
        alert("Please enter a search term.");
        return;
    }
    
    document.getElementById("searchPlaceholder").classList.add("d-none");
    
    const payload = {
        search_field: field,
        search_type: matchType,
        search_term: queryText
    };
    
    fetch(`/api/query/${taskId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            return;
        }
        
        const card = document.getElementById("searchTableCard");
        card.classList.remove("d-none");
        
        renderSearchGrid(data.records, data.total_matches);
    });
}

function renderSearchGrid(records, totalMatches) {
    if ($.fn.DataTable.isDataTable('#searchGridTable')) {
        $('#searchGridTable').DataTable().destroy();
        $('#searchGridTable').empty();
    }
    
    const headerTr = document.getElementById("searchTableHeader");
    headerTr.innerHTML = "";
    
    const sampleRecord = records[0] || {};
    const dataKeys = Object.keys(sampleRecord).filter(k => !k.startsWith('_'));
    
    // Action col
    const actionTh = document.createElement("th");
    actionTh.innerText = "Inspect";
    headerTr.appendChild(actionTh);
    
    dataKeys.slice(0, 8).forEach(key => {
        const th = document.createElement("th");
        th.innerText = key;
        headerTr.appendChild(th);
    });
    
    const tbody = document.getElementById("searchTableBody");
    tbody.innerHTML = "";
    
    records.forEach(rec => {
        const tr = document.createElement("tr");
        
        const actionTd = document.createElement("td");
        actionTd.innerHTML = `<button onclick="inspectRecord(${rec._row_id}, ${escapeHtml(JSON.stringify(rec))})" class="btn btn-sm btn-outline-primary py-1 px-2"><i class="bi bi-eye-fill"></i></button>`;
        tr.appendChild(actionTd);
        
        dataKeys.slice(0, 8).forEach(key => {
            const td = document.createElement("td");
            let val = rec[key];
            td.innerText = val !== null ? val : '';
            td.className = "text-truncate";
            td.style.maxWidth = "160px";
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    
    document.getElementById("searchMatchesCount").innerText = totalMatches;
    
    searchDataTable = $('#searchGridTable').DataTable({
        pageLength: 10,
        lengthMenu: [10, 25, 50],
        ordering: false,
        language: { search: "_INPUT_", searchPlaceholder: "Filter search preview rows..." }
    });
}

// Duplicate values panel execution
function runDuplicateDetection() {
    const field = document.getElementById("duplicateSelectField").value;
    if (!field) {
        alert("Please select a field first.");
        return;
    }
    
    document.getElementById("duplicatesPlaceholder").classList.add("d-none");
    
    fetch(`/api/duplicates/${taskId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field })
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            return;
        }
        
        document.getElementById("duplicateTableCard").classList.remove("d-none");
        
        // Destroy existing
        if ($.fn.DataTable.isDataTable('#duplicatesGridTable')) {
            $('#duplicatesGridTable').DataTable().destroy();
        }
        
        const tbody = document.getElementById("duplicatesTableBody");
        tbody.innerHTML = "";
        
        data.duplicates.forEach(row => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td style="font-weight: 500; color: #a5b4fc;">${row.value}</td>
                <td><span class="badge bg-danger rounded-pill px-3">${row.count}</span></td>
            `;
            tbody.appendChild(tr);
        });
        
        $('#duplicatesGridTable').DataTable({
            pageLength: 10,
            ordering: true,
            order: [[1, "desc"]],
            language: { search: "_INPUT_", searchPlaceholder: "Search duplicates list..." }
        });
    });
}

function exportDuplicates() {
    const field = document.getElementById("duplicateSelectField").value;
    if (!field) return;
    
    fetch(`/export/${taskId}/csv`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ export_type: "duplicates", field: field })
    })
    .then(res => res.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `duplicates_${field.replace(/\//g, '_')}.csv`;
        a.click();
    });
}

// Completeness reports panel execution
function runCompletenessScan() {
    document.getElementById("completenessPlaceholder").classList.add("d-none");
    
    fetch(`/api/missing/${taskId}`)
    .then(res => res.json())
    .then(data => {
        document.getElementById("completenessTableCard").classList.remove("d-none");
        
        if ($.fn.DataTable.isDataTable('#completenessGridTable')) {
            $('#completenessGridTable').DataTable().destroy();
        }
        
        const tbody = document.getElementById("completenessTableBody");
        tbody.innerHTML = "";
        
        data.report.forEach(row => {
            const tr = document.createElement("tr");
            
            // Completion rate color alert
            let badgeClass = "bg-success";
            if (row.completion_rate < 50.0) badgeClass = "bg-danger";
            else if (row.completion_rate < 85.0) badgeClass = "bg-warning";
            
            tr.innerHTML = `
                <td style="font-weight: 600; color: #38bdf8;">${row.field_path}</td>
                <td><span class="badge ${badgeClass} rounded-pill px-3">${row.completion_rate}%</span></td>
                <td>${row.present_count}</td>
                <td>${row.missing_count}</td>
            `;
            tbody.appendChild(tr);
        });
        
        $('#completenessGridTable').DataTable({
            pageLength: 25,
            ordering: true,
            order: [[1, "asc"]], // Sort ascending (worst completion first)
            language: { search: "_INPUT_", searchPlaceholder: "Search fields..." }
        });
    });
}

function exportCompletenessReport() {
    fetch(`/export/${taskId}/csv`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ export_type: "stats" })
    })
    .then(res => res.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `completeness_report.csv`;
        a.click();
    });
}

function exportFullHTMLReport() {
    fetch(`/export/${taskId}/html`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ export_type: "stats" })
    })
    .then(res => res.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `analytical_summary_report.html`;
        a.click();
    });
}

function showAllFieldValues() {
    if (!currentFieldPath) return;
    
    // Set modal label
    document.getElementById("allValuesModalLabel").innerHTML = `<i class="bi bi-list-ul me-2 text-primary"></i>All Values for: <span class="text-info">${currentFieldPath}</span>`;
    
    // Destroy DataTable safely using the standard jQuery DataTables API check
    if ($.fn.DataTable.isDataTable('#allValuesGridTable')) {
        $('#allValuesGridTable').DataTable().destroy();
    }
    allValuesDataTable = null;
    
    // Reset tbody
    const tbody = document.getElementById("allValuesTableBody");
    tbody.innerHTML = `<tr><td colspan="2" class="text-center"><span class="spinner-border spinner-border-sm me-2"></span>Loading...</td></tr>`;
    
    // Open Modal
    const modalEl = document.getElementById("allValuesModal");
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
    
    // Fetch values
    fetch(`/api/field_values/${taskId}?field=${encodeURIComponent(currentFieldPath)}`)
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                alert("Failed to load: " + data.error);
                return;
            }
            
            tbody.innerHTML = "";
            
            data.values.forEach(row => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td class="text-white text-truncate" style="max-width: 450px;" title="${row.value}">${escapeHtml(row.value)}</td>
                    <td><span class="badge bg-indigo rounded-pill px-3">${row.count}</span></td>
                `;
                tbody.appendChild(tr);
            });
            
            // Initialize DataTable
            allValuesDataTable = $('#allValuesGridTable').DataTable({
                pageLength: 10,
                lengthMenu: [5, 10, 25, 50],
                ordering: true,
                order: [[1, "desc"]], // Sort by count column descending
                language: { search: "_INPUT_", searchPlaceholder: "Search values..." }
            });
        })
        .catch(err => {
            tbody.innerHTML = `<tr><td colspan="2" class="text-center text-danger">Failed to communicate with server.</td></tr>`;
        });
}

function downloadAllFieldValues() {
    if (!currentFieldPath) return;
    window.location.href = `/export/${taskId}/field_values?field=${encodeURIComponent(currentFieldPath)}`;
}
