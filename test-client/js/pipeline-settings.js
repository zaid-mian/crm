document.addEventListener('DOMContentLoaded', () => {
    // --- UI Elements ---
    const logList = document.getElementById('logList');
    const detailViewer = document.getElementById('requestDetailViewer');
    
    const pipelineSelector = document.getElementById('pipelineSelector');
    const createPipelineBtn = document.getElementById('createPipelineBtn');
    const renamePipelineBtn = document.getElementById('renamePipelineBtn');
    const deletePipelineBtn = document.getElementById('deletePipelineBtn');
    
    const stagesTableBody = document.getElementById('stagesTableBody');
    const addStageBtn = document.getElementById('addStageBtn');
    
    const stageDrawerEl = document.getElementById('stageDrawer');
    const stageDrawerTitle = document.getElementById('stageDrawerTitle');
    const stageForm = document.getElementById('stageForm');
    const stageIdInput = document.getElementById('stageId');
    const stageNameInput = document.getElementById('stageNameInput');
    const stageOrderInput = document.getElementById('stageOrderInput');
    const stageColorPicker = document.getElementById('stageColorPicker');
    const stageColorInput = document.getElementById('stageColorInput');
    const saveStageBtn = document.getElementById('saveStageBtn');
    
    const bsStageDrawer = new bootstrap.Offcanvas(stageDrawerEl);
    
    const reassignModalEl = document.getElementById('reassignModal');
    const reassignSelector = document.getElementById('reassignSelector');
    const confirmReassignDeleteBtn = document.getElementById('confirmReassignDeleteBtn');
    const bsReassignModal = new bootstrap.Modal(reassignModalEl);
    
    // --- Setup Wizard UI Elements ---
    const openWizardBtn = document.getElementById('openWizardBtn');
    const wizardModalEl = document.getElementById('wizardModal');
    const bsWizardModal = new bootstrap.Modal(wizardModalEl);
    
    const wizardBackBtn = document.getElementById('wizardBackBtn');
    const wizardNextBtn = document.getElementById('wizardNextBtn');
    const wizardSaveBtn = document.getElementById('wizardSaveBtn');
    
    let activePipelineId = null;
    let deletingStageId = null;
    
    let wizardStages = [];
    let wizardConversionStageIdx = null;
    let wizardWonStageIdx = null;
    let wizardLostStageIdx = null;
    let wizardEnableForm = true;
    let wizardFormFields = [];
    let currentStep = 1;
    let originalStages = [];

    // Sync color inputs
    if (stageColorPicker && stageColorInput) {
        stageColorPicker.addEventListener('input', () => {
            stageColorInput.value = stageColorPicker.value;
        });
        stageColorInput.addEventListener('input', () => {
            if (/^#[0-9A-F]{6}$/i.test(stageColorInput.value)) {
                stageColorPicker.value = stageColorInput.value;
            }
        });
    }

    // --- Developer Log Panel Listener ---
    window.addEventListener('crm-api-log', (event) => {
        const log = event.detail;
        const item = document.createElement('div');
        const statusClass = log.status >= 200 && log.status < 300 ? 'bg-success-subtle text-success' : 'bg-danger-subtle text-danger';
        item.className = `log-item list-group-item list-group-item-action p-2 method-${log.method.toLowerCase()} d-flex justify-content-between align-items-center`;
        item.innerHTML = `
            <div>
                <span class="text-muted font-monospace">[${log.timestamp}]</span>
                <strong class="font-monospace ms-1">${log.method}</strong>
                <span class="text-truncate ms-2 font-monospace" style="max-width: 140px; display: inline-block;">
                    ${log.url.replace(localStorage.getItem('api_base_url'), '')}
                </span>
            </div>
            <div class="d-flex align-items-center">
                <span class="badge ${statusClass} me-2">${log.status}</span>
                <small class="text-muted font-monospace">${log.duration}ms</small>
            </div>
        `;

        item.addEventListener('click', () => {
            renderRequestDetails(log);
            document.querySelectorAll('.log-item').forEach(el => el.classList.remove('active'));
            item.classList.add('active');
        });

        if (logList && logList.querySelector('.text-center')) {
            logList.innerHTML = '';
        }
        if (logList) {
            logList.insertBefore(item, logList.firstChild);
            while (logList.children.length > 50) {
                logList.removeChild(logList.lastChild);
            }
        }

        renderRequestDetails(log);
        item.classList.add('active');
    });

    function renderRequestDetails(log) {
        if (!detailViewer) return;
        detailViewer.innerHTML = `
            <div class="mb-2">
                <strong class="small text-muted text-uppercase">Request Endpoint:</strong>
                <div class="font-monospace text-dark bg-light p-2 rounded small border">${log.method} ${log.url}</div>
            </div>
            <div class="row mb-2">
                <div class="col">
                    <strong class="small text-muted text-uppercase">Latency:</strong>
                    <div class="font-monospace small">${log.duration} ms</div>
                </div>
                <div class="col">
                    <strong class="small text-muted text-uppercase">HTTP Status:</strong>
                    <div class="font-monospace small font-weight-bold ${log.status >= 200 && log.status < 300 ? 'text-success' : 'text-danger'}">${log.status}</div>
                </div>
            </div>
            <div class="mb-2">
                <strong class="small text-muted text-uppercase">Request Payload:</strong>
                <pre class="json-viewer p-2">${log.requestBody ? UIUtils.syntaxHighlightJson(log.requestBody) : '<em>No payload body</em>'}</pre>
            </div>
            <div class="mb-2">
                <strong class="small text-muted text-uppercase">Response Envelope:</strong>
                <pre class="json-viewer p-2">${UIUtils.syntaxHighlightJson(log.responseBody)}</pre>
            </div>
        `;
    }

    // --- Load Pipelines list ---
    async function loadPipelines(selectedId = null) {
        try {
            console.log("Calling GET /api/pipelines/ in settings...");
            const response = await APIClient.get('/api/pipelines/');
            console.log("Response received in settings:", response);
            
            // Normalize wrapped/unwrapped response format
            let pipelines = [];
            if (Array.isArray(response)) {
                pipelines = response;
            } else if (response && response.hasOwnProperty('success')) {
                pipelines = response.data || [];
            } else if (response && response.results) {
                pipelines = response.results;
            } else {
                console.error("Unknown pipelines response in settings:", response);
                pipelines = [];
            }

            if (pipelineSelector) {
                pipelineSelector.innerHTML = '';
                if (pipelines.length === 0) {
                    pipelineSelector.innerHTML = '<option value="">No pipelines configured</option>';
                    if (stagesTableBody) {
                        stagesTableBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">Please create a pipeline first.</td></tr>';
                    }
                    activePipelineId = null;
                    return;
                }

                pipelines.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p.id;
                    opt.textContent = p.name;
                    pipelineSelector.appendChild(opt);
                });

                if (selectedId && pipelines.find(p => p.id === parseInt(selectedId))) {
                    pipelineSelector.value = selectedId;
                } else {
                    pipelineSelector.value = pipelines[0].id;
                }

                activePipelineId = parseInt(pipelineSelector.value);
                await loadStages(activePipelineId);
            }
        } catch (e) {
            console.error("Failed to load pipelines in settings:", e);
            UIUtils.showAlert('mainAlertContainer', e.message || 'Failed to load pipelines.', 'danger');
        }
    }

    if (pipelineSelector) {
        pipelineSelector.addEventListener('change', () => {
            activePipelineId = parseInt(pipelineSelector.value);
            loadStages(activePipelineId);
        });
    }

    // --- Load Stages of Active Pipeline ---
    async function loadStages(pipelineId) {
        if (!pipelineId) return;
        if (stagesTableBody) {
            stagesTableBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted"><div class="spinner-border spinner-border-sm text-primary me-2" role="status"></div>Loading stages...</td></tr>';
        }
        
        try {
            console.log(`Calling GET /api/pipeline/stages/?pipeline=${pipelineId} in settings...`);
            const response = await APIClient.get(`/api/pipeline/stages/?pipeline=${pipelineId}`);
            console.log("Response received from stages list:", response);
            
            // Normalize wrapped/unwrapped stages response
            let stages = [];
            if (Array.isArray(response)) {
                stages = response;
            } else if (response && response.hasOwnProperty('success')) {
                stages = response.data || [];
            } else if (response && response.results) {
                stages = response.results;
            } else {
                console.error("Unknown stages response format in settings:", response);
                stages = [];
            }
            
            stages.sort((a, b) => a.order - b.order);

            if (stagesTableBody) {
                if (stages.length === 0) {
                    stagesTableBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">No stages configured in this pipeline. Click Add New Stage to begin.</td></tr>';
                    return;
                }

                stagesTableBody.innerHTML = '';
                
                function getBehaviorLabel(stage_type) {
                    const mapping = {
                        'NORMAL_LEAD': 'Lead Stage',
                        'CONVERSION': 'Conversion Stage',
                        'NORMAL_OPPORTUNITY': 'Opportunity Stage',
                        'WON': 'Won Stage',
                        'LOST': 'Lost Stage'
                    };
                    return mapping[stage_type] || stage_type;
                }

                stages.forEach(stage => {
                    const tr = document.createElement('tr');
                    tr.className = 'stage-row';
                    tr.innerHTML = `
                        <td class="font-monospace fw-bold">${stage.order}</td>
                        <td class="fw-semibold">${stage.name}</td>
                        <td><span class="badge bg-info bg-opacity-10 text-info">${getBehaviorLabel(stage.stage_type)}</span></td>
                        <td>
                            <span class="color-preview" style="background-color: ${stage.color || '#6c757d'};"></span>
                            <span class="small font-monospace ms-2 text-muted">${stage.color || '#6c757d'}</span>
                        </td>
                        <td class="text-end">
                            <button class="btn btn-sm btn-outline-primary edit-btn" data-id="${stage.id}">Edit</button>
                            <button class="btn btn-sm btn-outline-danger delete-btn" data-id="${stage.id}">Delete</button>
                        </td>
                    `;
                    stagesTableBody.appendChild(tr);
                });

                // Attach button events
                document.querySelectorAll('.edit-btn').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const id = parseInt(btn.dataset.id);
                        const s = stages.find(x => x.id === id);
                        openStageDrawer(s);
                    });
                });

                document.querySelectorAll('.delete-btn').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const id = parseInt(btn.dataset.id);
                        handleDeleteStage(id);
                    });
                });
            }
        } catch (e) {
            console.error("Failed to load stages in settings:", e);
            if (stagesTableBody) {
                stagesTableBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-danger">Failed to load stages config.</td></tr>';
            }
        }
    }

    // --- Pipeline Actions (Create, Rename, Delete) ---
    if (createPipelineBtn) {
        createPipelineBtn.addEventListener('click', async () => {
            const name = prompt("Enter new pipeline name:");
            if (!name || !name.trim()) return;

            try {
                const res = await APIClient.post('/api/pipelines/', { name: name.trim() });
                if (res) {
                    const newId = res.id || (res.data && res.data.id);
                    UIUtils.showAlert('mainAlertContainer', 'Pipeline created successfully.');
                    await loadPipelines(newId);
                }
            } catch (e) {
                UIUtils.showAlert('mainAlertContainer', e.message || 'Failed to create pipeline.', 'danger');
            }
        });
    }

    if (renamePipelineBtn) {
        renamePipelineBtn.addEventListener('click', async () => {
            if (!activePipelineId) return;
            const currentName = pipelineSelector.options[pipelineSelector.selectedIndex].text;
            const name = prompt("Rename pipeline to:", currentName);
            if (!name || !name.trim() || name.trim() === currentName) return;

            try {
                const res = await APIClient.patch(`/api/pipelines/${activePipelineId}/`, { name: name.trim() });
                if (res) {
                    const newId = res.id || (res.data && res.data.id);
                    UIUtils.showAlert('mainAlertContainer', 'Pipeline renamed successfully.');
                    await loadPipelines(newId);
                }
            } catch (e) {
                UIUtils.showAlert('mainAlertContainer', e.message || 'Failed to rename pipeline.', 'danger');
            }
        });
    }

    if (deletePipelineBtn) {
        deletePipelineBtn.addEventListener('click', async () => {
            if (!activePipelineId) return;
            const currentName = pipelineSelector.options[pipelineSelector.selectedIndex].text;
            if (!confirm(`Are you absolutely sure you want to delete pipeline "${currentName}"?`)) return;

            try {
                await APIClient.delete(`/api/pipelines/${activePipelineId}/`);
                UIUtils.showAlert('mainAlertContainer', 'Pipeline deleted successfully.');
                await loadPipelines();
            } catch (e) {
                UIUtils.showAlert('mainAlertContainer', e.message || 'Failed to delete pipeline.', 'danger');
            }
        });
    }

    // --- Stage CRUD Actions ---
    function openStageDrawer(stage = null) {
        if (stage) {
            stageDrawerTitle.textContent = "Edit Stage Settings";
            stageIdInput.value = stage.id;
            stageNameInput.value = stage.name;
            stageOrderInput.value = stage.order;
            stageColorInput.value = stage.color || "#6c757d";
            stageColorPicker.value = stage.color || "#6c757d";
        } else {
            stageDrawerTitle.textContent = "Create Stage Settings";
            stageIdInput.value = "";
            stageNameInput.value = "";
            stageOrderInput.value = "0";
            stageColorInput.value = "#6c757d";
            stageColorPicker.value = "#6c757d";
        }
        bsStageDrawer.show();
    }

    if (addStageBtn) {
        addStageBtn.addEventListener('click', () => openStageDrawer());
    }

    if (stageForm) {
        stageForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            saveStageBtn.disabled = true;
            saveStageBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Saving...';

            const id = stageIdInput.value;
            const payload = {
                pipeline: activePipelineId,
                name: stageNameInput.value.trim(),
                order: parseInt(stageOrderInput.value),
                color: stageColorInput.value
            };

            try {
                let res;
                if (id) {
                    res = await APIClient.patch(`/api/pipeline/stages/${id}/`, payload);
                } else {
                    res = await APIClient.post('/api/pipeline/stages/', payload);
                }

                if (res) {
                    UIUtils.showAlert('mainAlertContainer', 'Stage configuration saved successfully.');
                    bsStageDrawer.hide();
                    await loadStages(activePipelineId);
                }
            } catch (err) {
                UIUtils.showAlert('mainAlertContainer', err.message || 'Error occurred while saving stage.', 'danger');
            } finally {
                saveStageBtn.disabled = false;
                saveStageBtn.textContent = 'Save Stage';
            }
        });
    }

    // --- Deletion Flow with Reassignment logic ---
    async function handleDeleteStage(stageId) {
        deletingStageId = stageId;
        
        try {
            // First check if deletion succeeds or demands reassignment (via DELETE attempt)
            const checkRes = await APIClient.delete(`/api/pipeline/stages/${stageId}/`);
            if (checkRes) {
                UIUtils.showAlert('mainAlertContainer', 'Stage deleted successfully.');
                await loadStages(activePipelineId);
            }
        } catch (e) {
            // Check if backend returned active cards deletion error
            if (e.message && e.message.includes("Please provide a reassign_stage_id")) {
                // Populate reassignment options
                const stageListRes = await APIClient.get(`/api/pipeline/stages/?pipeline=${activePipelineId}`);
                let stages = [];
                if (Array.isArray(stageListRes)) {
                    stages = stageListRes;
                } else if (stageListRes && stageListRes.hasOwnProperty('success')) {
                    stages = stageListRes.data || [];
                } else if (stageListRes && stageListRes.results) {
                    stages = stageListRes.results;
                }
                
                if (reassignSelector) {
                    reassignSelector.innerHTML = '<option value="">Choose a stage...</option>';
                    const filteredStages = stages.filter(s => s.id !== stageId);
                    
                    filteredStages.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s.id;
                        opt.textContent = `${s.name} (${s.entity_type})`;
                        reassignSelector.appendChild(opt);
                    });
                    
                    bsReassignModal.show();
                }
            } else {
                UIUtils.showAlert('mainAlertContainer', e.message || 'Failed to delete stage.', 'danger');
            }
        }
    }

    if (confirmReassignDeleteBtn) {
        confirmReassignDeleteBtn.addEventListener('click', async () => {
            const reassignId = reassignSelector.value;
            if (!reassignId) {
                alert('Please select a reassignment target stage.');
                return;
            }

            confirmReassignDeleteBtn.disabled = true;
            
            try {
                const res = await APIClient.delete(`/api/pipeline/stages/${deletingStageId}/`, {
                    reassign_stage_id: parseInt(reassignId)
                });
                if (res) {
                    UIUtils.showAlert('mainAlertContainer', 'Cards successfully reassigned and stage deleted.');
                    bsReassignModal.hide();
                    await loadStages(activePipelineId);
                }
            } catch (e) {
                alert(e.message || 'Failed to reassign cards and delete stage.');
            } finally {
                confirmReassignDeleteBtn.disabled = false;
            }
        });
    }

    // ==========================================
    // --- Guided Setup Wizard & Form Builder ---
    // ==========================================

    function renderWizardStages() {
        const list = document.getElementById('wizardStagesList');
        if (!list) return;
        list.innerHTML = '';
        wizardStages.forEach((stage, index) => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex align-items-center gap-2 py-2 bg-light border-secondary border-opacity-10';
            item.innerHTML = `
                <span class="badge bg-secondary font-monospace" style="width: 25px;">${index + 1}</span>
                <input type="text" class="form-control form-control-sm wizard-stage-name-input" data-index="${index}" value="${stage.name}" placeholder="Stage Name">
                <input type="color" class="form-control form-control-color border-0 wizard-stage-color-input" data-index="${index}" value="${stage.color || '#6c757d'}" style="width: 32px; height: 32px; padding: 0;">
                <button class="btn btn-sm btn-outline-secondary wizard-stage-up-btn" data-index="${index}" ${index === 0 ? 'disabled' : ''}>&uarr;</button>
                <button class="btn btn-sm btn-outline-secondary wizard-stage-down-btn" data-index="${index}" ${index === wizardStages.length - 1 ? 'disabled' : ''}>&darr;</button>
                <button class="btn btn-sm btn-outline-danger wizard-stage-delete-btn" data-index="${index}">&times;</button>
            `;
            list.appendChild(item);
        });

        // Sync inputs on text changes
        list.querySelectorAll('.wizard-stage-name-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.index);
                wizardStages[idx].name = e.target.value.trim();
            });
        });
        list.querySelectorAll('.wizard-stage-color-input').forEach(input => {
            input.addEventListener('input', (e) => {
                const idx = parseInt(e.target.dataset.index);
                wizardStages[idx].color = e.target.value;
            });
        });

        // Up/Down reordering action binds
        list.querySelectorAll('.wizard-stage-up-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.index);
                if (idx > 0) {
                    const temp = wizardStages[idx];
                    wizardStages[idx] = wizardStages[idx - 1];
                    wizardStages[idx - 1] = temp;
                    
                    // Adjust selections if indexes shift
                    if (wizardConversionStageIdx === idx) wizardConversionStageIdx = idx - 1;
                    else if (wizardConversionStageIdx === idx - 1) wizardConversionStageIdx = idx;

                    if (wizardWonStageIdx === idx) wizardWonStageIdx = idx - 1;
                    else if (wizardWonStageIdx === idx - 1) wizardWonStageIdx = idx;

                    if (wizardLostStageIdx === idx) wizardLostStageIdx = idx - 1;
                    else if (wizardLostStageIdx === idx - 1) wizardLostStageIdx = idx;

                    renderWizardStages();
                }
            });
        });
        list.querySelectorAll('.wizard-stage-down-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.index);
                if (idx < wizardStages.length - 1) {
                    const temp = wizardStages[idx];
                    wizardStages[idx] = wizardStages[idx + 1];
                    wizardStages[idx + 1] = temp;

                    // Adjust selections if indexes shift
                    if (wizardConversionStageIdx === idx) wizardConversionStageIdx = idx + 1;
                    else if (wizardConversionStageIdx === idx + 1) wizardConversionStageIdx = idx;

                    if (wizardWonStageIdx === idx) wizardWonStageIdx = idx + 1;
                    else if (wizardWonStageIdx === idx + 1) wizardWonStageIdx = idx;

                    if (wizardLostStageIdx === idx) wizardLostStageIdx = idx + 1;
                    else if (wizardLostStageIdx === idx + 1) wizardLostStageIdx = idx;

                    renderWizardStages();
                }
            });
        });
        list.querySelectorAll('.wizard-stage-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.index);
                wizardStages.splice(idx, 1);
                
                // Adjust index selections
                if (wizardConversionStageIdx === idx) wizardConversionStageIdx = null;
                else if (wizardConversionStageIdx > idx) wizardConversionStageIdx--;

                if (wizardWonStageIdx === idx) wizardWonStageIdx = null;
                else if (wizardWonStageIdx > idx) wizardWonStageIdx--;

                if (wizardLostStageIdx === idx) wizardLostStageIdx = null;
                else if (wizardLostStageIdx > idx) wizardLostStageIdx--;

                renderWizardStages();
            });
        });
    }

    const addWizardStageBtn = document.getElementById('addWizardStageBtn');
    const newWizardStageName = document.getElementById('newWizardStageName');
    const newWizardStageColor = document.getElementById('newWizardStageColor');

    if (addWizardStageBtn && newWizardStageName && newWizardStageColor) {
        addWizardStageBtn.addEventListener('click', () => {
            const name = newWizardStageName.value.trim();
            if (!name) {
                alert("Stage Name is required.");
                return;
            }
            const color = newWizardStageColor.value;

            wizardStages.push({
                id: null,
                name: name,
                color: color,
                order: wizardStages.length
            });

            newWizardStageName.value = '';
            renderWizardStages();
        });
    }

    function populateStep2Dropdown() {
        const select = document.getElementById('wizardConversionStageSelect');
        if (!select) return;
        select.innerHTML = '<option value="">Choose conversion stage...</option>';
        wizardStages.forEach((stage, idx) => {
            const opt = document.createElement('option');
            opt.value = idx;
            opt.textContent = `${stage.name} (Position: ${idx + 1})`;
            select.appendChild(opt);
        });

        if (wizardConversionStageIdx !== null && wizardConversionStageIdx < wizardStages.length) {
            select.value = wizardConversionStageIdx;
        }
    }

    function populateStep3Dropdowns() {
        const wonSelect = document.getElementById('wizardWonStageSelect');
        const lostSelect = document.getElementById('wizardLostStageSelect');
        if (!wonSelect || !lostSelect) return;

        wonSelect.innerHTML = '<option value="">Choose Won stage...</option>';
        lostSelect.innerHTML = '<option value="">Choose Lost stage...</option>';

        const startIdx = wizardConversionStageIdx !== null ? parseInt(wizardConversionStageIdx) : 0;
        const opportunityStages = wizardStages.slice(startIdx);

        opportunityStages.forEach((stage) => {
            const originalIdx = wizardStages.indexOf(stage);

            const optWon = document.createElement('option');
            optWon.value = originalIdx;
            optWon.textContent = `${stage.name} (Position: ${originalIdx + 1})`;
            wonSelect.appendChild(optWon);

            const optLost = document.createElement('option');
            optLost.value = originalIdx;
            optLost.textContent = `${stage.name} (Position: ${originalIdx + 1})`;
            lostSelect.appendChild(optLost);
        });

        if (wizardWonStageIdx !== null && wizardWonStageIdx < wizardStages.length && wizardWonStageIdx >= startIdx) {
            wonSelect.value = wizardWonStageIdx;
        } else {
            wonSelect.value = "";
            wizardWonStageIdx = null;
        }

        if (wizardLostStageIdx !== null && wizardLostStageIdx < wizardStages.length && wizardLostStageIdx >= startIdx) {
            lostSelect.value = wizardLostStageIdx;
        } else {
            lostSelect.value = "";
            wizardLostStageIdx = null;
        }
    }

    function renderWizardFormFields() {
        const tbody = document.getElementById('wizardFormFieldsTableBody');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (wizardFormFields.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-muted">No custom fields defined yet. Add fields below to build your conversion form.</td></tr>';
            return;
        }
        wizardFormFields.forEach((field, index) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="fw-semibold small">${field.label}</td>
                <td class="small font-monospace">${field.field_type}</td>
                <td class="small">${field.required ? '<span class="badge bg-danger">Required</span>' : '<span class="badge bg-secondary">Optional</span>'}</td>
                <td class="small text-muted text-truncate" style="max-width: 150px;">${field.options && field.options.length ? field.options.join(', ') : '-'}</td>
                <td class="text-center">
                    <button class="btn btn-sm btn-outline-danger py-0 px-1 remove-field-btn" data-index="${index}">&times;</button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll('.remove-field-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.index);
                wizardFormFields.splice(idx, 1);
                renderWizardFormFields();
            });
        });
    }

    const addFormFieldBtn = document.getElementById('addFormFieldBtn');
    const newFieldLabel = document.getElementById('newFieldLabel');
    const newFieldType = document.getElementById('newFieldType');
    const newFieldOptions = document.getElementById('newFieldOptions');
    const newFieldOptionsWrapper = document.getElementById('newFieldOptionsWrapper');
    const newFieldRequired = document.getElementById('newFieldRequired');

    if (newFieldType && newFieldOptionsWrapper) {
        newFieldType.addEventListener('change', () => {
            if (newFieldType.value === 'DROPDOWN') {
                newFieldOptionsWrapper.classList.remove('d-none');
            } else {
                newFieldOptionsWrapper.classList.add('d-none');
            }
        });
    }

    if (addFormFieldBtn) {
        addFormFieldBtn.addEventListener('click', () => {
            const label = newFieldLabel.value.trim();
            if (!label) {
                alert("Field Label Name is required.");
                return;
            }
            const type = newFieldType.value;
            let opts = [];
            if (type === 'DROPDOWN') {
                opts = newFieldOptions.value.split(',').map(x => x.trim()).filter(x => x !== '');
                if (opts.length === 0) {
                    alert("Dropdown field must have at least one option.");
                    return;
                }
            }
            const req = newFieldRequired.checked;

            wizardFormFields.push({
                id: null,
                label: label,
                field_type: type,
                required: req,
                options: opts,
                order: wizardFormFields.length
            });

            newFieldLabel.value = '';
            newFieldOptions.value = '';
            newFieldRequired.checked = false;
            newFieldType.value = 'TEXT';
            newFieldOptionsWrapper.classList.add('d-none');

            renderWizardFormFields();
        });
    }

    function showStep(step) {
        currentStep = step;
        for (let s = 1; s <= 5; s++) {
            const panel = document.getElementById(`stepPanel${s}`);
            if (panel) {
                if (s === step) {
                    panel.classList.remove('d-none');
                } else {
                    panel.classList.add('d-none');
                }
            }
        }

        document.querySelectorAll('.stepper-item').forEach(item => {
            const s = parseInt(item.dataset.step);
            item.classList.remove('active', 'completed');
            if (s === step) {
                item.classList.add('active');
            } else if (s < step) {
                item.classList.add('completed');
            }
        });

        const progressLine = document.getElementById('wizardProgressLine');
        if (progressLine) {
            progressLine.style.width = `${(step - 1) * 25}%`;
        }

        const backBtn = document.getElementById('wizardBackBtn');
        const nextBtn = document.getElementById('wizardNextBtn');
        const saveBtn = document.getElementById('wizardSaveBtn');

        if (backBtn) backBtn.disabled = (step === 1);
        
        if (step === 5) {
            if (nextBtn) nextBtn.classList.add('d-none');
            if (saveBtn) saveBtn.classList.remove('d-none');
            renderReviewSummary();
        } else {
            if (nextBtn) nextBtn.classList.remove('d-none');
            if (saveBtn) saveBtn.classList.add('d-none');
        }

        const saveLogs = document.getElementById('wizardSaveLogs');
        if (saveLogs) saveLogs.classList.add('d-none');
    }

    function validateWizardConfig() {
        if (wizardStages.length < 2) {
            return "The pipeline must have at least 2 stages.";
        }
        if (wizardConversionStageIdx === null || wizardConversionStageIdx === '') {
            return "Please select a conversion stage.";
        }
        const convIdx = parseInt(wizardConversionStageIdx);
        if (convIdx === 0) {
            return "The conversion stage cannot be the first stage. There must be at least one Lead stage.";
        }

        const hasWon = document.querySelector('input[name="hasWonRadio"]:checked').value === 'yes';
        if (hasWon) {
            if (wizardWonStageIdx === null || wizardWonStageIdx === '') {
                return "Please select a Won stage.";
            }
            const wonIdx = parseInt(wizardWonStageIdx);
            if (wonIdx < convIdx) {
                return "The Won stage cannot be before the Conversion stage.";
            }
        }

        const hasLost = document.querySelector('input[name="hasLostRadio"]:checked').value === 'yes';
        if (hasLost) {
            if (wizardLostStageIdx === null || wizardLostStageIdx === '') {
                return "Please select a Lost stage.";
            }
            const lostIdx = parseInt(wizardLostStageIdx);
            if (lostIdx < convIdx) {
                return "The Lost stage cannot be before the Conversion stage.";
            }
        }

        if (hasWon && hasLost && parseInt(wizardWonStageIdx) === parseInt(wizardLostStageIdx)) {
            return "The Won and Lost stages cannot be the same stage.";
        }

        return null;
    }

    function renderReviewSummary() {
        const convIdx = parseInt(wizardConversionStageIdx);
        
        const leads = wizardStages.slice(0, convIdx).map(s => s.name).join(' &rarr; ');
        document.getElementById('reviewLeadStages').innerHTML = leads || 'None';

        const conv = wizardStages[convIdx] ? wizardStages[convIdx].name : '-';
        document.getElementById('reviewConversionPoint').textContent = conv;

        const opps = wizardStages.slice(convIdx).map(s => s.name).join(' &rarr; ');
        document.getElementById('reviewOpportunityStages').innerHTML = opps || 'None';

        const won = (document.querySelector('input[name="hasWonRadio"]:checked').value === 'yes' && wizardWonStageIdx !== null && wizardStages[wizardWonStageIdx]) ? wizardStages[wizardWonStageIdx].name : 'Skipped / None';
        document.getElementById('reviewWonStage').textContent = won;

        const lost = (document.querySelector('input[name="hasLostRadio"]:checked').value === 'yes' && wizardLostStageIdx !== null && wizardStages[wizardLostStageIdx]) ? wizardStages[wizardLostStageIdx].name : 'Skipped / None';
        document.getElementById('reviewLostStage').textContent = lost;

        const formActive = document.getElementById('wizardEnableFormToggle').checked;
        document.getElementById('reviewFormStatus').textContent = formActive ? `Enabled (${wizardFormFields.length} custom fields)` : 'Disabled';
    }

    async function openWizard() {
        if (!activePipelineId) {
            alert("Please select a pipeline first.");
            return;
        }
        
        try {
            const response = await APIClient.get(`/api/pipeline/stages/?pipeline=${activePipelineId}`);
            let stages = [];
            if (Array.isArray(response)) {
                stages = response;
            } else if (response && response.hasOwnProperty('success')) {
                stages = response.data || [];
            } else if (response && response.results) {
                stages = response.results;
            }
            stages.sort((a, b) => a.order - b.order);
            originalStages = JSON.parse(JSON.stringify(stages));
            wizardStages = JSON.parse(JSON.stringify(stages));
        } catch (e) {
            alert("Failed to load stages for setup wizard.");
            return;
        }

        wizardConversionStageIdx = null;
        wizardWonStageIdx = null;
        wizardLostStageIdx = null;

        wizardStages.forEach((s, idx) => {
            if (s.stage_type === 'CONVERSION') wizardConversionStageIdx = idx;
            else if (s.stage_type === 'WON') wizardWonStageIdx = idx;
            else if (s.stage_type === 'LOST') wizardLostStageIdx = idx;
        });

        if (wizardConversionStageIdx === null && wizardStages.length > 1) {
            wizardConversionStageIdx = 1;
        }

        wizardFormFields = [];
        wizardEnableForm = true;
        try {
            const formRes = await APIClient.get(`/api/pipelines/${activePipelineId}/form/`);
            const formData = formRes.data || formRes;
            if (formData) {
                wizardEnableForm = formData.is_active;
                wizardFormFields = formData.fields || [];
            }
        } catch (e) {
            console.log("No custom form configured yet, starting empty.");
        }

        document.getElementById('wizardEnableFormToggle').checked = wizardEnableForm;
        if (wizardEnableForm) {
            document.getElementById('wizardFormBuilderWorkspace').classList.remove('d-none');
        } else {
            document.getElementById('wizardFormBuilderWorkspace').classList.add('d-none');
        }

        document.getElementById('hasWonYes').checked = (wizardWonStageIdx !== null);
        document.getElementById('hasWonNo').checked = (wizardWonStageIdx === null);
        if (wizardWonStageIdx !== null) {
            document.getElementById('wonStageDropdownWrapper').classList.remove('d-none');
        } else {
            document.getElementById('wonStageDropdownWrapper').classList.add('d-none');
        }

        document.getElementById('hasLostYes').checked = (wizardLostStageIdx !== null);
        document.getElementById('hasLostNo').checked = (wizardLostStageIdx === null);
        if (wizardLostStageIdx !== null) {
            document.getElementById('lostStageDropdownWrapper').classList.remove('d-none');
        } else {
            document.getElementById('lostStageDropdownWrapper').classList.add('d-none');
        }

        document.getElementById('wizardAlertContainer').innerHTML = '';
        document.getElementById('wizardSaveLogs').innerHTML = '';
        document.getElementById('wizardSaveLogs').classList.add('d-none');

        renderWizardStages();
        showStep(1);
        bsWizardModal.show();
    }

    // Toggle handlers
    document.querySelectorAll('input[name="hasWonRadio"]').forEach(r => {
        r.addEventListener('change', () => {
            const wrapper = document.getElementById('wonStageDropdownWrapper');
            if (r.value === 'yes') {
                wrapper.classList.remove('d-none');
                if (wizardWonStageIdx === null) {
                    const startIdx = wizardConversionStageIdx !== null ? parseInt(wizardConversionStageIdx) : 0;
                    if (startIdx < wizardStages.length) {
                        wizardWonStageIdx = startIdx;
                        document.getElementById('wizardWonStageSelect').value = startIdx;
                    }
                }
            } else {
                wrapper.classList.add('d-none');
                wizardWonStageIdx = null;
            }
        });
    });

    document.querySelectorAll('input[name="hasLostRadio"]').forEach(r => {
        r.addEventListener('change', () => {
            const wrapper = document.getElementById('lostStageDropdownWrapper');
            if (r.value === 'yes') {
                wrapper.classList.remove('d-none');
                if (wizardLostStageIdx === null) {
                    const startIdx = wizardConversionStageIdx !== null ? parseInt(wizardConversionStageIdx) : 0;
                    if (startIdx < wizardStages.length) {
                        wizardLostStageIdx = startIdx;
                        document.getElementById('wizardLostStageSelect').value = startIdx;
                    }
                }
            } else {
                wrapper.classList.add('d-none');
                wizardLostStageIdx = null;
            }
        });
    });

    document.getElementById('wizardEnableFormToggle').addEventListener('change', (e) => {
        wizardEnableForm = e.target.checked;
        const workspace = document.getElementById('wizardFormBuilderWorkspace');
        if (wizardEnableForm) {
            workspace.classList.remove('d-none');
        } else {
            workspace.classList.add('d-none');
        }
    });

    // Dropdown change binds
    document.getElementById('wizardConversionStageSelect').addEventListener('change', (e) => {
        wizardConversionStageIdx = e.target.value !== '' ? parseInt(e.target.value) : null;
    });
    document.getElementById('wizardWonStageSelect').addEventListener('change', (e) => {
        wizardWonStageIdx = e.target.value !== '' ? parseInt(e.target.value) : null;
    });
    document.getElementById('wizardLostStageSelect').addEventListener('change', (e) => {
        wizardLostStageIdx = e.target.value !== '' ? parseInt(e.target.value) : null;
    });

    // Back / Next / Trigger Binds
    if (openWizardBtn) {
        openWizardBtn.addEventListener('click', openWizard);
    }

    wizardBackBtn.addEventListener('click', () => {
        if (currentStep > 1) {
            showStep(currentStep - 1);
        }
    });

    wizardNextBtn.addEventListener('click', () => {
        if (currentStep === 1) {
            if (wizardStages.length < 2) {
                UIUtils.showAlert('wizardAlertContainer', 'The pipeline must have at least 2 stages.', 'danger');
                return;
            }
            const emptyStage = wizardStages.find(s => !s.name || !s.name.trim());
            if (emptyStage) {
                UIUtils.showAlert('wizardAlertContainer', 'Stage names cannot be empty.', 'danger');
                return;
            }
            document.getElementById('wizardAlertContainer').innerHTML = '';
            populateStep2Dropdown();
            showStep(2);
        } else if (currentStep === 2) {
            if (wizardConversionStageIdx === null || wizardConversionStageIdx === '') {
                UIUtils.showAlert('wizardAlertContainer', 'Please select a conversion stage.', 'danger');
                return;
            }
            const convIdx = parseInt(wizardConversionStageIdx);
            if (convIdx === 0) {
                UIUtils.showAlert('wizardAlertContainer', 'The conversion stage cannot be the first stage. There must be at least one Lead stage.', 'danger');
                return;
            }
            document.getElementById('wizardAlertContainer').innerHTML = '';
            populateStep3Dropdowns();
            showStep(3);
        } else if (currentStep === 3) {
            const err = validateWizardConfig();
            if (err) {
                UIUtils.showAlert('wizardAlertContainer', err, 'danger');
                return;
            }
            document.getElementById('wizardAlertContainer').innerHTML = '';
            renderWizardFormFields();
            showStep(4);
        } else if (currentStep === 4) {
            document.getElementById('wizardAlertContainer').innerHTML = '';
            showStep(5);
        }
    });

    wizardSaveBtn.addEventListener('click', async () => {
        const err = validateWizardConfig();
        if (err) {
            UIUtils.showAlert('wizardAlertContainer', err, 'danger');
            return;
        }

        document.getElementById('wizardAlertContainer').innerHTML = '';
        const logBox = document.getElementById('wizardSaveLogs');
        logBox.classList.remove('d-none');
        logBox.innerHTML = '';
        
        function logMsg(msg) {
            const d = document.createElement('div');
            d.textContent = `> ${msg}`;
            logBox.appendChild(d);
            logBox.scrollTop = logBox.scrollHeight;
        }

        wizardSaveBtn.disabled = true;
        wizardBackBtn.disabled = true;

        try {
            logMsg("Saving stages configuration...");
            const savedStages = [];
            for (let i = 0; i < wizardStages.length; i++) {
                const ws = wizardStages[i];
                const payload = {
                    pipeline: activePipelineId,
                    name: ws.name,
                    order: i,
                    color: ws.color || "#6c757d"
                };

                logMsg(`Processing stage: "${ws.name}" (Position: ${i + 1})...`);
                let res;
                if (ws.id) {
                    res = await APIClient.patch(`/api/pipeline/stages/${ws.id}/`, payload);
                } else {
                    res = await APIClient.post('/api/pipeline/stages/', payload);
                }
                const saved = res.data || res;
                savedStages.push(saved);
            }
            logMsg("Stages configuration saved successfully.");

            // Soft-delete removed stages
            const activeIds = savedStages.map(s => s.id);
            const deletedStages = originalStages.filter(os => !activeIds.includes(os.id));

            if (deletedStages.length > 0) {
                logMsg(`Processing deletions for ${deletedStages.length} removed stage(s)...`);
                for (const ds of deletedStages) {
                    logMsg(`Soft deleting stage: "${ds.name}"...`);
                    try {
                        await APIClient.delete(`/api/pipeline/stages/${ds.id}/`);
                    } catch (e) {
                        if (e.message && e.message.includes("Please provide a reassign_stage_id")) {
                            logMsg(`Stage "${ds.name}" contains active cards. Demanding reassignment.`);
                            const promptMsg = `Stage "${ds.name}" contains active cards. Please enter the number (Position) of the target stage to reassign them to (1 to ${savedStages.length}):\n` +
                                              savedStages.map((s, idx) => `[${idx+1}] ${s.name}`).join('\n');
                            const targetIdx = prompt(promptMsg);
                            const targetNum = parseInt(targetIdx);
                            if (!isNaN(targetNum) && targetNum >= 1 && targetNum <= savedStages.length) {
                                const reassignId = savedStages[targetNum - 1].id;
                                logMsg(`Reassigning cards to "${savedStages[targetNum - 1].name}" and retrying deletion...`);
                                await APIClient.delete(`/api/pipeline/stages/${ds.id}/`, {
                                    reassign_stage_id: reassignId
                                });
                            } else {
                                throw new Error(`Deletion of stage "${ds.name}" cancelled or invalid reassign stage selected.`);
                            }
                        } else {
                            throw e;
                        }
                    }
                }
                logMsg("Omitted stages deleted successfully.");
            }

            // Sync updated database stage IDs for configuration behavior anchors
            logMsg("Synchronizing stage IDs for behavior role mapping...");
            const refreshedRes = await APIClient.get(`/api/pipeline/stages/?pipeline=${activePipelineId}`);
            let freshStages = [];
            if (Array.isArray(refreshedRes)) {
                freshStages = refreshedRes;
            } else if (refreshedRes && refreshedRes.hasOwnProperty('success')) {
                freshStages = refreshedRes.data || [];
            } else if (refreshedRes && refreshedRes.results) {
                freshStages = refreshedRes.results;
            }
            freshStages.sort((a, b) => a.order - b.order);

            const convStageObj = freshStages[parseInt(wizardConversionStageIdx)];
            const wonStageObj = (document.querySelector('input[name="hasWonRadio"]:checked').value === 'yes' && wizardWonStageIdx !== null) ? freshStages[parseInt(wizardWonStageIdx)] : null;
            const lostStageObj = (document.querySelector('input[name="hasLostRadio"]:checked').value === 'yes' && wizardLostStageIdx !== null) ? freshStages[parseInt(wizardLostStageIdx)] : null;

            if (!convStageObj) {
                throw new Error("Could not resolve conversion stage database record.");
            }

            logMsg(`Mapping boundary conversion stage to: "${convStageObj.name}"...`);
            if (wonStageObj) logMsg(`Mapping Won stage to: "${wonStageObj.name}"...`);
            if (lostStageObj) logMsg(`Mapping Lost stage to: "${lostStageObj.name}"...`);

            logMsg("Updating pipeline behavior configuration...");
            await APIClient.post(`/api/pipelines/${activePipelineId}/configure_behavior/`, {
                conversion_stage_id: convStageObj.id,
                won_stage_id: wonStageObj ? wonStageObj.id : null,
                lost_stage_id: lostStageObj ? lostStageObj.id : null
            });
            logMsg("Pipeline behavior configuration updated successfully.");

            logMsg("Saving Opportunity Custom Form Template...");
            wizardFormFields.forEach((field, index) => {
                field.order = index;
            });
            await APIClient.post(`/api/pipelines/${activePipelineId}/form/`, {
                is_active: wizardEnableForm,
                fields: wizardFormFields
            });
            logMsg("Opportunity Custom Form Template saved successfully.");

            logMsg("--- PIPELINE SETUP COMPLETE! ---");
            alert("Pipeline configured successfully!");
            bsWizardModal.hide();
            await loadStages(activePipelineId);
        } catch (err) {
            console.error("Setup wizard failed to save configuration:", err);
            logMsg(`ERROR: ${err.message}`);
            UIUtils.showAlert('wizardAlertContainer', err.message || 'Failed to save pipeline configuration.', 'danger');
        } finally {
            wizardSaveBtn.disabled = false;
            wizardBackBtn.disabled = false;
        }
    });

    // --- Initialize ---
    (async () => {
        try {
            console.log("Initializing settings page...");
            await loadPipelines();
        } catch (err) {
            console.error("Settings initialization failed:", err);
        }
    })();
});
