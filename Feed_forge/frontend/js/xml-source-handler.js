/**
 * XML File & URL Source Handler
 */

import { initAgGrid } from './excel-handler.js';

export function initXmlSourceStep(state, onUploadSuccess) {
    const tabExcel = document.getElementById('excel-tab');
    const tabXmlFile = document.getElementById('xml-file-tab');
    const tabXmlUrl = document.getElementById('xml-url-tab');
    
    const dropZone = document.getElementById('xml-drop-zone');
    const fileInput = document.getElementById('xml-file-input');
    const browseBtn = document.getElementById('btn-browse-xml-file');
    const fetchUrlBtn = document.getElementById('btn-fetch-url');
    const authTypeSelect = document.getElementById('url-auth-type');
    const applyXpathBtn = document.getElementById('btn-apply-xpath-override');
    const xpathSwitch = document.getElementById('xpath-override-switch');
    const xpathCollapseEl = document.getElementById('xpath-override-collapse');
    const xpathInput = document.getElementById('xpath-override-input');
    
    const worksheetCard = document.getElementById('worksheet-selection-card');
    const xpathControl = document.getElementById('xml-xpath-control');
    const previewGridCard = document.getElementById('excel-preview-card');
    const rowCountSpan = document.getElementById('preview-row-count');
    
    // Set default source type
    state.sourceType = 'excel';
    state.sourceConfig = state.sourceConfig || {};

    // 1. Source Type Tabs click listeners
    tabExcel.addEventListener('click', () => {
        state.sourceType = 'excel';
        worksheetCard.classList.remove('d-none');
        xpathControl.classList.add('d-none');
        // Hide preview card unless loaded
        if (!state.filename) {
            previewGridCard.classList.add('d-none');
        } else {
            previewGridCard.classList.remove('d-none');
            // Re-trigger excel preview grid
            if (state.selectedSheet) {
                const tabsContainer = document.getElementById('worksheet-tabs-container');
                if (tabsContainer.children.length === 0) {
                    import('./excel-handler.js').then(m => m.renderWorksheetTabs(state));
                }
            }
        }
    });

    tabXmlFile.addEventListener('click', () => {
        state.sourceType = 'xml_file';
        worksheetCard.classList.add('d-none');
        xpathControl.classList.remove('d-none');
        previewGridCard.classList.add('d-none');
        if (state.filename && state.filename.endsWith('.xml')) {
            loadXmlPreview(state, onUploadSuccess);
        }
    });

    tabXmlUrl.addEventListener('click', () => {
        state.sourceType = 'xml_url';
        worksheetCard.classList.add('d-none');
        xpathControl.classList.remove('d-none');
        previewGridCard.classList.add('d-none');
        if (state.sourceConfig && state.sourceConfig.url) {
            loadXmlPreview(state, onUploadSuccess);
        }
    });

    // 2. Local XML Drag and Drop / Browsing
    browseBtn.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadXmlFile(e.target.files[0], state, onUploadSuccess);
        }
    });

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            uploadXmlFile(e.dataTransfer.files[0], state, onUploadSuccess);
        }
    });

    // 3. Auth UI toggle listeners
    authTypeSelect.addEventListener('change', () => {
        const val = authTypeSelect.value;
        // Hide all auth groups
        document.querySelectorAll('.auth-fields').forEach(el => el.classList.add('d-none'));
        
        if (val === 'basic') {
            document.getElementById('auth-fields-basic').classList.remove('d-none');
        } else if (val === 'bearer') {
            document.getElementById('auth-fields-bearer').classList.remove('d-none');
        } else if (val === 'apikey') {
            document.getElementById('auth-fields-apikey').classList.remove('d-none');
        }
    });

    // 4. Remote XML fetch URL button click
    fetchUrlBtn.addEventListener('click', async () => {
        const urlInput = document.getElementById('source-url-input');
        const url = urlInput.value.trim();
        if (!url) {
            alert('Please enter a valid XML URL.');
            return;
        }

        const authType = authTypeSelect.value;
        const auth_config = { auth_type: authType };
        
        if (authType === 'basic') {
            auth_config.username = document.getElementById('auth-username').value.trim();
            auth_config.password = document.getElementById('auth-password').value.trim();
        } else if (authType === 'bearer') {
            auth_config.token = document.getElementById('auth-token').value.trim();
        } else if (authType === 'apikey') {
            auth_config.header_name = document.getElementById('auth-header-name').value.trim();
            auth_config.header_value = document.getElementById('auth-header-value').value.trim();
        }

        state.sourceConfig = state.sourceConfig || {};
        state.sourceConfig.url = url;
        state.sourceConfig.auth_type = authType;
        state.sourceConfig.username = auth_config.username || '';
        state.sourceConfig.token = auth_config.token || '';
        state.sourceConfig.header_name = auth_config.header_name || '';
        state.sourceConfig.header_value = auth_config.header_value || '';
        
        // Temporarily put password/secrets in ephemeral state, don't write to state.sourceConfig permanent payload if sensitive
        const ephemeralAuth = Object.assign({}, auth_config);
        
        await fetchXmlUrlPreview(url, ephemeralAuth, state, onUploadSuccess);
    });

    // 5. XPath Override listeners
    xpathSwitch.addEventListener('change', () => {
        const collapse = bootstrap.Collapse.getOrCreateInstance(xpathCollapseEl);
        if (xpathSwitch.checked) {
            collapse.show();
        } else {
            collapse.hide();
            // Clear override input and reload with auto-detected default
            xpathInput.value = '';
            loadXmlPreview(state, onUploadSuccess);
        }
    });

    applyXpathBtn.addEventListener('click', () => {
        const xpath = xpathInput.value.trim();
        if (state.sourceConfig) {
            state.sourceConfig.record_xpath = xpath;
        }
        loadXmlPreview(state, onUploadSuccess);
    });
}

/**
 * Upload XML file to backend uploader
 */
async function uploadXmlFile(file, state, onUploadSuccess) {
    const statusIndicator = document.getElementById('status-indicator');
    if (!file.name.endsWith('.xml')) {
        alert('Invalid file format. Please upload a .xml file.');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        statusIndicator.innerHTML = `<i class="bi bi-arrow-repeat text-warning spinner me-1"></i> Uploading...`;
        
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            let errMsg = 'Upload failed';
            try {
                const errData = await response.json();
                errMsg = errData.error || errMsg;
            } catch (e) {
                errMsg = `Upload failed (Status ${response.status}): ${response.statusText}`;
            }
            throw new Error(errMsg);
        }
        
        const data = await response.json();
        console.log('XML Upload success:', data);
        
        // Update App State
        state.filename = data.filename;
        state.sourceConfig = state.sourceConfig || {};
        state.sourceConfig.record_xpath = data.detected_xpath;
        
        // Update UI
        statusIndicator.innerHTML = `<i class="bi bi-check-circle-fill text-success me-1"></i> ${file.name}`;
        statusIndicator.className = 'badge bg-success-subtle text-success border px-3 py-2 rounded-pill';
        
        // Populate XPath input
        const xpathInput = document.getElementById('xpath-override-input');
        xpathInput.value = data.detected_xpath;

        // Load preview
        await loadXmlPreview(state, onUploadSuccess);
        
    } catch (error) {
        console.error('XML Upload error:', error);
        alert(`Error uploading XML: ${error.message}`);
        statusIndicator.innerHTML = `<i class="bi bi-exclamation-circle-fill text-danger me-1"></i> Upload Failed`;
        statusIndicator.className = 'badge bg-danger-subtle text-danger border px-3 py-2 rounded-pill';
    }
}

/**
 * Fetch and load XML Url preview
 */
async function fetchXmlUrlPreview(url, auth_config, state, onUploadSuccess) {
    const statusIndicator = document.getElementById('status-indicator');
    const rowCountSpan = document.getElementById('preview-row-count');
    const previewGridCard = document.getElementById('excel-preview-card');
    const xpathInput = document.getElementById('xpath-override-input');

    try {
        statusIndicator.innerHTML = `<i class="bi bi-arrow-repeat text-warning spinner me-1"></i> Fetching URL...`;
        previewGridCard.classList.remove('d-none');
        rowCountSpan.textContent = 'Fetching and parsing remote feed...';

        const record_xpath = (state.sourceConfig && state.sourceConfig.record_xpath) || null;

        const response = await fetch('/api/source/fetch-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                record_xpath: record_xpath,
                auth_config: auth_config
            })
        });

        if (!response.ok) {
            let errMsg = 'Failed to fetch remote XML feed.';
            try {
                const errData = await response.json();
                errMsg = errData.error || errMsg;
            } catch (e) {
                errMsg = `Fetch failed (Status ${response.status}): ${response.statusText}`;
            }
            throw new Error(errMsg);
        }

        const data = await response.json();
        console.log('XML URL Fetch success:', data);

        // Store headers and preview records in state
        state.excelHeaders = data.columns.map(col => col.headerName);
        state.previewData = data.data;
        
        // Update xpath
        state.sourceConfig.record_xpath = data.detected_xpath;
        xpathInput.value = data.detected_xpath;

        // Update counts and render grid
        rowCountSpan.textContent = `Showing ${data.data.length} records`;
        initAgGrid(data.columns, data.data);

        // Update status badge
        const domain = new URL(url).hostname;
        statusIndicator.innerHTML = `<i class="bi bi-cloud-check-fill text-success me-1"></i> Connected: ${domain}`;
        statusIndicator.className = 'badge bg-success-subtle text-success border px-3 py-2 rounded-pill';

        // Trigger success callback
        onUploadSuccess(state);

    } catch (error) {
        console.error('XML URL Fetch error:', error);
        rowCountSpan.textContent = 'Failed to fetch URL feed';
        alert(`Error loading remote URL: ${error.message}`);
        statusIndicator.innerHTML = `<i class="bi bi-exclamation-circle-fill text-danger me-1"></i> Connection Failed`;
        statusIndicator.className = 'badge bg-danger-subtle text-danger border px-3 py-2 rounded-pill';
    }
}

/**
 * Load XML preview (uses either uploaded file or URL based on sourceType)
 */
export async function loadXmlPreview(state, onUploadSuccess) {
    if (state.sourceType === 'xml_url') {
        const auth_config = {
            auth_type: state.sourceConfig.auth_type || 'none',
            username: state.sourceConfig.username || '',
            password: state.sourceConfig.password || '',
            token: state.sourceConfig.token || '',
            header_name: state.sourceConfig.header_name || 'X-API-Key',
            header_value: state.sourceConfig.header_value || ''
        };
        return fetchXmlUrlPreview(state.sourceConfig.url, auth_config, state, onUploadSuccess);
    }

    if (!state.filename) return;

    const previewGridCard = document.getElementById('excel-preview-card');
    const rowCountSpan = document.getElementById('preview-row-count');
    const xpathInput = document.getElementById('xpath-override-input');

    try {
        previewGridCard.classList.remove('d-none');
        rowCountSpan.textContent = 'Loading XML...';

        let url = `/api/preview?filename=${encodeURIComponent(state.filename)}`;
        if (state.sourceConfig && state.sourceConfig.record_xpath) {
            url += `&xpath=${encodeURIComponent(state.sourceConfig.record_xpath)}`;
        }

        const response = await fetch(url);
        if (!response.ok) {
            let errMsg = 'Failed to parse XML preview';
            try {
                const errData = await response.json();
                errMsg = errData.error || errMsg;
            } catch (e) {
                errMsg = `Parse failed (Status ${response.status}): ${response.statusText}`;
            }
            throw new Error(errMsg);
        }

        const data = await response.json();

        // Store XML header names and preview records
        state.excelHeaders = data.columns.map(col => col.headerName);
        state.previewData = data.data;

        // Update record xpath UI
        state.sourceConfig = state.sourceConfig || {};
        state.sourceConfig.record_xpath = data.detected_xpath;
        xpathInput.value = data.detected_xpath;

        // Render preview
        rowCountSpan.textContent = `Showing ${data.data.length} records`;
        initAgGrid(data.columns, data.data);

        if (onUploadSuccess) {
            onUploadSuccess(state);
        }

    } catch (error) {
        console.error('XML Preview error:', error);
        rowCountSpan.textContent = 'Failed to parse XML feed records';
        alert(`Error loading XML preview: ${error.message}`);
    }
}

/**
 * Restores the XML Source UI fields based on loaded state
 */
export function restoreXmlSourceUI(state) {
    const tabExcelBtn = document.getElementById('excel-tab');
    const tabXmlFileBtn = document.getElementById('xml-file-tab');
    const tabXmlUrlBtn = document.getElementById('xml-url-tab');
    
    const urlInput = document.getElementById('source-url-input');
    const authTypeSelect = document.getElementById('url-auth-type');
    const xpathSwitch = document.getElementById('xpath-override-switch');
    const xpathInput = document.getElementById('xpath-override-input');
    const xpathCollapseEl = document.getElementById('xpath-override-collapse');
    
    // De-activate all tabs
    document.querySelectorAll('#source-type-tabs .nav-link').forEach(btn => {
        btn.classList.remove('active');
        btn.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('#source-type-tab-content .tab-pane').forEach(pane => {
        pane.classList.remove('show', 'active');
    });

    const worksheetCard = document.getElementById('worksheet-selection-card');
    const xpathControl = document.getElementById('xml-xpath-control');

    if (state.sourceType === 'excel') {
        tabExcelBtn.classList.add('active');
        tabExcelBtn.setAttribute('aria-selected', 'true');
        document.getElementById('source-excel').classList.add('show', 'active');
        worksheetCard.classList.remove('d-none');
        xpathControl.classList.add('d-none');
    } else if (state.sourceType === 'xml_file') {
        tabXmlFileBtn.classList.add('active');
        tabXmlFileBtn.setAttribute('aria-selected', 'true');
        document.getElementById('source-xml-file').classList.add('show', 'active');
        worksheetCard.classList.add('d-none');
        xpathControl.classList.remove('d-none');
    } else if (state.sourceType === 'xml_url') {
        tabXmlUrlBtn.classList.add('active');
        tabXmlUrlBtn.setAttribute('aria-selected', 'true');
        document.getElementById('source-xml-url').classList.add('show', 'active');
        worksheetCard.classList.add('d-none');
        xpathControl.classList.remove('d-none');
        
        // Restore URL field
        if (urlInput && state.sourceConfig) {
            urlInput.value = state.sourceConfig.url || '';
            authTypeSelect.value = state.sourceConfig.auth_type || 'none';
            authTypeSelect.dispatchEvent(new Event('change'));
            
            if (state.sourceConfig.auth_type === 'basic') {
                document.getElementById('auth-username').value = state.sourceConfig.username || '';
                document.getElementById('auth-password').value = '';
            } else if (state.sourceConfig.auth_type === 'bearer') {
                document.getElementById('auth-token').value = '';
            } else if (state.sourceConfig.auth_type === 'apikey') {
                document.getElementById('auth-header-name').value = state.sourceConfig.header_name || 'X-API-Key';
                document.getElementById('auth-header-value').value = '';
            }
        }
    }
    
    // Restore XPath overrides
    if (state.sourceConfig && state.sourceConfig.record_xpath) {
        xpathInput.value = state.sourceConfig.record_xpath;
        xpathSwitch.checked = true;
        const collapse = bootstrap.Collapse.getOrCreateInstance(xpathCollapseEl);
        collapse.show();
    } else {
        xpathSwitch.checked = false;
        xpathInput.value = '';
        const collapse = bootstrap.Collapse.getOrCreateInstance(xpathCollapseEl);
        collapse.hide();
    }
}
