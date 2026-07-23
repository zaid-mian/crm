document.addEventListener('DOMContentLoaded', () => {
    // --- State Variables ---
    let opportunities = [];
    let currentPage = 1;
    let totalPages = 1;
    let currentOrdering = '-created_at';
    let searchTimeout = null;
    let activeOpportunityId = null;

    // --- UI Elements ---
    const searchBox = document.getElementById('searchBox');
    const filterStage = document.getElementById('filterStage');
    const filterSource = document.getElementById('filterSource');
    const filterOwner = document.getElementById('filterOwner');

    const opportunityTable = document.getElementById('opportunityTable');
    const opportunityTableBody = opportunityTable.querySelector('tbody');
    const rawResponseEl = document.getElementById('rawResponse');

    const paginationDisplay = document.getElementById('paginationDisplay');
    const prevPageBtn = document.getElementById('prevPageBtn');
    const nextPageBtn = document.getElementById('nextPageBtn');

    // Bootstrap Drawer & Modal initializers
    const profileDrawerEl = document.getElementById('opportunityProfileDrawer');
    const leadDrawer = new bootstrap.Offcanvas(profileDrawerEl);

    const stageModalEl = document.getElementById('stageModal');
    const stageModal = new bootstrap.Modal(stageModalEl);
    const stageForm = document.getElementById('stageForm');
    const stageSelect = document.getElementById('stageSelect');
    const lostReasonGroup = document.getElementById('lostReasonGroup');
    const lostReasonSelect = document.getElementById('lostReasonSelect');

    // --- Format Helpers ---
    const formatCurrency = (val) => {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0);
    };

    const UIUtils = {
        formatStage: (stage) => {
            const mappings = {
                'QUALIFICATION': '<span class="badge bg-secondary">Qualification</span>',
                'DISCOVERY': '<span class="badge bg-info text-dark">Discovery</span>',
                'PROPOSAL': '<span class="badge bg-primary">Proposal</span>',
                'NEGOTIATION': '<span class="badge bg-warning text-dark">Negotiation</span>',
                'CLOSED_WON': '<span class="badge bg-success">Closed Won</span>',
                'CLOSED_LOST': '<span class="badge bg-danger">Closed Lost</span>'
            };
            return mappings[stage] || `<span class="badge bg-light text-dark">${stage}</span>`;
        },
        showAlert: (containerId, message, type = 'success') => {
            const container = document.getElementById(containerId);
            container.innerHTML = `
                <div class="alert alert-${type} alert-dismissible fade show shadow-sm border-0 py-3" role="alert">
                    <div class="d-flex align-items-center">
                        <span class="small font-weight-medium">${message}</span>
                    </div>
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            setTimeout(() => {
                const alert = container.querySelector('.alert');
                if (alert) {
                    const bsAlert = bootstrap.Alert.getInstance(alert);
                    if (bsAlert) bsAlert.close();
                }
            }, 5000);
        },
        formatAPIError: (error) => {
            if (error.errors && typeof error.errors === 'object') {
                const details = [];
                for (const [key, value] of Object.entries(error.errors)) {
                    const fieldName = key === 'non_field_errors' ? '' : `${key}: `;
                    if (Array.isArray(value)) {
                        details.push(`${fieldName}${value.join(', ')}`);
                    } else if (typeof value === 'string') {
                        details.push(`${fieldName}${value}`);
                    } else {
                        details.push(`${fieldName}${JSON.stringify(value)}`);
                    }
                }
                if (details.length > 0) {
                    return details.join(' | ');
                }
            }
            return error.message || 'Request failed';
        }
    };

    // Show/hide lost reason depending on Stage choice
    stageSelect.addEventListener('change', (e) => {
        if (e.target.value === 'CLOSED_LOST') {
            lostReasonGroup.classList.remove('d-none');
            lostReasonSelect.required = true;
        } else {
            lostReasonGroup.classList.add('d-none');
            lostReasonSelect.required = false;
        }
    });

    // --- Core API Loading Methods ---
    async function loadOpportunities() {
        let url = `/api/opportunities/?page=${currentPage}&ordering=${currentOrdering}`;
        
        const search = searchBox.value.trim();
        if (search) url += `&search=${encodeURIComponent(search)}`;
        
        const stage = filterStage.value;
        if (stage) url += `&stage=${stage}`;
        
        const source = filterSource.value;
        if (source) url += `&lead_source=${source}`;
        
        const owner = filterOwner.value;
        if (owner) url += `&assigned_salesperson=${owner}`;

        try {
            const response = await APIClient.get(url);
            rawResponseEl.innerText = JSON.stringify(response, null, 2);
            
            if (response.success) {
                opportunities = response.data.results;
                renderTable();
                updatePagination(response.data.pagination);
            }
        } catch (error) {
            rawResponseEl.innerText = JSON.stringify(error, null, 2);
            opportunityTableBody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center py-4 text-danger font-weight-medium">
                        Error loading opportunities: ${UIUtils.formatAPIError(error)}
                    </td>
                </tr>
            `;
        }
    }

    async function loadStats() {
        let url = '/api/opportunities/stats/';
        
        const stage = filterStage.value;
        if (stage) url += `?stage=${stage}`;
        
        const source = filterSource.value;
        if (source) url += `${stage ? '&' : '?'}lead_source=${source}`;
        
        const owner = filterOwner.value;
        if (owner) url += `${(stage || source) ? '&' : '?'}assigned_salesperson=${owner}`;

        try {
            const response = await APIClient.get(url);
            if (response.success) {
                const s = response.data;
                document.getElementById('statTotal').innerText = s.total_deals;
                document.getElementById('statOpen').innerText = s.open_deals;
                document.getElementById('statWon').innerText = s.closed_won;
                document.getElementById('statLost').innerText = s.closed_lost;
                document.getElementById('statPipelineValue').innerText = formatCurrency(s.pipeline_value);
                document.getElementById('statExpectedRevenue').innerText = formatCurrency(s.expected_revenue);
            }
        } catch (error) {
            console.error('Failed to load stats:', error);
        }
    }

    // --- Render Methods ---
    function renderTable() {
        if (!opportunities || opportunities.length === 0) {
            opportunityTableBody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center py-5 text-secondary">
                        No opportunities matching current filters found.
                    </td>
                </tr>
            `;
            return;
        }

        opportunityTableBody.innerHTML = opportunities.map(opp => `
            <tr>
                <td style="padding-left: 1.5rem;" class="font-monospace text-muted small">${opp.opportunity_code || 'N/A'}</td>
                <td class="font-weight-semibold text-dark">${opp.name}</td>
                <td>${opp.company_name}</td>
                <td>${UIUtils.formatStage(opp.stage)}</td>
                <td class="font-weight-medium">${formatCurrency(opp.amount)}</td>
                <td class="small text-secondary">${opp.expected_close_date}</td>
                <td class="small text-muted">User ID: ${opp.assigned_salesperson || 'Unassigned'}</td>
                <td class="text-end" style="padding-right: 1.5rem;">
                    <button class="btn btn-sm btn-outline-primary px-3 view-details-btn" data-id="${opp.id}">Details</button>
                </td>
            </tr>
        `).join('');

        // Bind table details buttons
        document.querySelectorAll('.view-details-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = e.target.getAttribute('data-id');
                openDetailsDrawer(id);
            });
        });
    }

    function updatePagination(p) {
        if (!p) return;
        currentPage = p.page;
        totalPages = p.total_pages;
        paginationDisplay.innerText = `Showing page ${p.page} of ${p.total_pages} (Total: ${p.total_items} deals).`;
        
        prevPageBtn.parentElement.classList.toggle('disabled', p.page <= 1);
        nextPageBtn.parentElement.classList.toggle('disabled', p.page >= p.total_pages);
    }

    // --- Details Drawer Rendering ---
    async function openDetailsDrawer(id) {
        activeOpportunityId = id;
        try {
            const response = await APIClient.get(`/api/opportunities/${id}/`);
            rawResponseEl.innerText = JSON.stringify(response, null, 2);

            if (response.success) {
                const opp = response.data;
                document.getElementById('drawerContent').innerHTML = `
                    <div class="card bg-light border-0 p-4 mb-4">
                        <div class="d-flex align-items-center justify-content-between mb-3">
                            <span class="font-monospace text-muted small">${opp.opportunity_code || 'N/A'}</span>
                            ${UIUtils.formatStage(opp.stage)}
                        </div>
                        <h4 class="text-dark font-weight-bold mb-3">${opp.name}</h4>
                        <div class="row g-3">
                            <div class="col-6">
                                <label class="small text-muted mb-0">Company Name</label>
                                <div class="font-weight-semibold text-dark">${opp.company_name}</div>
                            </div>
                            <div class="col-6">
                                <label class="small text-muted mb-0">Lead Source</label>
                                <div class="font-weight-semibold text-dark">${opp.lead_source || 'None'}</div>
                            </div>
                            <div class="col-6">
                                <label class="small text-muted mb-0">Amount</label>
                                <div class="font-weight-semibold text-dark">${formatCurrency(opp.amount)}</div>
                            </div>
                            <div class="col-6">
                                <label class="small text-muted mb-0">Exp Close Date</label>
                                <div class="font-weight-semibold text-dark">${opp.expected_close_date}</div>
                            </div>
                            <div class="col-6">
                                <label class="small text-muted mb-0">Probability</label>
                                <div class="font-weight-semibold text-dark">${opp.probability}%</div>
                            </div>
                            <div class="col-6">
                                <label class="small text-muted mb-0">Expected Revenue</label>
                                <div class="font-weight-semibold text-primary">${formatCurrency(opp.expected_revenue)}</div>
                            </div>
                        </div>
                    </div>

                    <!-- Owner & Associations -->
                    <div class="mb-4">
                        <h6 class="border-bottom pb-2 font-weight-semibold">Ownership & Links</h6>
                        <div class="row g-2 small text-secondary">
                            <div class="col-12"><strong>Assigned Owner:</strong> User ID ${opp.assigned_salesperson || 'Unassigned'}</div>
                            <div class="col-12"><strong>Primary Contact:</strong> Contact ID ${opp.primary_contact}</div>
                            <div class="col-12"><strong>Source Lead:</strong> Lead ID ${opp.source_lead}</div>
                        </div>
                    </div>

                    <!-- Description/Notes -->
                    <div class="mb-4">
                        <h6 class="border-bottom pb-2 font-weight-semibold">Opportunity Description</h6>
                        <p class="text-secondary bg-light p-3 rounded small">${opp.description || 'No description notes available.'}</p>
                    </div>

                    <!-- Lost Reason (if applicable) -->
                    ${opp.lost_reason ? `
                    <div class="mb-4">
                        <h6 class="border-bottom pb-2 font-weight-semibold text-danger">Lost Details</h6>
                        <div class="alert alert-danger py-2 small mb-0">${opp.lost_reason}</div>
                    </div>
                    ` : ''}

                    <!-- Action buttons -->
                    <div class="d-flex gap-2 justify-content-start mt-4">
                        <button class="btn btn-primary px-3" id="viewEditBtn" ${opp.closed ? 'disabled' : ''}>Edit Deal</button>
                        <button class="btn btn-success px-3" id="viewStageBtn">Change Stage</button>
                    </div>
                `;

                // Bind drawer buttons
                document.getElementById('viewStageBtn').addEventListener('click', () => {
                    // Populate current values in modal
                    stageSelect.value = opp.stage;
                    if (opp.stage === 'CLOSED_LOST') {
                        lostReasonGroup.classList.remove('d-none');
                        lostReasonSelect.value = opp.lost_reason || '';
                    } else {
                        lostReasonGroup.classList.add('d-none');
                    }
                    leadDrawer.hide();
                    setTimeout(() => stageModal.show(), 300);
                });

                document.getElementById('viewEditBtn').addEventListener('click', () => {
                    leadDrawer.hide();
                    setTimeout(() => openEditDrawer(opp), 300);
                });

                leadDrawer.show();
            }
        } catch (error) {
            UIUtils.showAlert('mainAlertContainer', UIUtils.formatAPIError(error), 'danger');
        }
    }

    // --- Edit Mode Drawer Rendering ---
    function openEditDrawer(opp) {
        document.getElementById('drawerContent').innerHTML = `
            <form id="editOppForm">
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Opportunity Name *</label>
                    <input type="text" class="form-control" name="name" value="${opp.name}" required>
                </div>
                <div class="row mb-3">
                    <div class="col">
                        <label class="form-label font-weight-medium">Deal Amount *</label>
                        <input type="number" step="0.01" class="form-control" name="amount" value="${opp.amount}" required min="0">
                    </div>
                    <div class="col">
                        <label class="form-label font-weight-medium">Expected Close *</label>
                        <input type="date" class="form-control" name="expected_close_date" value="${opp.expected_close_date}" required>
                    </div>
                </div>
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Assigned Salesperson (ID)</label>
                    <input type="number" class="form-control" name="assigned_salesperson" value="${opp.assigned_salesperson || ''}">
                </div>
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Description</label>
                    <textarea class="form-control" name="description" rows="4">${opp.description || ''}</textarea>
                </div>
                <div class="d-flex gap-2 justify-content-end mt-4">
                    <button type="button" class="btn btn-light" id="cancelEditBtn">Cancel</button>
                    <button type="submit" class="btn btn-primary px-4">Save Changes</button>
                </div>
            </form>
        `;

        document.getElementById('cancelEditBtn').addEventListener('click', () => {
            leadDrawer.hide();
            setTimeout(() => openDetailsDrawer(opp.id), 300);
        });

        document.getElementById('editOppForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const body = Object.fromEntries(formData.entries());
            body.assigned_salesperson = body.assigned_salesperson ? parseInt(body.assigned_salesperson) : null;
            body.amount = parseFloat(body.amount);

            try {
                const response = await APIClient.patch(`/api/opportunities/${opp.id}/`, body);
                rawResponseEl.innerText = JSON.stringify(response, null, 2);
                if (response.success) {
                    leadDrawer.hide();
                    UIUtils.showAlert('mainAlertContainer', 'Opportunity updated successfully.');
                    loadOpportunities();
                    loadStats();
                }
            } catch (error) {
                rawResponseEl.innerText = JSON.stringify(error, null, 2);
                UIUtils.showAlert('mainAlertContainer', UIUtils.formatAPIError(error), 'danger');
            }
        });

        leadDrawer.show();
    }

    // --- Form Modal Submit ---
    stageForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const stage = stageSelect.value;
        const lost_reason = stage === 'CLOSED_LOST' ? lostReasonSelect.value : '';

        try {
            const response = await APIClient.post(`/api/opportunities/${activeOpportunityId}/change-stage/`, {
                stage,
                lost_reason
            });
            rawResponseEl.innerText = JSON.stringify(response, null, 2);
            if (response.success) {
                stageModal.hide();
                UIUtils.showAlert('mainAlertContainer', 'Opportunity stage updated successfully.');
                loadOpportunities();
                loadStats();
            }
        } catch (error) {
            rawResponseEl.innerText = JSON.stringify(error, null, 2);
            UIUtils.showAlert('mainAlertContainer', UIUtils.formatAPIError(error), 'danger');
        }
    });

    // --- Search & Filters Event Listeners ---
    function applyFilters() {
        currentPage = 1;
        loadOpportunities();
        loadStats();
    }

    searchBox.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 500);
    });

    filterStage.addEventListener('change', applyFilters);
    filterSource.addEventListener('change', applyFilters);
    filterOwner.addEventListener('change', applyFilters);

    // --- Table Ordering / Sorting click handlers ---
    document.querySelectorAll('th[data-ordering]').forEach(th => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
            const field = th.getAttribute('data-ordering');
            if (currentOrdering === field) {
                currentOrdering = `-${field}`;
            } else {
                currentOrdering = field;
            }
            loadOpportunities();
        });
    });

    // --- Pagination Actions ---
    prevPageBtn.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            loadOpportunities();
        }
    });

    nextPageBtn.addEventListener('click', () => {
        if (currentPage < totalPages) {
            currentPage++;
            loadOpportunities();
        }
    });

    // --- Initial Execution ---
    loadOpportunities();
    loadStats();
});
