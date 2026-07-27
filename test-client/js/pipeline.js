document.addEventListener('DOMContentLoaded', () => {
    // --- UI Elements ---
    const logList = document.getElementById('logList');
    const detailViewer = document.getElementById('requestDetailViewer');
    const boardContainer = document.getElementById('kanbanBoard');
    const pipelineSelect = document.getElementById('pipelineSelect');
    
    const drawerEl = document.getElementById('pipelineDrawer');
    const drawerTitle = document.getElementById('drawerTitle');
    const drawerContent = document.getElementById('drawerContent');
    const bsDrawer = new bootstrap.Offcanvas(drawerEl);

    let activePipelineId = null;
    let activeStages = [];
    const sortables = [];

    // Shared list of CRM users/salespersons to populate select dropdowns
    const users = [
        { id: 1, name: "Admin" },
        { id: 2, name: "Manager" },
        { id: 3, name: "Salesperson 1" },
        { id: 4, name: "Salesperson 2" }
    ];

    // --- Developer Log Panel Listener ---
    window.addEventListener('crm-api-log', (event) => {
        const log = event.detail;
        
        // Create log item
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

        // Prepend to list
        if (logList.querySelector('.text-center')) {
            logList.innerHTML = '';
        }
        logList.insertBefore(item, logList.firstChild);

        // Limit log items to 50
        while (logList.children.length > 50) {
            logList.removeChild(logList.lastChild);
        }

        renderRequestDetails(log);
        item.classList.add('active');
    });

    function renderRequestDetails(log) {
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

    // --- Helper to Build Card HTML ---
    function createCardElement(card) {
        const div = document.createElement('div');
        div.className = 'card mb-2 shadow-sm border kanban-card bg-white';
        div.dataset.id = card.id;
        div.dataset.type = card.entity_type;
        div.innerHTML = getCardInnerHTML(card);
        
        // Click to open Drawer details
        div.addEventListener('click', (e) => {
            if (e.target.closest('a') || e.target.closest('button')) {
                return;
            }
            openCardDrawer(card.entity_type, card.id, div);
        });

        return div;
    }

    function getCardInnerHTML(card) {
        const isLead = card.entity_type === 'lead';
        const typeBadge = isLead ? 'bg-secondary' : 'bg-primary';
        const amountDisplay = card.amount ? `<div class="text-dark small mb-1"><strong>Amount:</strong> $${Number(card.amount).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>` : '';
        const closeDisplay = card.expected_close_date ? `<div class="text-muted small mb-1"><strong>Close Date:</strong> ${card.expected_close_date}</div>` : '';
        const probDisplay = card.probability !== null && card.probability !== undefined ? `<div class="text-muted small mb-1"><strong>Probability:</strong> ${card.probability}%</div>` : '';
        const ownerDisplay = `<div class="text-muted small"><strong>Owner:</strong> ${card.assigned_salesperson_name || 'Unassigned'}</div>`;
        
        return `
            <div class="card-body p-3">
                <div class="d-flex justify-content-between align-items-start mb-2">
                    <span class="badge ${typeBadge} text-uppercase small" style="font-size: 0.65rem;">${card.entity_type}</span>
                    <span class="text-muted small font-monospace">#${card.id}</span>
                </div>
                <h6 class="card-title font-weight-bold text-dark mb-1" style="font-size: 0.9rem;">${card.name}</h6>
                <p class="text-secondary small mb-2" style="font-size: 0.8rem;">${card.company_name || 'No Company'}</p>
                ${amountDisplay}
                ${closeDisplay}
                ${probDisplay}
                ${ownerDisplay}
            </div>
        `;
    }

    // --- Slide-out Details Drawer Logic ---
    async function openCardDrawer(entityType, id, cardEl) {
        drawerTitle.textContent = `${entityType === 'lead' ? 'Lead' : 'Opportunity'} Details`;
        drawerContent.innerHTML = `
            <div class="text-center py-5 text-muted">
                <div class="spinner-border text-primary" role="status"></div>
                <div class="mt-2">Loading details...</div>
            </div>
        `;
        bsDrawer.show();

        try {
            if (entityType === 'lead') {
                const response = await APIClient.get(`/api/leads/${id}/`);
                if (response.success) {
                    renderLeadForm(response.data, cardEl);
                } else {
                    drawerContent.innerHTML = `<div class="alert alert-danger">${response.message || 'Error loading details.'}</div>`;
                }
            } else {
                const response = await APIClient.get(`/api/opportunities/${id}/`);
                if (response.success) {
                    renderOpportunityForm(response.data, cardEl);
                } else {
                    drawerContent.innerHTML = `<div class="alert alert-danger">${response.message || 'Error loading details.'}</div>`;
                }
            }
        } catch (error) {
            drawerContent.innerHTML = `<div class="alert alert-danger">${error.message || 'Failed to fetch details.'}</div>`;
        }
    }

    function renderLeadForm(lead, cardEl) {
        // Filter active pipeline stages compatible with Leads
        const compatibleStages = activeStages.filter(s => s.entity_type === 'LEAD' || s.stage_type === 'CONVERSION' || s.stage_type === 'LOST');

        drawerContent.innerHTML = `
            <form id="drawerForm">
                <div class="mb-3">
                    <label class="form-label font-weight-medium small text-muted text-uppercase">Lead ID</label>
                    <input type="text" class="form-control bg-light" value="${lead.lead_code || lead.id}" readonly>
                </div>
                <div class="mb-3">
                    <label for="edit_full_name" class="form-label font-weight-medium">Full Name</label>
                    <input type="text" class="form-control" id="edit_full_name" value="${lead.full_name || ''}" required>
                </div>
                <div class="mb-3">
                    <label for="edit_company_name" class="form-label font-weight-medium">Company Name</label>
                    <input type="text" class="form-control" id="edit_company_name" value="${lead.company_name || ''}" required>
                </div>
                <div class="mb-3">
                    <label for="edit_phone" class="form-label font-weight-medium">Phone</label>
                    <input type="text" class="form-control" id="edit_phone" value="${lead.phone || ''}">
                </div>
                <div class="mb-3">
                    <label for="edit_email" class="form-label font-weight-medium">Email</label>
                    <input type="email" class="form-control" id="edit_email" value="${lead.email || ''}">
                </div>
                <div class="mb-3">
                    <label for="edit_source" class="form-label font-weight-medium">Lead Source</label>
                    <select class="form-select" id="edit_source">
                        <option value="WEBSITE" ${lead.source === 'WEBSITE' ? 'selected' : ''}>Website</option>
                        <option value="FACEBOOK" ${lead.source === 'FACEBOOK' ? 'selected' : ''}>Facebook</option>
                        <option value="GOOGLE_ADS" ${lead.source === 'GOOGLE_ADS' ? 'selected' : ''}>Google Ads</option>
                        <option value="REFERRAL" ${lead.source === 'REFERRAL' ? 'selected' : ''}>Referral</option>
                        <option value="WALK_IN" ${lead.source === 'WALK_IN' ? 'selected' : ''}>Walk-in</option>
                        <option value="PHONE_CALL" ${lead.source === 'PHONE_CALL' ? 'selected' : ''}>Phone Call</option>
                        <option value="EMAIL_CAMPAIGN" ${lead.source === 'EMAIL_CAMPAIGN' ? 'selected' : ''}>Email Campaign</option>
                        <option value="OTHER" ${lead.source === 'OTHER' ? 'selected' : ''}>Other</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label for="edit_priority" class="form-label font-weight-medium">Priority</label>
                    <select class="form-select" id="edit_priority">
                        <option value="LOW" ${lead.priority === 'LOW' ? 'selected' : ''}>Low</option>
                        <option value="MEDIUM" ${lead.priority === 'MEDIUM' ? 'selected' : ''}>Medium</option>
                        <option value="HIGH" ${lead.priority === 'HIGH' ? 'selected' : ''}>High</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label for="edit_lead_stage" class="form-label font-weight-medium">Pipeline Stage</label>
                    <select class="form-select" id="edit_lead_stage">
                        ${compatibleStages.map(s => `<option value="${s.id}" ${lead.pipeline_stage === s.id ? 'selected' : ''}>${s.name}</option>`).join('')}
                    </select>
                </div>
                <div class="mb-3">
                    <label for="edit_assigned_salesperson" class="form-label font-weight-medium">Assigned Salesperson</label>
                    <select class="form-select" id="edit_assigned_salesperson">
                        <option value="">Unassigned</option>
                        ${users.map(u => `<option value="${u.id}" ${lead.assigned_salesperson === u.id ? 'selected' : ''}>${u.name}</option>`).join('')}
                    </select>
                </div>
                <div class="mb-3">
                    <label for="edit_notes" class="form-label font-weight-medium">Notes</label>
                    <textarea class="form-control" id="edit_notes" rows="4">${lead.notes || ''}</textarea>
                </div>
                <div class="mt-4 d-flex gap-2">
                    <button type="submit" class="btn btn-primary flex-grow-1 py-2" id="saveDrawerBtn">Save Details</button>
                    <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="offcanvas">Cancel</button>
                </div>
            </form>
        `;

        document.getElementById('drawerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const saveBtn = document.getElementById('saveDrawerBtn');
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Saving...';

            const newStageId = parseInt(document.getElementById('edit_lead_stage').value);
            const salespersonVal = document.getElementById('edit_assigned_salesperson').value;
            const newSalesperson = salespersonVal ? parseInt(salespersonVal) : null;

            const payload = {
                full_name: document.getElementById('edit_full_name').value.trim(),
                company_name: document.getElementById('edit_company_name').value.trim(),
                phone: document.getElementById('edit_phone').value.trim(),
                email: document.getElementById('edit_email').value.trim(),
                source: document.getElementById('edit_source').value,
                priority: document.getElementById('edit_priority').value,
                notes: document.getElementById('edit_notes').value.trim(),
            };

            try {
                const updateRes = await APIClient.put(`/api/leads/${lead.id}/`, payload);
                if (updateRes.success) {
                    if (newSalesperson !== lead.assigned_salesperson) {
                        await APIClient.post(`/api/leads/${lead.id}/assign/`, {
                            assigned_salesperson: newSalesperson
                        });
                    }

                    if (newStageId !== lead.pipeline_stage) {
                        await APIClient.post('/api/pipeline/move/', {
                            entity_type: 'lead',
                            id: lead.id,
                            target_stage_id: newStageId
                        });
                    }

                    UIUtils.showAlert('mainAlertContainer', 'Lead details updated successfully.');
                    bsDrawer.hide();
                    loadPipeline();
                } else {
                    UIUtils.showAlert('mainAlertContainer', updateRes.message || 'Failed to save lead.', 'danger');
                }
            } catch (err) {
                UIUtils.showAlert('mainAlertContainer', err.message || 'Error occurred while saving.', 'danger');
                loadPipeline();
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Details';
            }
        });
    }

    function renderOpportunityForm(opp, cardEl) {
        // Filter active pipeline stages compatible with Opportunities
        const compatibleStages = activeStages.filter(s => s.entity_type === 'OPPORTUNITY' || s.stage_type === 'CONVERSION');

        drawerContent.innerHTML = `
            <form id="drawerForm">
                <div class="mb-3">
                    <label class="form-label font-weight-medium small text-muted text-uppercase">Opportunity ID</label>
                    <input type="text" class="form-control bg-light" value="${opp.opportunity_code || opp.id}" readonly>
                </div>
                <div class="mb-3">
                    <label class="form-label font-weight-medium small text-muted text-uppercase d-block">Related Company</label>
                    <span class="text-dark font-weight-semibold">${opp.company_name || 'None'}</span>
                    ${opp.company ? `<a href="companies.html?id=${opp.company}" target="_blank" class="btn btn-sm btn-link py-0 px-1 ms-2">Open Profile &raquo;</a>` : ''}
                </div>
                <div class="mb-3">
                    <label class="form-label font-weight-medium small text-muted text-uppercase d-block">Primary Contact</label>
                    <span class="text-dark font-weight-semibold">${opp.name || 'None'}</span>
                    ${opp.primary_contact ? `<a href="contacts.html?id=${opp.primary_contact}" target="_blank" class="btn btn-sm btn-link py-0 px-1 ms-2">Open Profile &raquo;</a>` : ''}
                </div>
                
                <hr class="my-3 text-muted">
                
                <div class="mb-3">
                    <label for="edit_opp_amount" class="form-label font-weight-medium">Deal Amount ($)</label>
                    <input type="number" step="0.01" class="form-control" id="edit_opp_amount" value="${opp.amount || '0.00'}" required>
                </div>
                <div class="mb-3">
                    <label for="edit_opp_close_date" class="form-label font-weight-medium">Expected Close Date</label>
                    <input type="date" class="form-control" id="edit_opp_close_date" value="${opp.expected_close_date || ''}" required>
                </div>
                <div class="mb-3">
                    <label for="edit_opp_probability" class="form-label font-weight-medium">Probability (%)</label>
                    <input type="number" class="form-control bg-light" id="edit_opp_probability" value="${opp.probability || ''}" readonly>
                    <div class="form-text text-muted small">Calculated dynamically based on column stage.</div>
                </div>
                <div class="mb-3">
                    <label for="edit_opp_stage_select" class="form-label font-weight-medium">Stage</label>
                    <select class="form-select" id="edit_opp_stage_select">
                        ${compatibleStages.map(s => `<option value="${s.id}" data-type="${s.stage_type}" ${opp.pipeline_stage === s.id ? 'selected' : ''}>${s.name}</option>`).join('')}
                    </select>
                </div>
                
                <div class="mb-3 d-none" id="lostReasonGroup">
                    <label for="edit_opp_lost_reason" class="form-label font-weight-medium text-danger">Lost Reason</label>
                    <input type="text" class="form-control border-danger" id="edit_opp_lost_reason" value="${opp.lost_reason || ''}" placeholder="Enter reason for losing deal">
                </div>

                <div class="mb-3">
                    <label for="edit_opp_salesperson" class="form-label font-weight-medium">Assigned Salesperson</label>
                    <select class="form-select" id="edit_opp_salesperson">
                        <option value="">Unassigned</option>
                        ${users.map(u => `<option value="${u.id}" ${opp.assigned_salesperson === u.id ? 'selected' : ''}>${u.name}</option>`).join('')}
                    </select>
                </div>
                <div class="mb-3">
                    <label for="edit_opp_description" class="form-label font-weight-medium">Notes / Description</label>
                    <textarea class="form-control" id="edit_opp_description" rows="4">${opp.description || ''}</textarea>
                </div>
                <div class="mt-4 d-flex gap-2">
                    <button type="submit" class="btn btn-primary flex-grow-1 py-2" id="saveDrawerBtn">Save Details</button>
                    <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="offcanvas">Cancel</button>
                </div>
            </form>
        `;

        const stageSelect = document.getElementById('edit_opp_stage_select');
        const lostReasonGroup = document.getElementById('lostReasonGroup');
        
        function toggleLostReason() {
            const selectedOpt = stageSelect.options[stageSelect.selectedIndex];
            const stageType = selectedOpt ? selectedOpt.dataset.type : '';
            if (stageType === 'LOST') {
                lostReasonGroup.classList.remove('d-none');
            } else {
                lostReasonGroup.classList.add('d-none');
            }
        }
        
        stageSelect.addEventListener('change', toggleLostReason);
        toggleLostReason(); // trigger on initial draw

        document.getElementById('drawerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const saveBtn = document.getElementById('saveDrawerBtn');
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Saving...';

            const newStageId = parseInt(stageSelect.value);
            const selectedOpt = stageSelect.options[stageSelect.selectedIndex];
            const stageType = selectedOpt ? selectedOpt.dataset.type : '';

            const payload = {
                name: opp.name,
                amount: parseFloat(document.getElementById('edit_opp_amount').value),
                expected_close_date: document.getElementById('edit_opp_close_date').value || null,
                lost_reason: stageType === 'LOST' ? document.getElementById('edit_opp_lost_reason').value.trim() : '',
                assigned_salesperson: document.getElementById('edit_opp_salesperson').value ? parseInt(document.getElementById('edit_opp_salesperson').value) : null,
                description: document.getElementById('edit_opp_description').value.trim()
            };

            try {
                const updateRes = await APIClient.put(`/api/opportunities/${opp.id}/`, payload);
                if (updateRes.success) {
                    if (newStageId !== opp.pipeline_stage) {
                        await APIClient.post('/api/pipeline/move/', {
                            entity_type: 'opportunity',
                            id: opp.id,
                            target_stage_id: newStageId
                        });
                    }

                    UIUtils.showAlert('mainAlertContainer', 'Opportunity details updated successfully.');
                    bsDrawer.hide();
                    loadPipeline();
                } else {
                    UIUtils.showAlert('mainAlertContainer', updateRes.message || 'Failed to save opportunity.', 'danger');
                }
            } catch (err) {
                UIUtils.showAlert('mainAlertContainer', err.message || 'Error occurred while saving.', 'danger');
                loadPipeline();
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Details';
            }
        });
    }

    // --- Load Pipelines list ---
    async function loadPipelines() {
        try {
            const response = await APIClient.get('/api/pipelines/');
            if (response.success) {
                pipelineSelect.innerHTML = '';
                const pipelines = response.data;
                if (pipelines.length === 0) {
                    pipelineSelect.innerHTML = '<option value="">No pipelines configured</option>';
                    boardContainer.innerHTML = '<div class="text-center py-5 text-muted w-100">Configure a pipeline and stages in settings first.</div>';
                    return;
                }

                pipelines.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p.id;
                    opt.textContent = p.name;
                    pipelineSelect.appendChild(opt);
                });

                // Default selection
                activePipelineId = parseInt(pipelineSelect.value);
                loadPipeline();
            }
        } catch (e) {
            UIUtils.showAlert('mainAlertContainer', 'Failed to fetch pipelines list.', 'danger');
        }
    }

    pipelineSelect.addEventListener('change', () => {
        activePipelineId = parseInt(pipelineSelect.value);
        loadPipeline();
    });

    // --- Load Pipeline Stages & Cards ---
    async function loadPipeline() {
        if (!activePipelineId) return;

        // Destroy existing sortables to avoid duplicate bindings
        sortables.forEach(s => s.destroy());
        sortables.length = 0;

        boardContainer.innerHTML = '<div class="text-center py-5 text-muted w-100"><div class="spinner-border text-primary me-2" role="status"></div>Loading pipeline layout...</div>';

        try {
            // 1. Fetch Stages configurations
            const stagesRes = await APIClient.get(`/api/pipeline/stages/?pipeline=${activePipelineId}`);
            if (stagesRes.success) {
                activeStages = stagesRes.data;
                activeStages.sort((a, b) => a.order - b.order);
                
                if (activeStages.length === 0) {
                    boardContainer.innerHTML = '<div class="text-center py-5 text-muted w-100">No stages configured in this pipeline. Please add stages in Settings.</div>';
                    return;
                }

                // Render dynamic columns layout
                boardContainer.innerHTML = '';
                const countBadges = {};
                const lists = {};

                activeStages.forEach(stage => {
                    const colDiv = document.createElement('div');
                    colDiv.className = 'kanban-column flex-shrink-0';
                    colDiv.dataset.stageId = stage.id;
                    colDiv.innerHTML = `
                        <div class="card border-0 shadow-sm h-100">
                            <div class="card-header bg-white py-3 border-0 d-flex justify-content-between align-items-center">
                                <h6 class="mb-0 font-weight-bold" style="color: ${stage.color || '#333333'};">${stage.name}</h6>
                                <span class="badge rounded-pill" style="background-color: ${stage.color || '#6c757d'}22; color: ${stage.color || '#6c757d'};" id="count-${stage.id}">0</span>
                            </div>
                            <div class="card-body p-2 kanban-list" id="list-${stage.id}"></div>
                        </div>
                    `;
                    boardContainer.appendChild(colDiv);

                    lists[stage.id] = document.getElementById(`list-${stage.id}`);
                    countBadges[stage.id] = document.getElementById(`count-${stage.id}`);
                });

                // 2. Fetch cards matching active stages
                const cardsRes = await APIClient.get('/api/pipeline/');
                if (cardsRes.success) {
                    const cards = cardsRes.data;
                    const columnCounts = {};
                    activeStages.forEach(s => columnCounts[s.id] = 0);

                    cards.forEach(card => {
                        const stageId = card.pipeline_stage_id;
                        if (stageId && lists[stageId]) {
                            const cardEl = createCardElement(card);
                            lists[stageId].appendChild(cardEl);
                            columnCounts[stageId]++;
                        }
                    });

                    // Update count badges
                    activeStages.forEach(s => {
                        countBadges[s.id].textContent = columnCounts[s.id];
                    });

                    // 3. Initialize SortableJS drag-and-drop
                    activeStages.forEach(stage => {
                        const sortable = new Sortable(lists[stage.id], {
                            group: 'pipeline',
                            animation: 150,
                            ghostClass: 'sortable-ghost',
                            onEnd: async (evt) => {
                                const itemEl = evt.item;
                                const sourceList = evt.from;
                                const targetList = evt.to;
                                const sourceStageId = parseInt(sourceList.parentElement.parentElement.dataset.stageId);
                                const targetStageId = parseInt(targetList.parentElement.parentElement.dataset.stageId);

                                if (sourceStageId === targetStageId) return;

                                const entityType = itemEl.dataset.type;
                                const idVal = itemEl.dataset.id;

                                try {
                                    const moveResponse = await APIClient.post('/api/pipeline/move/', {
                                        entity_type: entityType,
                                        id: parseInt(idVal),
                                        target_stage_id: targetStageId
                                    });

                                    if (moveResponse.success) {
                                        const updatedCard = moveResponse.data;
                                        itemEl.dataset.type = updatedCard.entity_type;
                                        itemEl.dataset.id = updatedCard.id;
                                        itemEl.innerHTML = getCardInnerHTML(updatedCard);

                                        countBadges[sourceStageId].textContent = sourceList.children.length;
                                        countBadges[targetStageId].textContent = targetList.children.length;

                                        UIUtils.showAlert('mainAlertContainer', moveResponse.message || 'Card moved successfully.');
                                        
                                        // If drop triggered lead -> opp conversion, reload board layout to place opportunity cards
                                        const targetStageObj = activeStages.find(x => x.id === targetStageId);
                                        if (entityType === 'lead' && targetStageObj && targetStageObj.stage_type === 'CONVERSION') {
                                            loadPipeline();
                                        }
                                    }
                                } catch (error) {
                                    UIUtils.showAlert('mainAlertContainer', error.message || 'Failed to move card.', 'danger');
                                    loadPipeline();
                                }
                            }
                        });
                        sortables.push(sortable);
                    });
                }
            }
        } catch (error) {
            boardContainer.innerHTML = '<div class="text-center py-5 text-danger w-100">Error loading pipeline board data.</div>';
        }
    }

    // --- Init ---
    loadPipelines();
});
