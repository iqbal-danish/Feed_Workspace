/**
 * FeedForge SPA Main Entrypoint
 */

import { initExcelStep, renderWorksheetTabs } from './excel-handler.js';
import { initTemplateStep, loadTemplate, fetchTemplatesList } from './template-handler.js';
import { initMappingStep, renderMappingInterface } from './mapping-handler.js';
import { initWorkspaceStep } from './workspace-handler.js';
import { initGenerationStep } from './generation-handler.js';
import { initXmlSourceStep } from './xml-source-handler.js';

// Global application state
const appState = {
    filename: null,
    selectedSheet: null,
    sheets: [],
    excelHeaders: [],
    template: null,
    placeholders: [],
    mapping: {},
    staticFields: {},
    campaignCustomFields: [],
    awmConfig: { enabled: false, fields: {} },
    salaryConfig: { enabled: false, fields: {} },
    headersConfig: {},
    disabledFields: [],
    ftpConfig: {},
    sourceType: 'excel',
    sourceConfig: {},
    transforms: [],
    previewData: []
};

document.addEventListener('DOMContentLoaded', () => {
    console.log('FeedForge initialized.');
    initWorkflowNav();
    checkBackendHealth();
    
    // Initialize Step 1 (Excel & XML Inputs) handlers
    initExcelStep(appState, onExcelUploadSuccess);
    initXmlSourceStep(appState, onExcelUploadSuccess);
    
    // Initialize Step 2 (XML Template) handlers
    initTemplateStep(appState, onTemplateLoaded);
    
    // Initialize Step 3 (Field Mapping) handlers
    initMappingStep(appState, onMappingSaved);
    
    // Initialize Step 4 (XML Generation) handlers
    initGenerationStep(appState);
    
    // Initialize Workspace load/save modal listeners
    initWorkspaceStep(appState, onWorkspaceLoaded);
});

/**
 * Handle view switching in the sidebar workflow
 */
function initWorkflowNav() {
    const navButtons = document.querySelectorAll('#workflow-nav button');
    const stepViews = document.querySelectorAll('.workflow-step-view');

    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const stepId = btn.getAttribute('data-step');
            
            // Remove active classes
            navButtons.forEach(b => b.classList.remove('active'));
            stepViews.forEach(v => {
                v.classList.add('d-none');
                v.classList.remove('active-view');
            });

            // Set current active
            btn.classList.add('active');
            const activeView = document.getElementById(`step-view-${stepId}`);
            if (activeView) {
                activeView.classList.remove('d-none');
                activeView.classList.add('active-view');
            }
            
            // Trigger dynamic renders based on step selection
            if (stepId === '3') {
                renderMappingInterface(appState);
            }
        });
    });
}

/**
 * Callback when Excel file is successfully uploaded and validated
 */
function onExcelUploadSuccess(state) {
    // 1. Render worksheet tabs
    renderWorksheetTabs(state);
    
    // 2. Enable step 2 (XML Template) in the sidebar
    enableSidebarStep(2);
    
    // 3. Enable save workspace button
    const saveBtn = document.getElementById('btn-save-workspace');
    if (saveBtn) {
        saveBtn.removeAttribute('disabled');
    }
}

/**
 * Callback when XML Template is loaded and placeholders parsed
 */
function onTemplateLoaded(state) {
    console.log("Template loaded:", state.template, "Placeholders:", state.placeholders);
    
    // Enable step 3 (Field Mapping) in the sidebar
    enableSidebarStep(3);
}

/**
 * Callback when mappings and static fields are successfully validated
 */
function onMappingSaved(state) {
    console.log("Mappings saved:", state.mapping, "Static fields:", state.staticFields);
    
    // Enable step 4 (XML Generation) in the sidebar
    enableSidebarStep(4);
}

/**
 * Callback when a saved JSON workspace configuration is re-loaded
 */
async function onWorkspaceLoaded(state) {
    console.log("Restoring workspace state:", state);
    
    // 1. Update file status indicators
    const statusIndicator = document.getElementById('status-indicator');
    if (statusIndicator && state.filename) {
        statusIndicator.innerHTML = `<i class="bi bi-check-circle-fill text-success me-1"></i> ${state.filename}`;
        statusIndicator.className = 'badge bg-success-subtle text-success border px-3 py-2 rounded-pill';
    }
    
    const saveBtn = document.getElementById('btn-save-workspace');
    if (saveBtn) saveBtn.removeAttribute('disabled');
    
    // Reset all sidebar nav items to disabled state initially
    disableSidebarStep(2);
    disableSidebarStep(3);
    disableSidebarStep(4);
    
    // 1.5. Restore source selection UI tabs and properties
    try {
        const { restoreXmlSourceUI } = await import('./xml-source-handler.js');
        restoreXmlSourceUI(state);
    } catch (err) {
        console.error("Failed to restore XML source UI fields:", err);
    }

    // 2. Fetch sheet list / load XML preview
    if (state.sourceType === 'excel' && state.filename) {
        try {
            const res = await fetch(`/api/sheets?filename=${encodeURIComponent(state.filename)}`);
            if (res.ok) {
                const data = await res.json();
                state.sheets = data.sheets;
                renderWorksheetTabs(state);
                enableSidebarStep(2);
            }
        } catch (err) {
            console.error("Failed to restore sheets during workspace load:", err);
        }
    } else if (state.sourceType === 'xml_file' && state.filename) {
        try {
            const { loadXmlPreview } = await import('./xml-source-handler.js');
            await loadXmlPreview(state, () => {
                enableSidebarStep(2);
            });
        } catch (err) {
            console.error("Failed to restore XML file preview during workspace load:", err);
        }
    } else if (state.sourceType === 'xml_url' && state.sourceConfig && state.sourceConfig.url) {
        try {
            const { loadXmlPreview } = await import('./xml-source-handler.js');
            await loadXmlPreview(state, () => {
                enableSidebarStep(2);
            });
        } catch (err) {
            console.error("Failed to restore XML URL preview during workspace load:", err);
        }
    }
    
    // 3. Load template content and placeholders
    if (state.template) {
        try {
            await loadTemplate(state.template, state, () => {
                enableSidebarStep(3);
            });
            // Update select dropdown
            await fetchTemplatesList(state.template);
        } catch (err) {
            console.error("Failed to restore template during workspace load:", err);
        }
    }
    
    // 4. Restore mappings step (if mapping already exists)
    if (state.mapping && Object.keys(state.mapping).length > 0) {
        enableSidebarStep(4);
    }
    
    // Navigate back to Step 1 (Excel Spreadsheet) view so the user can see everything restored
    const step1Btn = document.querySelector('#workflow-nav button[data-step="1"]');
    if (step1Btn) {
        step1Btn.click();
    }
}

/**
 * Utility to enable a sidebar step button and style its circle badge
 */
function enableSidebarStep(stepNum) {
    const stepBtn = document.querySelector(`#workflow-nav button[data-step="${stepNum}"]`);
    if (stepBtn) {
        stepBtn.removeAttribute('disabled');
        const numSpan = stepBtn.querySelector('.step-num');
        if (numSpan) {
            numSpan.classList.remove('bg-secondary');
            numSpan.classList.add('bg-primary');
        }
    }
}

/**
 * Utility to disable a sidebar step button
 */
function disableSidebarStep(stepNum) {
    const stepBtn = document.querySelector(`#workflow-nav button[data-step="${stepNum}"]`);
    if (stepBtn) {
        stepBtn.setAttribute('disabled', 'true');
        const numSpan = stepBtn.querySelector('.step-num');
        if (numSpan) {
            numSpan.classList.remove('bg-primary');
            numSpan.classList.add('bg-secondary');
        }
    }
}

/**
 * Perform a health check call to the backend to verify connection
 */
async function checkBackendHealth() {
    const statusIndicator = document.getElementById('status-indicator');
    
    try {
        const response = await fetch('/api/health');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        
        if (data.status === 'healthy') {
            console.log('Successfully connected to FeedForge backend.');
        }
    } catch (error) {
        console.error('Failed to connect to backend:', error);
        if (statusIndicator) {
            statusIndicator.innerHTML = `<i class="bi bi-circle-fill text-danger me-1"></i> Offline`;
            statusIndicator.classList.remove('bg-light', 'text-secondary');
            statusIndicator.classList.add('bg-danger-subtle', 'text-danger');
        }
    }
}
