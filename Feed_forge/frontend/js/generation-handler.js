/**
 * XML Generation Step Workflow Handler
 */

export function initGenerationStep(state) {
    const generateBtn = document.getElementById('btn-generate-xml');
    const downloadBtn = document.getElementById('btn-download-xml');
    const ftpModalBtn = document.getElementById('btn-ftp-upload-modal');
    const previewContainer = document.getElementById('xml-preview-container');
    const linesCountBadge = document.getElementById('preview-lines-count');
    
    let generatedFilename = null;
    let ftpModal = null;
    
    // Initialize Bootstrap Modal
    const modalEl = document.getElementById('ftpUploadModal');
    if (modalEl) {
        ftpModal = new bootstrap.Modal(modalEl);
    }
    
    // Dynamic Port auto-switching based on protocol choice
    const protocolSelect = document.getElementById('ftp-protocol-select');
    const portInput = document.getElementById('ftp-port-input');
    
    if (protocolSelect && portInput) {
        protocolSelect.addEventListener('change', () => {
            const proto = protocolSelect.value;
            portInput.value = proto === 'sftp' ? '22' : '21';
        });
    }
    
    // Compile XML click handler
    generateBtn.addEventListener('click', async () => {
        if (!state.template) {
            alert('Please load an XML template first (Step 2).');
            return;
        }
        
        if (state.sourceType === 'excel') {
            if (!state.filename || !state.selectedSheet) {
                alert('Missing Excel configuration. Load spreadsheet and select worksheet (Step 1).');
                return;
            }
        } else if (state.sourceType === 'xml_file') {
            if (!state.filename) {
                alert('Missing XML file. Upload a source XML file (Step 1).');
                return;
            }
        } else if (state.sourceType === 'xml_url') {
            if (!state.sourceConfig || !state.sourceConfig.url) {
                alert('Missing XML URL. Enter and fetch a remote XML feed (Step 1).');
                return;
            }
        }
        
        try {
            generateBtn.disabled = true;
            generateBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>Compiling...`;
            downloadBtn.disabled = true;
            ftpModalBtn.disabled = true;
            
            previewContainer.textContent = 'Generating XML feed... Please wait...';
            linesCountBadge.textContent = 'Generating...';
            linesCountBadge.className = 'badge bg-warning text-dark border';
            
            const response = await fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: state.filename,
                    sheet: state.selectedSheet,
                    template: state.template,
                    mapping: state.mapping,
                    static_fields: state.staticFields,
                    campaign_custom_fields: state.campaignCustomFields || [],
                    awm_config: state.awmConfig || { enabled: false, fields: {} },
                    salary_config: state.salaryConfig || { enabled: false, fields: {} },
                    headers_config: state.headersConfig || {},
                    disabled_fields: state.disabledFields || [],
                    source_type: state.sourceType || 'excel',
                    source_config: state.sourceConfig || {},
                    transforms: state.transforms || []
                })
            });
            
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || 'Failed to compile XML');
            }
            
            const data = await response.json();
            
            // Render XML preview
            previewContainer.textContent = data.preview;
            
            // Save output filename for download / upload
            generatedFilename = data.output_file;
            
            // Enable download/upload actions
            downloadBtn.removeAttribute('disabled');
            ftpModalBtn.removeAttribute('disabled');
            
            // Update line counts badge
            linesCountBadge.textContent = `${data.line_count} lines compiled`;
            linesCountBadge.className = 'badge bg-success text-white border';
            
        } catch (err) {
            console.error(err);
            previewContainer.textContent = `<!-- Generation Failed -->\n\nError details:\n${err.message}`;
            linesCountBadge.textContent = 'Failed';
            linesCountBadge.className = 'badge bg-danger text-white border';
            alert(`XML Compilation Error: ${err.message}`);
        } finally {
            generateBtn.disabled = false;
            generateBtn.innerHTML = `<i class="bi bi-gear-wide-connected me-2 text-white"></i>Compile XML`;
        }
    });
    
    // Download XML click handler
    downloadBtn.addEventListener('click', () => {
        if (generatedFilename) {
            window.location.href = `/api/download?file=${encodeURIComponent(generatedFilename)}`;
        } else {
            alert('No compiled file available for download. Click Compile XML first.');
        }
    });
    
    // Open FTP Modal handler
    ftpModalBtn.addEventListener('click', () => {
        if (!generatedFilename) {
            alert('Please compile the XML first.');
            return;
        }
        
        // Pre-fill FTP settings from state (saved in workspace)
        const ftpConfig = state.ftpConfig || {};
        if (ftpConfig.host) document.getElementById('ftp-host-input').value = ftpConfig.host;
        if (ftpConfig.protocol) {
            document.getElementById('ftp-protocol-select').value = ftpConfig.protocol;
            document.getElementById('ftp-port-input').value = ftpConfig.port || (ftpConfig.protocol === 'sftp' ? '22' : '21');
        }
        if (ftpConfig.username) document.getElementById('ftp-user-input').value = ftpConfig.username;
        if (ftpConfig.remote_dir) document.getElementById('ftp-dir-input').value = ftpConfig.remote_dir;
        
        // Pre-fill remote filename rename field with current filename or previously stored rename value
        const renameInput = document.getElementById('ftp-rename-input');
        renameInput.value = ftpConfig.remote_filename || generatedFilename;
        
        ftpModal.show();
    });
    
    // FTP Confirm Upload action
    const confirmUploadBtn = document.getElementById('btn-confirm-ftp-upload');
    confirmUploadBtn.addEventListener('click', async () => {
        const host = document.getElementById('ftp-host-input').value.trim();
        const port = document.getElementById('ftp-port-input').value.trim();
        const username = document.getElementById('ftp-user-input').value.trim();
        const password = document.getElementById('ftp-pass-input').value;
        const protocol = document.getElementById('ftp-protocol-select').value;
        const remoteDir = document.getElementById('ftp-dir-input').value.trim();
        const remoteFilename = document.getElementById('ftp-rename-input').value.trim();
        
        if (!host || !username || !password) {
            alert('Please specify the host address, username, and password.');
            return;
        }
        
        try {
            confirmUploadBtn.disabled = true;
            confirmUploadBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>Uploading...`;
            
            const response = await fetch('/api/generate/upload-ftp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: generatedFilename,
                    protocol: protocol,
                    host: host,
                    port: port ? parseInt(port) : null,
                    username: username,
                    password: password,
                    remote_dir: remoteDir,
                    remote_filename: remoteFilename
                })
            });
            
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || 'FTP upload failed');
            }
            
            const resData = await response.json();
            
            // Save non-sensitive FTP details in local state for workspace serialization
            state.ftpConfig = {
                host: host,
                protocol: protocol,
                port: port,
                username: username,
                remote_dir: remoteDir,
                remote_filename: remoteFilename
            };
            
            ftpModal.hide();
            // Clear password field for security
            document.getElementById('ftp-pass-input').value = '';
            
            alert(resData.message || 'File uploaded successfully!');
            
        } catch (err) {
            console.error(err);
            alert(`File Transfer Error: ${err.message}`);
        } finally {
            confirmUploadBtn.disabled = false;
            confirmUploadBtn.innerHTML = `<i class="bi bi-cloud-arrow-up-fill me-1"></i>Start Upload`;
        }
    });
}
