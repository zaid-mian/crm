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
    const stageEntityTypeInput = document.getElementById('stageEntityTypeInput');
    const stageTypeInput = document.getElementById('stageTypeInput');
    const stageOrderInput = document.getElementById('stageOrderInput');
    const stageColorPicker = document.getElementById('stageColorPicker');
    const stageColorInput = document.getElementById('stageColorInput');
    const saveStageBtn = document.getElementById('saveStageBtn');
    
    const bsStageDrawer = new bootstrap.Offcanvas(stageDrawerEl);
    
    const reassignModalEl = document.getElementById('reassignModal');
    const reassignSelector = document.getElementById('reassignSelector');
    const confirmReassignDeleteBtn = document.getElementById('confirmReassignDeleteBtn');
    const bsReassignModal = new bootstrap.Modal(reassignModalEl);
    
    let activePipelineId = null;
    let deletingStageId = null;

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
                stages.forEach(stage => {
                    const tr = document.createElement('tr');
                    tr.className = 'stage-row';
                    tr.innerHTML = `
                        <td class="font-monospace fw-bold">${stage.order}</td>
                        <td class="fw-semibold">${stage.name}</td>
                        <td><span class="badge bg-secondary text-uppercase">${stage.entity_type}</span></td>
                        <td><span class="badge bg-info bg-opacity-10 text-info text-capitalize">${stage.stage_type.replace('_', ' ')}</span></td>
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
            stageEntityTypeInput.value = stage.entity_type;
            stageTypeInput.value = stage.stage_type;
            stageOrderInput.value = stage.order;
            stageColorInput.value = stage.color || "#6c757d";
            stageColorPicker.value = stage.color || "#6c757d";
        } else {
            stageDrawerTitle.textContent = "Create Stage Settings";
            stageIdInput.value = "";
            stageNameInput.value = "";
            stageEntityTypeInput.value = "LEAD";
            stageTypeInput.value = "NORMAL_LEAD";
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
                entity_type: stageEntityTypeInput.value,
                stage_type: stageTypeInput.value,
                order: parseInt(stageOrderInput.value),
                color: stageColorInput.value
            };

            try {
                let res;
                if (id) {
                    res = await APIClient.put(`/api/pipeline/stages/${id}/`, payload);
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
