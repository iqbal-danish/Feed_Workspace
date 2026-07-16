/**
 * XML Template Step Workflow Handler
 */

export function initTemplateStep(state, onTemplateLoaded) {
    const selectEl = document.getElementById('template-select');
    const loadBtn = document.getElementById('btn-load-selected-template');
    
    const dropZone = document.getElementById('template-drop-zone');
    const fileInput = document.getElementById('template-file-input');
    const browseBtn = document.getElementById('btn-browse-template');
    
    const editorEl = document.getElementById('template-editor');
    const filenameEl = document.getElementById('template-filename');
    const clearBtn = document.getElementById('btn-clear-template-editor');
    const saveBtn = document.getElementById('btn-save-template-editor');
    
    // 1. Initial load of available templates
    fetchTemplatesList();
    
    // 2. Select template load button
    loadBtn.addEventListener('click', () => {
        const filename = selectEl.value;
        if (filename) {
            loadTemplate(filename, state, onTemplateLoaded);
        } else {
            alert('Please select a template from the list first.');
        }
    });
    
    // 3. Upload events
    browseBtn.addEventListener('click', () => {
        fileInput.click();
    });
    
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadTemplate(e.target.files[0], state, onTemplateLoaded);
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
            uploadTemplate(e.dataTransfer.files[0], state, onTemplateLoaded);
        }
    });
    
    // 4. Editor button actions
    clearBtn.addEventListener('click', () => {
        editorEl.value = '';
        filenameEl.value = '';
        document.getElementById('detected-placeholders-card').classList.add('d-none');
        document.getElementById('template-edit-status').textContent = 'Cleared';
    });
    
    saveBtn.addEventListener('click', () => {
        saveEditorTemplate(state, onTemplateLoaded);
    });
}

/**
 * Fetch and render the list of template filenames in the dropdown
 */
export async function fetchTemplatesList(selectedFilename = null) {
    const selectEl = document.getElementById('template-select');
    try {
        const response = await fetch('/api/templates');
        if (!response.ok) throw new Error('Failed to retrieve templates list.');
        
        const data = await response.json();
        
        // Preserve selection or default
        selectEl.innerHTML = '<option value="">-- Select Template --</option>';
        data.templates.forEach(tpl => {
            const opt = document.createElement('option');
            opt.value = tpl;
            opt.textContent = tpl;
            if (tpl === selectedFilename) {
                opt.selected = true;
            }
            selectEl.appendChild(opt);
        });
    } catch (err) {
        console.error('Error fetching templates:', err);
    }
}

/**
 * Fetch specific template contents and placeholders from the API
 */
export async function loadTemplate(filename, state, onTemplateLoaded) {
    try {
        const response = await fetch(`/api/templates/parse?name=${encodeURIComponent(filename)}`);
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Failed to load template');
        }
        
        const data = await response.json();
        populateEditor(data.filename, data.content, data.placeholders);
        
        // Update App State
        state.template = data.filename;
        state.placeholders = data.placeholders;
        
        onTemplateLoaded(state);
    } catch (err) {
        console.error(err);
        alert(`Error loading template: ${err.message}`);
    }
}

/**
 * Upload XML file template using multipart/form-data
 */
async function uploadTemplate(file, state, onTemplateLoaded) {
    if (!file.name.endsWith('.xml')) {
        alert('Invalid file format. Only XML (.xml) files are supported.');
        return;
    }
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/api/templates/upload', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Template upload failed');
        }
        
        const data = await response.json();
        
        populateEditor(data.filename, data.content, data.placeholders);
        
        // Re-fetch template list and select the newly uploaded template
        await fetchTemplatesList(data.filename);
        
        // Update State
        state.template = data.filename;
        state.placeholders = data.placeholders;
        
        onTemplateLoaded(state);
        
    } catch (err) {
        console.error(err);
        alert(`Error uploading template: ${err.message}`);
    }
}

/**
 * Save template content currently inside the editor
 */
async function saveEditorTemplate(state, onTemplateLoaded) {
    const filenameEl = document.getElementById('template-filename');
    const editorEl = document.getElementById('template-editor');
    
    const filename = filenameEl.value.trim();
    const content = editorEl.value;
    
    if (!filename) {
        alert('Please enter a template filename (e.g. template.xml).');
        return;
    }
    if (!content.trim()) {
        alert('Please insert XML content.');
        return;
    }
    
    try {
        const response = await fetch('/api/templates/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, content })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Failed to save template');
        }
        
        const data = await response.json();
        
        // Populate editor clean states
        populateEditor(data.filename, data.content, data.placeholders);
        document.getElementById('template-edit-status').textContent = 'Saved';
        
        // Refresh dropdown
        await fetchTemplatesList(data.filename);
        
        // Update State
        state.template = data.filename;
        state.placeholders = data.placeholders;
        
        onTemplateLoaded(state);
        
        alert('Template saved successfully!');
    } catch (err) {
        console.error(err);
        alert(`Error saving template: ${err.message}`);
    }
}

/**
 * Fill editor textareas and trigger placeholders display card
 */
function populateEditor(filename, content, placeholders) {
    document.getElementById('template-filename').value = filename;
    document.getElementById('template-editor').value = content;
    document.getElementById('template-edit-status').textContent = 'Loaded';
    
    displayPlaceholders(placeholders);
}

/**
 * Display detected template variables inside badges
 */
function displayPlaceholders(placeholders) {
    const card = document.getElementById('detected-placeholders-card');
    const container = document.getElementById('placeholders-badges-container');
    
    container.innerHTML = '';
    
    if (!placeholders || placeholders.length === 0) {
        container.innerHTML = '<span class="text-danger small"><i class="bi bi-exclamation-triangle-fill me-1"></i> No placeholders detected. Make sure to use {{placeholder}} tags.</span>';
        card.classList.remove('d-none');
        return;
    }
    
    placeholders.forEach(pl => {
        const badge = document.createElement('span');
        badge.className = 'badge bg-info text-dark border px-2.5 py-1.5 rounded-pill font-monospace';
        badge.textContent = pl;
        container.appendChild(badge);
    });
    
    card.classList.remove('d-none');
}
