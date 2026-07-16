/**
 * Excel Spreadsheet Workflow Handler
 */

let gridApi = null;

export function initExcelStep(state, onUploadSuccess) {
    const dropZone = document.getElementById('excel-drop-zone');
    const fileInput = document.getElementById('excel-file-input');
    const browseBtn = document.getElementById('btn-browse-file');
    
    // Browse File button click handler
    browseBtn.addEventListener('click', () => {
        fileInput.click();
    });
    
    // File input change handler
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadFile(e.target.files[0], state, onUploadSuccess);
        }
    });
    
    // Drag and Drop event handlers
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
            uploadFile(e.dataTransfer.files[0], state, onUploadSuccess);
        }
    });
}

/**
 * Upload spreadsheet via POST API
 */
async function uploadFile(file, state, onUploadSuccess) {
    const statusIndicator = document.getElementById('status-indicator');
    
    // Simple extension check
    if (!file.name.endsWith('.xlsx')) {
        alert('Invalid file format. Please upload a .xlsx workbook.');
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
            const errData = await response.json();
            throw new Error(errData.error || 'Upload failed');
        }
        
        const data = await response.json();
        console.log('Upload success:', data);
        
        // Update App State
        state.filename = data.filename;
        state.sheets = data.sheets;
        state.selectedSheet = data.sheets[0] || null;
        
        // Update UI Indicators
        statusIndicator.innerHTML = `<i class="bi bi-check-circle-fill text-success me-1"></i> ${file.name}`;
        statusIndicator.classList.remove('bg-light', 'text-secondary');
        statusIndicator.classList.add('bg-success-subtle', 'text-success');
        
        // Trigger callback to render worksheets & enable next steps
        onUploadSuccess(state);
        
    } catch (error) {
        console.error('Upload error:', error);
        alert(`Error uploading file: ${error.message}`);
        statusIndicator.innerHTML = `<i class="bi bi-exclamation-circle-fill text-danger me-1"></i> Upload Failed`;
        statusIndicator.classList.remove('bg-light', 'text-secondary');
        statusIndicator.classList.add('bg-danger-subtle', 'text-danger');
    }
}

/**
 * Render sheet tabs and fetch data for the first sheet
 */
export function renderWorksheetTabs(state) {
    const tabsContainer = document.getElementById('worksheet-tabs-container');
    const selectionCard = document.getElementById('worksheet-selection-card');
    
    tabsContainer.innerHTML = '';
    if (state.sourceType === 'excel') {
        selectionCard.classList.remove('d-none');
    } else {
        selectionCard.classList.add('d-none');
        return;
    }
    
    state.sheets.forEach(sheetName => {
        const btn = document.createElement('button');
        btn.className = `btn btn-sm ${state.selectedSheet === sheetName ? 'btn-primary' : 'btn-outline-primary'}`;
        btn.textContent = sheetName;
        
        btn.addEventListener('click', () => {
            // Update selected sheet
            state.selectedSheet = sheetName;
            
            // Re-render tabs styles
            document.querySelectorAll('#worksheet-tabs-container button').forEach(b => {
                b.className = 'btn btn-sm btn-outline-primary';
            });
            btn.className = 'btn btn-sm btn-primary';
            
            loadSheetPreview(state);
        });
        
        tabsContainer.appendChild(btn);
    });
    
    // Load initial sheet preview
    loadSheetPreview(state);
}

/**
 * Fetch and load sheet rows into AG Grid
 */
async function loadSheetPreview(state) {
    if (!state.filename || !state.selectedSheet) return;
    
    const previewCard = document.getElementById('excel-preview-card');
    const rowCountSpan = document.getElementById('preview-row-count');
    
    try {
        previewCard.classList.remove('d-none');
        rowCountSpan.textContent = 'Loading...';
        
        const url = `/api/preview?filename=${encodeURIComponent(state.filename)}&sheet=${encodeURIComponent(state.selectedSheet)}`;
        const response = await fetch(url);
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Failed to fetch preview');
        }
        
        const data = await response.json();
        
        // Store excel headers and preview records in state for mapping/transforms
        state.excelHeaders = data.columns.map(col => col.headerName);
        state.previewData = data.data;
        
        // Update counts
        rowCountSpan.textContent = `Showing ${data.data.length} rows`;
        
        // Render AG Grid
        initAgGrid(data.columns, data.data);
        
    } catch (error) {
        console.error('Preview error:', error);
        rowCountSpan.textContent = 'Failed to load preview data';
        alert(`Error loading worksheet preview: ${error.message}`);
    }
}

/**
 * Initialize / Refresh AG Grid
 */
export function initAgGrid(columns, rowData) {
    const gridDiv = document.getElementById('excel-preview-grid');
    
    // Destroy existing grid to apply new dynamic column schema
    if (gridApi) {
        gridApi.destroy();
        gridApi = null;
    }
    
    const gridOptions = {
        columnDefs: columns,
        rowData: rowData,
        pagination: true,
        paginationPageSize: 10,
        paginationPageSizeSelector: [10, 20, 50],
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true,
            flex: 1,
            minWidth: 120
        }
    };
    
    gridApi = agGrid.createGrid(gridDiv, gridOptions);
}
