/**
 * Excel-to-XML Field Mapping Workflow Handler (Supporting dynamic configurations)
 */

export function initMappingStep(state, onMappingSaved) {
    const addStaticBtn = document.getElementById('btn-add-static-row');
    const saveMappingsBtn = document.getElementById('btn-save-mappings');
    const addCampaignFieldBtn = document.getElementById('btn-add-campaign-field');
    
    const awmSwitch = document.getElementById('awm-enabled-switch');
    const awmForm = document.getElementById('awm-fields-form');
    const salarySwitch = document.getElementById('salary-enabled-switch');
    const salaryForm = document.getElementById('salary-fields-form');
    
    // Add new static row
    addStaticBtn.addEventListener('click', () => {
        addStaticRow();
    });
    
    // Save and validate mappings
    saveMappingsBtn.addEventListener('click', () => {
        saveAndValidate(state, onMappingSaved);
    });
    
    // Add new campaign custom field
    addCampaignFieldBtn.addEventListener('click', () => {
        addCampaignFieldRow(state);
    });
    
    // Switch dynamic states for AWM & Salary forms
    awmSwitch.addEventListener('change', () => {
        if (awmSwitch.checked) {
            awmForm.classList.remove('opacity-50', 'pe-none');
        } else {
            awmForm.classList.add('opacity-50', 'pe-none');
        }
    });
    
    salarySwitch.addEventListener('change', () => {
        if (salarySwitch.checked) {
            salaryForm.classList.remove('opacity-50', 'pe-none');
        } else {
            salaryForm.classList.add('opacity-50', 'pe-none');
        }
    });
}

/**
 * Render the entire mapping screen based on the current app state
 */
export function renderMappingInterface(state) {
    const tableBody = document.getElementById('mapping-table-body');
    const staticContainer = document.getElementById('static-fields-container');
    const campaignContainer = document.getElementById('campaign-fields-container');
    
    // 1. Render Column Mappings Table (Filtering out mandatory feed header keys)
    tableBody.innerHTML = '';
    const headerKeys = ['provider', 'providerurl', 'isfullfeed', 'part', 'islast'];
    const filteredPlaceholders = (state.placeholders || []).filter(p => !headerKeys.includes(p));
    
    if (filteredPlaceholders.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="2" class="text-center text-muted py-3">
                    <i class="bi bi-exclamation-circle me-1"></i> No template placeholders loaded. Please check step 2.
                </td>
            </tr>
        `;
    } else {
        filteredPlaceholders.forEach(placeholder => {
            const tr = document.createElement('tr');
            tr.className = 'mapping-row';
            tr.setAttribute('data-placeholder', placeholder);
            
            // Checkbox column
            const tdActive = document.createElement('td');
            tdActive.className = 'text-center';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input mapping-active-checkbox';
            
            const isFieldDisabled = state.disabledFields && state.disabledFields.includes(placeholder);
            checkbox.checked = !isFieldDisabled;
            tdActive.appendChild(checkbox);
            tr.appendChild(tdActive);
            
            // XML Target tag
            const tdTarget = document.createElement('td');
            tdTarget.innerHTML = `<code class="text-dark fw-semibold" style="font-size: 0.9rem;">{{${placeholder}}}</code>`;
            tr.appendChild(tdTarget);
            
            // Excel column selector
            const tdSelect = document.createElement('td');
            const select = document.createElement('select');
            select.className = 'form-select form-select-sm mapping-select';
            select.setAttribute('data-placeholder', placeholder);
            if (isFieldDisabled) {
                select.disabled = true;
            }
            
            const defaultOpt = document.createElement('option');
            defaultOpt.value = '';
            defaultOpt.textContent = '[ None / Use Static Field ]';
            select.appendChild(defaultOpt);
            
            let mappedExcelCol = Object.keys(state.mapping).find(
                key => state.mapping[key] === placeholder
            );
            
            if (!mappedExcelCol && state.excelHeaders) {
                mappedExcelCol = findAutoMatch(placeholder, state.excelHeaders);
            }
            
            if (state.excelHeaders) {
                state.excelHeaders.forEach(colHeader => {
                    const opt = document.createElement('option');
                    opt.value = colHeader;
                    opt.textContent = colHeader;
                    if (colHeader === mappedExcelCol) {
                        opt.selected = true;
                    }
                    select.appendChild(opt);
                });
            }
            
            tdSelect.appendChild(select);
            tr.appendChild(tdSelect);
            
            // Transform (fx) Column
            const tdFx = document.createElement('td');
            tdFx.className = 'text-center';
            const fxBtn = document.createElement('button');
            fxBtn.type = 'button';
            fxBtn.className = 'btn btn-sm btn-outline-secondary px-2 btn-fx-trigger';
            fxBtn.setAttribute('data-placeholder', placeholder);
            
            // Check if there is an active transform for this placeholder
            const activeTransform = (state.transforms || []).find(t => t.target_field === placeholder);
            if (activeTransform && activeTransform.function) {
                fxBtn.className = 'btn btn-sm btn-success px-2 btn-fx-trigger';
                fxBtn.innerHTML = `<i class="bi bi-function me-1"></i>${activeTransform.function}`;
            } else {
                fxBtn.innerHTML = `<i class="bi bi-function me-1"></i>fx`;
            }
            
            fxBtn.addEventListener('click', () => {
                openTransformEditor(placeholder, state, fxBtn);
            });
            
            if (isFieldDisabled) {
                fxBtn.disabled = true;
            }
            
            tdFx.appendChild(fxBtn);
            tr.appendChild(tdFx);
            tableBody.appendChild(tr);
            
            // Toggle dropdown and fx button interactive state
            checkbox.addEventListener('change', () => {
                select.disabled = !checkbox.checked;
                fxBtn.disabled = !checkbox.checked;
            });
        });
    }
    
    // 2. Render Feed Headers (Mandatory feed root tags)
    if (!state.headersConfig || Object.keys(state.headersConfig).length === 0) {
        state.headersConfig = {
            provider: { source_type: 'static', value: 'Monster' },
            providerurl: { source_type: 'static', value: 'www.monster.com' },
            isfullfeed: { source_type: 'static', value: 'true' },
            part: { source_type: 'static', value: '1' },
            islast: { source_type: 'static', value: 'true' }
        };
    }
    renderBlockConfig('headers-rows-container', headerKeys, state.headersConfig, state.excelHeaders);
    
    // 3. Render Static Fields (For custom static tags)
    staticContainer.innerHTML = '';
    if (state.staticFields && Object.keys(state.staticFields).length > 0) {
        // Exclude the headerKeys from showing in the static fields list as they are managed above
        Object.entries(state.staticFields).forEach(([key, val]) => {
            if (!headerKeys.includes(key)) {
                addStaticRow(key, val);
            }
        });
    }
    // If staticFields container is empty, we don't force a row, but if it starts empty we add one blank
    if (staticContainer.children.length === 0) {
        addStaticRow();
    }
    
    // 4. Render Campaign Custom Fields
    campaignContainer.innerHTML = '';
    if (state.campaignCustomFields && state.campaignCustomFields.length > 0) {
        state.campaignCustomFields.forEach(f => {
            addCampaignFieldRow(state, f.name, f.source_type, f.value);
        });
    } else {
        addCampaignFieldRow(state);
    }
    
    // 5. Render AWM Configuration
    const awmSwitch = document.getElementById('awm-enabled-switch');
    const awmForm = document.getElementById('awm-fields-form');
    const hasAwm = !!(state.awmConfig && state.awmConfig.enabled);
    awmSwitch.checked = hasAwm;
    if (hasAwm) {
        awmForm.classList.remove('opacity-50', 'pe-none');
    } else {
        awmForm.classList.add('opacity-50', 'pe-none');
    }
    renderBlockConfig('awm-rows-container', ['method', 'format', 'email', 'apikey'], state.awmConfig, state.excelHeaders);
    
    // 6. Render Salary Configuration
    const salarySwitch = document.getElementById('salary-enabled-switch');
    const salaryForm = document.getElementById('salary-fields-form');
    const hasSalary = !!(state.salaryConfig && state.salaryConfig.enabled);
    salarySwitch.checked = hasSalary;
    if (hasSalary) {
        salaryForm.classList.remove('opacity-50', 'pe-none');
    } else {
        salaryForm.classList.add('opacity-50', 'pe-none');
    }
    renderBlockConfig('salary-rows-container', ['min', 'max', 'type', 'currency'], state.salaryConfig, state.excelHeaders);
}

/**
 * Append a key-value row for static fields
 */
function addStaticRow(key = '', value = '') {
    const container = document.getElementById('static-fields-container');
    const row = document.createElement('div');
    row.className = 'd-flex align-items-center gap-2 static-row';
    
    row.innerHTML = `
        <input type="text" class="form-control form-control-sm static-key font-monospace" style="width: 40%;" placeholder="XML Tag" value="${escapeHtml(key)}">
        <span class="text-muted">=</span>
        <input type="text" class="form-control form-control-sm static-value" style="width: 46%;" placeholder="Value" value="${escapeHtml(value)}">
        <button class="btn btn-outline-danger btn-sm btn-delete-static" style="width: 10%;"><i class="bi bi-trash"></i></button>
    `;
    
    row.querySelector('.btn-delete-static').addEventListener('click', () => {
        row.remove();
    });
    
    container.appendChild(row);
}

/**
 * Append a Campaign Custom Field row
 */
function addCampaignFieldRow(state, name = '', sourceType = 'static', value = '') {
    const container = document.getElementById('campaign-fields-container');
    const tr = document.createElement('tr');
    tr.className = 'campaign-row';
    
    // Column 1: Field Name
    const tdName = document.createElement('td');
    tdName.innerHTML = `<input type="text" class="form-control form-control-sm campaign-key font-monospace" placeholder="e.g. priority" value="${escapeHtml(name)}">`;
    tr.appendChild(tdName);
    
    // Column 2: Source Type
    const tdType = document.createElement('td');
    const typeSelect = document.createElement('select');
    typeSelect.className = 'form-select form-select-sm campaign-type-select';
    typeSelect.innerHTML = `
        <option value="static" ${sourceType === 'static' ? 'selected' : ''}>Static Value</option>
        <option value="column" ${sourceType === 'column' ? 'selected' : ''}>Excel Column</option>
    `;
    tdType.appendChild(typeSelect);
    tr.appendChild(tdType);
    
    // Column 3: Value Container
    const tdVal = document.createElement('td');
    tdVal.className = 'campaign-value-container';
    tr.appendChild(tdVal);
    
    // Column 4: Delete button
    const tdDel = document.createElement('td');
    tdDel.className = 'text-center';
    tdDel.innerHTML = `<button class="btn btn-outline-danger btn-sm btn-delete-campaign"><i class="bi bi-trash"></i></button>`;
    tr.appendChild(tdDel);
    
    const updateValueCell = (currentType, currentValue) => {
        tdVal.innerHTML = '';
        if (currentType === 'column') {
            const select = document.createElement('select');
            select.className = 'form-select form-select-sm campaign-value-select';
            select.innerHTML = '<option value="">-- Select Column --</option>';
            if (state.excelHeaders) {
                state.excelHeaders.forEach(col => {
                    const opt = document.createElement('option');
                    opt.value = col;
                    opt.textContent = col;
                    if (col === currentValue) opt.selected = true;
                    select.appendChild(opt);
                });
            }
            tdVal.appendChild(select);
        } else {
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'form-control form-control-sm campaign-value-input';
            input.placeholder = 'Static value';
            input.value = currentValue;
            tdVal.appendChild(input);
        }
    };
    
    updateValueCell(sourceType, value);
    
    typeSelect.addEventListener('change', () => {
        updateValueCell(typeSelect.value, '');
    });
    
    tdDel.querySelector('.btn-delete-campaign').addEventListener('click', () => {
        tr.remove();
    });
    
    container.appendChild(tr);
}

/**
 * Render sub-field configurators for configuration blocks (Headers, AWM, Salary)
 */
function renderBlockConfig(containerId, fields, currentConfig, excelHeaders) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    
    fields.forEach(field => {
        const row = document.createElement('div');
        row.className = 'row g-2 align-items-center block-row';
        row.setAttribute('data-field', field);
        
        // Col 1: Label
        const colLabel = document.createElement('div');
        colLabel.className = 'col-3 text-end';
        let labelName = field;
        if (field === 'providerurl') labelName = 'URL';
        else if (field === 'email') labelName = 'Email/Post URL';
        colLabel.innerHTML = `<label class="col-form-label col-form-label-sm fw-medium text-capitalize">${labelName}:</label>`;
        row.appendChild(colLabel);
        
        // Col 2: Source Type
        const colType = document.createElement('div');
        colType.className = 'col-3';
        const typeSelect = document.createElement('select');
        typeSelect.className = 'form-select form-select-sm block-type-select';
        
        const fieldConfig = (currentConfig && currentConfig.fields) ? currentConfig.fields[field] : (currentConfig ? currentConfig[field] : {});
        const currentType = fieldConfig ? (fieldConfig.source_type || 'static') : 'static';
        const currentValue = fieldConfig ? (fieldConfig.value || '') : '';
        
        typeSelect.innerHTML = `
            <option value="static" ${currentType === 'static' ? 'selected' : ''}>Static</option>
            <option value="column" ${currentType === 'column' ? 'selected' : ''}>Column</option>
        `;
        colType.appendChild(typeSelect);
        row.appendChild(colType);
        
        // Col 3: Value selector
        const colVal = document.createElement('div');
        colVal.className = 'col-6 block-value-container';
        row.appendChild(colVal);
        
        const updateValueInput = (type, val) => {
            colVal.innerHTML = '';
            if (type === 'column') {
                const select = document.createElement('select');
                select.className = 'form-select form-select-sm block-value-select';
                select.innerHTML = '<option value="">-- Select Column --</option>';
                if (excelHeaders) {
                    excelHeaders.forEach(col => {
                        const opt = document.createElement('option');
                        opt.value = col;
                        opt.textContent = col;
                        if (col === val) opt.selected = true;
                        select.appendChild(opt);
                    });
                }
                colVal.appendChild(select);
            } else {
                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'form-control form-control-sm block-value-input';
                input.placeholder = `Static ${field} value`;
                input.value = val;
                
                if (field === 'method') {
                    input.setAttribute('list', 'awm-method-suggestions');
                    if (!document.getElementById('awm-method-suggestions')) {
                        const dl = document.createElement('datalist');
                        dl.id = 'awm-method-suggestions';
                        dl.innerHTML = `
                            <option value="POST2"></option>
                            <option value="Email"></option>
                        `;
                        document.body.appendChild(dl);
                    }
                } else if (field === 'format') {
                    input.setAttribute('list', 'awm-format-suggestions');
                    if (!document.getElementById('awm-format-suggestions')) {
                        const dl = document.createElement('datalist');
                        dl.id = 'awm-format-suggestions';
                        dl.innerHTML = `
                            <option value="JSON"></option>
                            <option value="XML"></option>
                        `;
                        document.body.appendChild(dl);
                    }
                }
                colVal.appendChild(input);
            }
        };
        
        updateValueInput(currentType, currentValue);
        
        typeSelect.addEventListener('change', () => {
            updateValueInput(typeSelect.value, '');
        });
        
        container.appendChild(row);
    });
}

/**
 * Validate selections and serialize them into the state object
 */
async function saveAndValidate(state, onMappingSaved) {
    const saveBtn = document.getElementById('btn-save-mappings');
    
    // 1. Column Mappings & Disabled Fields
    const mapping = {};
    const disabledFields = [];
    document.querySelectorAll('.mapping-row').forEach(row => {
        const placeholder = row.getAttribute('data-placeholder');
        const isActive = row.querySelector('.mapping-active-checkbox').checked;
        const select = row.querySelector('.mapping-select');
        
        if (isActive) {
            const excelCol = select.value;
            if (excelCol) {
                mapping[excelCol] = placeholder;
            }
        } else {
            disabledFields.push(placeholder);
        }
    });
    
    // 2. Feed Headers Config (Mandatory block validation)
    const headersFields = {};
    let missingHeaderField = false;
    document.querySelectorAll('#headers-rows-container .block-row').forEach(row => {
        const field = row.getAttribute('data-field');
        const type = row.querySelector('.block-type-select').value;
        let value = '';
        if (type === 'column') {
            value = row.querySelector('.block-value-select').value;
        } else {
            value = row.querySelector('.block-value-input').value.trim();
        }
        if (!value) {
            missingHeaderField = true;
        }
        headersFields[field] = { source_type: type, value };
    });
    
    if (missingHeaderField) {
        alert('Please configure all Feed Headers. They are mandatory.');
        return;
    }
    
    // 3. Static Fields
    const staticFields = {};
    document.querySelectorAll('.static-row').forEach(row => {
        const key = row.querySelector('.static-key').value.trim();
        const val = row.querySelector('.static-value').value;
        if (key) {
            staticFields[key] = val;
        }
    });
    
    // 4. Campaign Custom Fields
    const campaignFields = [];
    let hasInvalidCampaign = false;
    document.querySelectorAll('.campaign-row').forEach(row => {
        const name = row.querySelector('.campaign-key').value.trim();
        const type = row.querySelector('.campaign-type-select').value;
        let value = '';
        if (type === 'column') {
            value = row.querySelector('.campaign-value-select').value;
        } else {
            value = row.querySelector('.campaign-value-input').value;
        }
        
        if (name) {
            if (!/^[a-zA-Z_][a-zA-Z0-9_\-\.]*$/.test(name)) {
                hasInvalidCampaign = true;
                row.querySelector('.campaign-key').classList.add('is-invalid');
            } else {
                row.querySelector('.campaign-key').classList.remove('is-invalid');
                campaignFields.push({ name, source_type: type, value });
            }
        }
    });
    
    if (hasInvalidCampaign) {
        alert('Some campaign custom fields have invalid XML tag names.');
        return;
    }
    
    // 5. AWM Config
    const awmEnabled = document.getElementById('awm-enabled-switch').checked;
    const awmFields = {};
    document.querySelectorAll('#awm-rows-container .block-row').forEach(row => {
        const field = row.getAttribute('data-field');
        const type = row.querySelector('.block-type-select').value;
        let value = '';
        if (type === 'column') {
            value = row.querySelector('.block-value-select').value;
        } else {
            value = row.querySelector('.block-value-input').value.trim();
        }
        awmFields[field] = { source_type: type, value };
    });
    const awmConfig = { enabled: awmEnabled, fields: awmFields };
    
    // 6. Salary Config
    const salaryEnabled = document.getElementById('salary-enabled-switch').checked;
    const salaryFields = {};
    document.querySelectorAll('#salary-rows-container .block-row').forEach(row => {
        const field = row.getAttribute('data-field');
        const type = row.querySelector('.block-type-select').value;
        let value = '';
        if (type === 'column') {
            value = row.querySelector('.block-value-select').value;
        } else {
            value = row.querySelector('.block-value-input').value.trim();
        }
        salaryFields[field] = { source_type: type, value };
    });
    const salaryConfig = { enabled: salaryEnabled, fields: salaryFields };
    
    try {
        saveBtn.disabled = true;
        saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> Validating...`;
        
        // Post mapping validation
        const mappingRes = await fetch('/api/mapping', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: state.filename,
                sheet: state.selectedSheet,
                mapping: mapping,
                source_type: state.sourceType || 'excel',
                source_config: state.sourceConfig || {}
            })
        });
        
        if (!mappingRes.ok) {
            const errData = await mappingRes.json();
            throw new Error(errData.error || 'Excel column mapping validation failed');
        }
        
        // Post static fields validation
        const staticRes = await fetch('/api/static-fields', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                static_fields: staticFields
            })
        });
        
        if (!staticRes.ok) {
            const errData = await staticRes.json();
            throw new Error(errData.error || 'Static fields validation failed');
        }
        
        // Validation succeeded, update global state
        state.mapping = mapping;
        state.staticFields = staticFields;
        state.campaignCustomFields = campaignFields;
        state.awmConfig = awmConfig;
        state.salaryConfig = salaryConfig;
        state.headersConfig = headersFields;
        state.disabledFields = disabledFields;
        state.transforms = (state.transforms || []).filter(t => !disabledFields.includes(t.target_field));
        
        alert('Mappings and dynamic fields saved and validated successfully!');
        onMappingSaved(state);
        
    } catch (err) {
        console.error(err);
        alert(`Validation Error: ${err.message}`);
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = `<i class="bi bi-check2-circle me-1"></i>Save & Validate Mappings`;
    }
}

/**
 * Escapes HTML characters to prevent XSS in inputs
 */
function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/**
 * Attempt to match an XML placeholder to a spreadsheet column header automatically
 */
function findAutoMatch(placeholder, headers) {
    if (!headers || headers.length === 0) return '';
    
    const cleanPh = placeholder.toLowerCase().replace(/[^a-z0-9]/g, '');
    
    // 1. Exact clean match (e.g., "jobtitle" === "jobtitle")
    let match = headers.find(h => {
        const cleanH = h.toLowerCase().replace(/[^a-z0-9]/g, '');
        return cleanH === cleanPh;
    });
    if (match) return match;
    
    // 2. Contains match (e.g., "job title" overlaps with "title")
    match = headers.find(h => {
        const cleanH = h.toLowerCase().replace(/[^a-z0-9]/g, '');
        return cleanH.includes(cleanPh) || cleanPh.includes(cleanH);
    });
    if (match) return match;
    
    // 3. Common abbreviations/synonyms map
    const commonSynonyms = {
        'title': ['jobtitle', 'name', 'position', 'role'],
        'company': ['employer', 'companyname', 'brand', 'organization'],
        'posteddate': ['dateposted', 'posted', 'date', 'creationdate'],
        'refcode': ['reference', 'jobid', 'id', 'ref', 'code'],
        'postalcode': ['zip', 'zipcode', 'postal', 'postcode'],
        'description': ['desc', 'jobdescription', 'body', 'text'],
        'salary_min': ['minsalary', 'salarymin', 'min', 'salaryfrom'],
        'salary_max': ['maxsalary', 'salarymax', 'max', 'salaryto']
    };
    
    const synonyms = commonSynonyms[placeholder];
    if (synonyms) {
        for (const syn of synonyms) {
            const found = headers.find(h => {
                const cleanH = h.toLowerCase().replace(/[^a-z0-9]/g, '');
                return cleanH === syn || cleanH.includes(syn) || syn.includes(cleanH);
            });
            if (found) return found;
        }
    }
    
    return '';
}

/**
 * Opens the transform editor modal for a specific placeholder
 */
export function openTransformEditor(placeholder, state, fxBtn) {
    const modalEl = document.getElementById('transformModal');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    
    // Set target field
    document.getElementById('transform-target-field').value = placeholder;
    
    const funcSelect = document.getElementById('transform-function');
    
    // Find active transform
    const activeTransform = (state.transforms || []).find(t => t.target_field === placeholder);
    
    // Set active function
    funcSelect.value = activeTransform ? activeTransform.function : '';
    
    // Render initial arguments and preview
    renderTransformArgs(funcSelect.value, activeTransform, state);
    updateLivePreview(placeholder, state);
    
    // Setup listener on function selection change
    const onFuncChange = () => {
        renderTransformArgs(funcSelect.value, null, state);
        updateLivePreview(placeholder, state);
        
        // Add listener to new dynamic inputs to refresh preview
        const inputs = document.getElementById('transform-args-container').querySelectorAll('input, select');
        inputs.forEach(input => {
            input.addEventListener('input', () => updateLivePreview(placeholder, state));
            input.addEventListener('change', () => updateLivePreview(placeholder, state));
        });
    };
    
    funcSelect.removeEventListener('change', funcSelect._onFuncChange);
    funcSelect._onFuncChange = onFuncChange;
    funcSelect.addEventListener('change', onFuncChange);
    
    // Add input listeners initially if arguments are rendered
    const inputs = document.getElementById('transform-args-container').querySelectorAll('input, select');
    inputs.forEach(input => {
        input.addEventListener('input', () => updateLivePreview(placeholder, state));
        input.addEventListener('change', () => updateLivePreview(placeholder, state));
    });
    
    // Save button handler
    const saveBtn = document.getElementById('btn-save-transform');
    const onSave = () => {
        const funcName = funcSelect.value;
        if (!state.transforms) state.transforms = [];
        
        // Remove existing
        state.transforms = state.transforms.filter(t => t.target_field !== placeholder);
        
        if (funcName) {
            const args = [];
            if (funcName === 'concat') {
                args.push(document.getElementById('arg-sep').value);
                const selectors = document.querySelectorAll('.arg-concat-select');
                const textInputs = document.querySelectorAll('.arg-concat-text');
                for (let i = 0; i < 3; i++) {
                    if (selectors[i].value) {
                        args.push(selectors[i].value);
                    } else {
                        args.push(textInputs[i].value);
                    }
                }
            } else if (funcName === 'substring') {
                args.push(document.getElementById('arg-start').value);
                args.push(document.getElementById('arg-end').value);
            } else if (funcName === 'tokenize') {
                args.push(document.getElementById('arg-delim').value);
                args.push(document.getElementById('arg-index').value);
            } else if (funcName === 'replace') {
                args.push(document.getElementById('arg-search').value);
                args.push(document.getElementById('arg-replace').value);
            } else if (funcName === 'regex_replace') {
                args.push(document.getElementById('arg-pattern').value);
                args.push(document.getElementById('arg-replace-with').value);
            } else if (funcName === 'default') {
                args.push(document.getElementById('arg-fallback').value);
            } else if (funcName === 'date_format') {
                args.push(document.getElementById('arg-in-fmt').value);
                args.push(document.getElementById('arg-out-fmt').value);
            } else if (funcName === 'contains') {
                args.push(document.getElementById('arg-search-str').value);
                args.push(document.getElementById('arg-match-val').value);
                args.push(document.getElementById('arg-otherwise-val').value);
            }
            
            state.transforms.push({
                target_field: placeholder,
                function: funcName,
                args: args
            });
            
            // Highlight button
            fxBtn.className = 'btn btn-sm btn-success px-2 btn-fx-trigger';
            fxBtn.innerHTML = `<i class="bi bi-function me-1"></i>${funcName}`;
        } else {
            // Restore button
            fxBtn.className = 'btn btn-sm btn-outline-secondary px-2 btn-fx-trigger';
            fxBtn.innerHTML = `<i class="bi bi-function me-1"></i>fx`;
        }
        
        modal.hide();
        saveBtn.removeEventListener('click', onSave);
    };
    
    // Remove past save listeners to avoid stack duplication
    const newSaveBtn = saveBtn.cloneNode(true);
    saveBtn.parentNode.replaceChild(newSaveBtn, saveBtn);
    newSaveBtn.addEventListener('click', onSave);
    
    modal.show();
}

/**
 * Render dynamic function inputs
 */
function renderTransformArgs(funcName, activeTransform, state) {
    const container = document.getElementById('transform-args-container');
    container.innerHTML = '';
    
    if (!funcName) {
        container.classList.add('d-none');
        return;
    }
    
    container.classList.remove('d-none');
    const args = activeTransform && activeTransform.function === funcName ? activeTransform.args : [];
    
    switch (funcName) {
        case 'concat':
            // Render separator
            const sepDiv = document.createElement('div');
            sepDiv.className = 'mb-2';
            sepDiv.innerHTML = `
                <label class="form-label text-muted small fw-semibold">Concatenation Separator</label>
                <input type="text" id="arg-sep" class="form-control form-control-sm" placeholder="e.g. - or space or leave blank" value="${args[0] !== undefined ? args[0] : ''}">
            `;
            container.appendChild(sepDiv);
            
            // Title
            const partsLabel = document.createElement('label');
            partsLabel.className = 'form-label text-muted small fw-semibold d-block mt-3 mb-1';
            partsLabel.textContent = 'Fields / Values to Concat (Select or Type)';
            container.appendChild(partsLabel);
            
            for (let i = 1; i <= 3; i++) {
                const val = args[i] || '';
                const grp = document.createElement('div');
                grp.className = 'input-group input-group-sm mb-2';
                
                let selectHtml = `<select class="form-select form-select-sm arg-concat-select"><option value="">[ None / Static Text ]</option>`;
                if (state.excelHeaders) {
                    state.excelHeaders.forEach(col => {
                        const optionVal = `$${col}`;
                        const isSelected = val === optionVal ? 'selected' : '';
                        selectHtml += `<option value="${optionVal}" ${isSelected}>${col}</option>`;
                    });
                }
                selectHtml += `</select>`;
                
                grp.innerHTML = `
                    <span class="input-group-text bg-light text-muted">Part ${i}</span>
                    ${selectHtml}
                    <input type="text" class="form-control arg-concat-text" placeholder="Or type static text..." value="${val.startsWith('$') ? '' : val}">
                `;
                
                const sel = grp.querySelector('select');
                const txt = grp.querySelector('input');
                sel.addEventListener('change', () => {
                    if (sel.value) {
                        txt.value = '';
                        txt.disabled = true;
                    } else {
                        txt.disabled = false;
                    }
                });
                if (val.startsWith('$')) {
                    txt.disabled = true;
                }
                
                container.appendChild(grp);
            }
            break;
            
        case 'substring':
            container.innerHTML = `
                <div class="row g-2">
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Start Index (0-based)</label>
                        <input type="number" id="arg-start" class="form-control form-control-sm" value="${args[0] !== undefined ? args[0] : 0}" min="0">
                    </div>
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">End Index (Optional)</label>
                        <input type="number" id="arg-end" class="form-control form-control-sm" placeholder="End position" value="${args[1] !== undefined ? args[1] : ''}" min="0">
                    </div>
                </div>
            `;
            break;
            
        case 'tokenize':
            container.innerHTML = `
                <div class="row g-2">
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Delimiter String</label>
                        <input type="text" id="arg-delim" class="form-control form-control-sm" value="${args[0] !== undefined ? args[0] : ','}">
                    </div>
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Token Index (0-based)</label>
                        <input type="number" id="arg-index" class="form-control form-control-sm" value="${args[1] !== undefined ? args[1] : 0}" min="0">
                    </div>
                </div>
            `;
            break;
            
        case 'replace':
            container.innerHTML = `
                <div class="row g-2">
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Search For</label>
                        <input type="text" id="arg-search" class="form-control form-control-sm" placeholder="Text to match" value="${args[0] || ''}">
                    </div>
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Replace With</label>
                        <input type="text" id="arg-replace" class="form-control form-control-sm" placeholder="New replacement" value="${args[1] || ''}">
                    </div>
                </div>
            `;
            break;
            
        case 'default':
            container.innerHTML = `
                <div class="mb-2">
                    <label class="form-label text-muted small fw-semibold">Fallback Default Value</label>
                    <input type="text" id="arg-fallback" class="form-control form-control-sm" placeholder="Fallback if field is empty" value="${args[0] || ''}">
                </div>
            `;
            break;
            
        case 'date_format':
            container.innerHTML = `
                <div class="row g-2">
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Input Format (strptime)</label>
                        <input type="text" id="arg-in-fmt" class="form-control form-control-sm" placeholder="e.g. %Y-%m-%d" value="${args[0] || ''}">
                    </div>
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Output Format (strftime)</label>
                        <input type="text" id="arg-out-fmt" class="form-control form-control-sm" placeholder="e.g. %d/%m/%Y" value="${args[1] || ''}">
                    </div>
                </div>
            `;
            break;
            
        case 'regex_replace':
            container.innerHTML = `
                <div class="row g-2">
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Regex Pattern</label>
                        <input type="text" id="arg-pattern" class="form-control form-control-sm" placeholder="e.g. \\\\d+" value="${args[0] || ''}">
                    </div>
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Replacement Text</label>
                        <input type="text" id="arg-replace-with" class="form-control form-control-sm" placeholder="e.g. XXX" value="${args[1] || ''}">
                    </div>
                </div>
            `;
            break;
            
        case 'url_encode':
            container.innerHTML = `
                <div class="text-muted small py-2">
                    <i class="bi bi-info-circle me-1"></i> URL Encode: Converts special characters to percentage-encoded sequences (e.g. spaces to %20). Requires no arguments.
                </div>
            `;
            break;
            
        case 'url_decode':
            container.innerHTML = `
                <div class="text-muted small py-2">
                    <i class="bi bi-info-circle me-1"></i> URL Decode: Decodes percentage-encoded characters back to plain text. Requires no arguments.
                </div>
            `;
            break;
            
        case 'contains':
            container.innerHTML = `
                <div class="mb-2">
                    <label class="form-label text-muted small fw-semibold">Search Substring</label>
                    <input type="text" id="arg-search-str" class="form-control form-control-sm" placeholder="Search keyword..." value="${args[0] || ''}">
                </div>
                <div class="row g-2">
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Match Value</label>
                        <input type="text" id="arg-match-val" class="form-control form-control-sm" placeholder="If matched" value="${args[1] || ''}">
                    </div>
                    <div class="col">
                        <label class="form-label text-muted small fw-semibold">Otherwise Value</label>
                        <input type="text" id="arg-otherwise-val" class="form-control form-control-sm" placeholder="Else value" value="${args[2] || ''}">
                    </div>
                </div>
            `;
            break;
            
        default:
            container.innerHTML = `
                <div class="text-muted small py-2">
                    <i class="bi bi-info-circle me-1"></i> This function requires no parameters and applies directly to the field value.
                </div>
            `;
            break;
    }
}

/**
 * Update live preview outputs inside modal
 */
function updateLivePreview(placeholder, state) {
    const previewCard = document.getElementById('transform-preview-card');
    const inputSpan = document.getElementById('transform-preview-input');
    const outputSpan = document.getElementById('transform-preview-output');
    const funcSelect = document.getElementById('transform-function');
    
    const funcName = funcSelect.value;
    if (!funcName) {
        previewCard.classList.add('d-none');
        return;
    }
    
    // Find mapped source column
    const selectEl = document.querySelector(`.mapping-select[data-placeholder="${placeholder}"]`);
    const mappedCol = selectEl ? selectEl.value : null;
    
    // Load first preview row
    const sampleRow = (state.previewData && state.previewData[0]) ? state.previewData[0] : null;
    const colIdx = state.excelHeaders ? state.excelHeaders.indexOf(mappedCol) : -1;
    const fieldKey = colIdx !== -1 ? `col_${colIdx}` : null;
    
    const rawInputVal = (sampleRow && fieldKey) ? sampleRow[fieldKey] : '';
    
    // Collect modal args
    const args = [];
    if (funcName === 'concat') {
        const sepEl = document.getElementById('arg-sep');
        args.push(sepEl ? sepEl.value : '');
        const selectors = document.querySelectorAll('.arg-concat-select');
        const textInputs = document.querySelectorAll('.arg-concat-text');
        for (let i = 0; i < 3; i++) {
            if (selectors[i] && selectors[i].value) {
                args.push(selectors[i].value);
            } else if (textInputs[i]) {
                args.push(textInputs[i].value);
            }
        }
    } else if (funcName === 'substring') {
        const startEl = document.getElementById('arg-start');
        const endEl = document.getElementById('arg-end');
        args.push(startEl ? startEl.value : '0');
        args.push(endEl ? endEl.value : '');
    } else if (funcName === 'tokenize') {
        const delimEl = document.getElementById('arg-delim');
        const idxEl = document.getElementById('arg-index');
        args.push(delimEl ? delimEl.value : ',');
        args.push(idxEl ? idxEl.value : '0');
    } else if (funcName === 'replace') {
        const searchEl = document.getElementById('arg-search');
        const replaceEl = document.getElementById('arg-replace');
        args.push(searchEl ? searchEl.value : '');
        args.push(replaceEl ? replaceEl.value : '');
    } else if (funcName === 'regex_replace') {
        const patternEl = document.getElementById('arg-pattern');
        const replaceWithEl = document.getElementById('arg-replace-with');
        args.push(patternEl ? patternEl.value : '');
        args.push(replaceWithEl ? replaceWithEl.value : '');
    } else if (funcName === 'default') {
        const fallbackEl = document.getElementById('arg-fallback');
        args.push(fallbackEl ? fallbackEl.value : '');
    } else if (funcName === 'date_format') {
        const inEl = document.getElementById('arg-in-fmt');
        const outEl = document.getElementById('arg-out-fmt');
        args.push(inEl ? inEl.value : '');
        args.push(outEl ? outEl.value : '');
    } else if (funcName === 'contains') {
        const searchStrEl = document.getElementById('arg-search-str');
        const matchValEl = document.getElementById('arg-match-val');
        const otherwiseValEl = document.getElementById('arg-otherwise-val');
        args.push(searchStrEl ? searchStrEl.value : '');
        args.push(matchValEl ? matchValEl.value : '');
        args.push(otherwiseValEl ? otherwiseValEl.value : '');
    }
    
    // Run simulation
    let outputVal = '';
    let displayInput = '';
    
    if (funcName === 'concat') {
        displayInput = `Multiple Fields`;
    } else {
        displayInput = rawInputVal !== null && rawInputVal !== undefined ? String(rawInputVal) : '[Empty]';
    }
    
    try {
        outputVal = runSimulatedTransform(funcName, args, rawInputVal, sampleRow, state);
    } catch (e) {
        outputVal = '[Simulation Error]';
    }
    
    inputSpan.textContent = displayInput;
    inputSpan.title = displayInput;
    outputSpan.textContent = outputVal !== '' ? outputVal : '[Empty]';
    outputSpan.title = outputVal;
    
    previewCard.classList.remove('d-none');
}

/**
 * JS implementation of transform algorithms for modal simulation
 */
function runSimulatedTransform(funcName, args, rawInputVal, sampleRow, state) {
    let val = rawInputVal !== null && rawInputVal !== undefined ? String(rawInputVal) : '';
    if (!funcName) return val;
    
    switch (funcName) {
        case 'upper':
            return val.toUpperCase();
        case 'lower':
            return val.toLowerCase();
        case 'strip':
            return val.trim();
        case 'title_case':
            return val.replace(/\w\S*/g, txt => txt.charAt(0).toUpperCase() + txt.slice(1).toLowerCase());
        case 'default':
            return (!val || val.trim() === '') ? (args[0] || '') : val;
        case 'replace':
            return val.replaceAll(args[0] || '', args[1] || '');
        case 'regex_replace':
            try {
                const pat = args[0] || '';
                const rep = args[1] || '';
                if (!pat) return val;
                const rx = new RegExp(pat, 'g');
                return val.replace(rx, rep);
            } catch (e) {
                return val;
            }
        case 'url_encode':
            return encodeURIComponent(val);
        case 'url_decode':
            try {
                return decodeURIComponent(val);
            } catch (e) {
                return val;
            }
        case 'contains':
            const search = args[0] || '';
            const matchVal = args[1] || '';
            const otherwiseVal = args[2] || '';
            return val.includes(search) ? matchVal : otherwiseVal;
        case 'substring':
            const start = parseInt(args[0]) || 0;
            const end = args[1] ? parseInt(args[1]) : undefined;
            return val.slice(start, end);
        case 'tokenize':
            const delim = args[0] || ',';
            const idx = parseInt(args[1]) || 0;
            const tokens = val.split(delim);
            return tokens[idx] || '';
        case 'date_format':
            // Simple mockup formatting simulation in JS
            return val;
        case 'concat':
            const sep = args[0] || '';
            const parts = [];
            for (let i = 1; i < args.length; i++) {
                const arg = args[i];
                if (arg && arg.startsWith('$')) {
                    const colName = arg.slice(1);
                    const idx2 = state.excelHeaders ? state.excelHeaders.indexOf(colName) : -1;
                    const key2 = idx2 !== -1 ? `col_${idx2}` : null;
                    const cVal = (sampleRow && key2) ? sampleRow[key2] : '';
                    parts.push(cVal !== null && cVal !== undefined ? String(cVal) : '');
                } else if (arg) {
                    parts.push(arg);
                }
            }
            return parts.join(sep);
        default:
            return val;
    }
}
