/**
 * Workspace Save & Load Workflow Handler
 */

let saveModalInstance = null;
let loadModalInstance = null;

export function initWorkspaceStep(state, onWorkspaceLoaded) {
    const saveToolbarBtn = document.getElementById('btn-save-workspace');
    const loadToolbarBtn = document.getElementById('btn-load-workspace');
    const confirmSaveBtn = document.getElementById('btn-confirm-save-workspace');
    
    const saveModalEl = document.getElementById('saveWorkspaceModal');
    const loadModalEl = document.getElementById('loadWorkspaceModal');
    
    // Initialize Bootstrap Modal instances
    saveModalInstance = new bootstrap.Modal(saveModalEl);
    loadModalInstance = new bootstrap.Modal(loadModalEl);
    
    // Toolbar Save Button Click -> Open Modal
    saveToolbarBtn.addEventListener('click', () => {
        document.getElementById('workspace-name-input').value = '';
        saveModalInstance.show();
    });
    
    // Toolbar Load Button Click -> Open Modal & Fetch workspaces
    loadToolbarBtn.addEventListener('click', () => {
        loadModalInstance.show();
        fetchWorkspacesList(state, onWorkspaceLoaded);
    });
    
    // Confirm Save inside modal
    confirmSaveBtn.addEventListener('click', () => {
        saveCurrentWorkspace(state);
    });
}

/**
 * Send POST API to save workspace JSON
 */
async function saveCurrentWorkspace(state) {
    const nameInput = document.getElementById('workspace-name-input');
    const name = nameInput.value.trim();
    
    if (!name) {
        alert('Please enter a valid workspace name.');
        return;
    }
    
    const payload = {
        name: name,
        filename: state.filename,
        worksheet: state.selectedSheet,
        template: state.template,
        mapping: state.mapping,
        static_fields: state.staticFields,
        campaign_custom_fields: state.campaignCustomFields,
        awm_config: state.awmConfig,
        salary_config: state.salaryConfig,
        headers_config: state.headersConfig,
        disabled_fields: state.disabledFields || [],
        ftp_config: state.ftpConfig || {},
        source_type: state.sourceType || 'excel',
        source_config: state.sourceConfig || {},
        transforms: state.transforms || []
    };
    
    try {
        const response = await fetch('/api/workspace/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Failed to save workspace');
        }
        
        const data = await response.json();
        alert(data.message);
        saveModalInstance.hide();
        
    } catch (err) {
        console.error(err);
        alert(`Save Workspace Error: ${err.message}`);
    }
}

/**
 * Retrieve and list workspaces in the load modal list group
 */
async function fetchWorkspacesList(state, onWorkspaceLoaded) {
    const listGroup = document.getElementById('workspaces-list-group');
    listGroup.innerHTML = '<span class="text-muted small text-center py-3">Fetching workspaces...</span>';
    
    try {
        const response = await fetch('/api/workspaces');
        if (!response.ok) throw new Error('Failed to retrieve workspaces.');
        
        const data = await response.json();
        listGroup.innerHTML = '';
        
        if (!data.workspaces || data.workspaces.length === 0) {
            listGroup.innerHTML = '<span class="text-muted small text-center py-3"><i class="bi bi-info-circle me-1"></i> No saved workspaces found.</span>';
            return;
        }
        
        data.workspaces.forEach(wsName => {
            const btn = document.createElement('button');
            btn.className = 'list-group-item list-group-item-action d-flex align-items-center justify-content-between py-2.5';
            btn.innerHTML = `
                <span><i class="bi bi-folder text-warning me-2"></i><strong>${wsName}</strong></span>
                <span class="badge bg-light text-secondary border">JSON</span>
            `;
            
            btn.addEventListener('click', () => {
                loadSelectedWorkspace(wsName, state, onWorkspaceLoaded);
            });
            
            listGroup.appendChild(btn);
        });
        
    } catch (err) {
        console.error(err);
        listGroup.innerHTML = `<span class="text-danger small text-center py-3"><i class="bi bi-exclamation-triangle me-1"></i> Error loading list: ${err.message}</span>`;
    }
}

/**
 * Load workspace content and update application state
 */
async function loadSelectedWorkspace(name, state, onWorkspaceLoaded) {
    try {
        const response = await fetch('/api/workspace/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Failed to load workspace.');
        }
        
        const data = await response.json();
        
        // Restore State
        state.filename = data.filename;
        state.selectedSheet = data.worksheet;
        state.template = data.template;
        state.mapping = data.mapping || {};
        state.staticFields = data.static_fields || {};
        state.campaignCustomFields = data.campaign_custom_fields || [];
        state.awmConfig = data.awm_config || { enabled: false, fields: {} };
        state.salaryConfig = data.salary_config || { enabled: false, fields: {} };
        state.headersConfig = data.headers_config || {};
        state.disabledFields = data.disabled_fields || [];
        state.ftpConfig = data.ftp_config || {};
        state.sourceType = data.source_type || 'excel';
        state.sourceConfig = data.source_config || {};
        state.transforms = data.transforms || [];
        
        loadModalInstance.hide();
        
        // Trigger callback to re-draw worksheets, preview grids, mapping matrix
        onWorkspaceLoaded(state);
        
        alert(`Workspace "${name}" loaded successfully!`);
        
    } catch (err) {
        console.error(err);
        alert(`Load Workspace Error: ${err.message}`);
    }
}
