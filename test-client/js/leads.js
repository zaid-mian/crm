/**
 * Lead Module Dashboard Controller.
 * Manages queries, page state transitions, modal handlers, and the developer debug console.
 */
document.addEventListener('DOMContentLoaded', () => {
    // Check global settings base URL
    if (!localStorage.getItem('api_base_url')) {
        localStorage.setItem('api_base_url', 'http://localhost:8000');
    }

    // Dashboard State
    let currentPage = 1;
    let currentFilters = {
        status: '',
        priority: '',
        source: '',
        assigned_salesperson: '',
        search: ''
    };
    let currentOrdering = '-created_at';
    let activeLeadId = null;

    // Bootstrap Instances
    const leadDrawerEl = document.getElementById('leadDrawer');
    const leadDrawer = new bootstrap.Offcanvas(leadDrawerEl);
    
    const convertModalEl = document.getElementById('convertModal');
    const convertModal = new bootstrap.Modal(convertModalEl);
    
    const lostModalEl = document.getElementById('lostModal');
    const lostModal = new bootstrap.Modal(lostModalEl);

    // --- Developer debug panel Logging Handler ---
    const logList = document.getElementById('logList');
    const detailViewer = document.getElementById('requestDetailViewer');
    
    const authMethodSelect = document.getElementById('authMethodOverride');
    const tokenInput = document.getElementById('authTokenOverride');
    const usernameInput = document.getElementById('authUsernameOverride');
    const passwordInput = document.getElementById('authPasswordOverride');
    
    const tokenGroup = document.getElementById('tokenOverrideGroup');
    const basicGroup = document.getElementById('basicOverrideGroup');

    function updateOverrideVisibility() {
        const method = authMethodSelect.value;
        tokenGroup.classList.add('d-none');
        basicGroup.classList.add('d-none');
        
        if (method === 'token') tokenGroup.classList.remove('d-none');
        if (method === 'basic') basicGroup.classList.remove('d-none');
    }

    let authReloadTimeout = null;
    function triggerAuthReload() {
        clearTimeout(authReloadTimeout);
        authReloadTimeout = setTimeout(() => {
            loadLeads();
            loadStats();
        }, 600); // 600ms debounce to wait for typing pause
    }

    authMethodSelect.addEventListener('change', () => {
        localStorage.setItem('auth_method', authMethodSelect.value);
        updateOverrideVisibility();
        triggerAuthReload();
    });

    tokenInput.addEventListener('input', () => {
        localStorage.setItem('auth_token', tokenInput.value.trim());
        triggerAuthReload();
    });

    usernameInput.addEventListener('input', () => {
        localStorage.setItem('auth_username', usernameInput.value.trim());
        triggerAuthReload();
    });

    passwordInput.addEventListener('input', () => {
        localStorage.setItem('auth_password', passwordInput.value.trim());
        triggerAuthReload();
    });

    // Initialize values from localStorage
    authMethodSelect.value = localStorage.getItem('auth_method') || 'basic';
    tokenInput.value = localStorage.getItem('auth_token') || '';
    usernameInput.value = localStorage.getItem('auth_username') || '';
    passwordInput.value = localStorage.getItem('auth_password') || '';
    updateOverrideVisibility();

    window.addEventListener('crm-api-log', (event) => {
        const log = event.detail;
        
        // 1. Create console list log item
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

        // 2. Add click listener to render full details in the Viewer
        item.addEventListener('click', () => {
            renderRequestDetails(log);
            // Highlight selected log item
            document.querySelectorAll('.log-item').forEach(el => el.classList.remove('active'));
            item.classList.add('active');
        });

        // Prepend to list
        logList.insertBefore(item, logList.firstChild);

        // Limit log items to 50
        while (logList.children.length > 50) {
            logList.removeChild(logList.lastChild);
        }

        // By default, display the most recent request details
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
                <strong class="small text-muted text-uppercase">Request Headers:</strong>
                <pre class="json-viewer p-2 text-wrap" style="max-height: 120px;">${JSON.stringify(log.headers, null, 2)}</pre>
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

    // --- Core API Data Fetching ---
    async function loadStats() {
        try {
            // Build query params based on permission scope filters
            let query = '?';
            if (currentFilters.assigned_salesperson) query += `assigned_salesperson=${currentFilters.assigned_salesperson}&`;
            
            const response = await APIClient.get(`/api/leads/stats/${query}`);
            if (response.success) {
                const data = response.data;
                document.getElementById('statTotal').innerText = data.total_leads || 0;
                document.getElementById('statNew').innerText = data.status_counts.NEW || 0;
                document.getElementById('statQualified').innerText = data.status_counts.QUALIFIED || 0;
                document.getElementById('statConverted').innerText = data.status_counts.CONVERTED || 0;
                document.getElementById('statLost').innerText = data.status_counts.LOST || 0;
            }
        } catch (error) {
            console.error("Failed to load statistics:", error);
        }
    }

    async function loadLeads() {
        try {
            // Build query filter parameters
            let query = `?page=${currentPage}&ordering=${currentOrdering}`;
            
            if (currentFilters.status) query += `&status=${currentFilters.status}`;
            if (currentFilters.priority) query += `&priority=${currentFilters.priority}`;
            if (currentFilters.source) query += `&source=${currentFilters.source}`;
            if (currentFilters.assigned_salesperson) query += `&assigned_salesperson=${currentFilters.assigned_salesperson}`;
            if (currentFilters.search) query += `&search=${encodeURIComponent(currentFilters.search)}`;

            const response = await APIClient.get(`/api/leads/${query}`);
            if (response.success) {
                renderLeadsTable(response.data.results);
                renderPagination(response.data.pagination);
            }
        } catch (error) {
            UIUtils.showAlert('mainAlertContainer', error.message || 'Error loading lead records.', 'danger');
        }
    }

    // --- Table & Pagination UI Drawing ---
    function renderLeadsTable(leads) {
        const tbody = document.getElementById('leadsTableBody');
        tbody.innerHTML = '';

        if (!leads || leads.length === 0) {
            tbody.innerHTML = `<tr><td colspan="10" class="text-center py-4 text-muted">No leads matched your search query.</td></tr>`;
            return;
        }

        leads.forEach((lead, index) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="align-middle small font-monospace">${(currentPage - 1) * 20 + index + 1}</td>
                <td class="align-middle font-monospace text-primary font-weight-medium">${lead.lead_code || 'N/A'}</td>
                <td class="align-middle font-weight-medium">${lead.full_name}</td>
                <td class="align-middle text-secondary small">${lead.company_name}</td>
                <td class="align-middle small">${lead.phone}</td>
                <td class="align-middle text-secondary small">${lead.source}</td>
                <td class="align-middle text-secondary small">User #${lead.assigned_salesperson || 'Unassigned'}</td>
                <td class="align-middle">${UIUtils.formatPriority(lead.priority)}</td>
                <td class="align-middle">${UIUtils.formatStatus(lead.status)}</td>
                <td class="align-middle text-end">
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-secondary btn-view" data-id="${lead.id}">View</button>
                        <button class="btn btn-outline-primary btn-edit" data-id="${lead.id}" ${lead.is_converted ? 'disabled' : ''}>Edit</button>
                        <button class="btn btn-outline-success btn-convert" data-id="${lead.id}" ${lead.is_converted || lead.status === 'LOST' ? 'disabled' : ''}>Convert</button>
                        <button class="btn btn-outline-danger btn-lost" data-id="${lead.id}" ${lead.is_converted ? 'disabled' : ''}>Mark Lost</button>
                    </div>
                </td>
            `;

            // Attach action handlers
            tr.querySelector('.btn-view').addEventListener('click', () => openViewDrawer(lead.id));
            tr.querySelector('.btn-edit').addEventListener('click', () => openEditDrawer(lead.id));
            tr.querySelector('.btn-convert').addEventListener('click', () => openConvertModal(lead.id));
            tr.querySelector('.btn-lost').addEventListener('click', () => openLostModal(lead.id));

            tbody.appendChild(tr);
        });
    }

    function renderPagination(pagination) {
        const pagContainer = document.getElementById('leadsPagination');
        pagContainer.innerHTML = '';

        if (!pagination || pagination.total_pages <= 1) return;

        const ul = document.createElement('ul');
        ul.className = 'pagination pagination-sm mb-0 justify-content-end';

        // Previous Button
        const prevLi = document.createElement('li');
        prevLi.className = `page-item ${pagination.previous ? '' : 'disabled'}`;
        prevLi.innerHTML = `<a class="page-link" href="#" aria-label="Previous">&laquo;</a>`;
        prevLi.addEventListener('click', (e) => {
            e.preventDefault();
            if (pagination.previous) {
                currentPage--;
                loadLeads();
            }
        });
        ul.appendChild(prevLi);

        // Page Numbers
        for (let i = 1; i <= pagination.total_pages; i++) {
            const li = document.createElement('li');
            li.className = `page-item ${pagination.page === i ? 'active' : ''}`;
            li.innerHTML = `<a class="page-link" href="#">${i}</a>`;
            li.addEventListener('click', (e) => {
                e.preventDefault();
                currentPage = i;
                loadLeads();
            });
            ul.appendChild(li);
        }

        // Next Button
        const nextLi = document.createElement('li');
        nextLi.className = `page-item ${pagination.next ? '' : 'disabled'}`;
        nextLi.innerHTML = `<a class="page-link" href="#" aria-label="Next">&raquo;</a>`;
        nextLi.addEventListener('click', (e) => {
            e.preventDefault();
            if (pagination.next) {
                currentPage++;
                loadLeads();
            }
        });
        ul.appendChild(nextLi);

        pagContainer.appendChild(ul);
    }

    // --- Search & Filters Binding ---
    const searchInput = document.getElementById('searchBox');
    const filterStatus = document.getElementById('filterStatus');
    const filterSource = document.getElementById('filterSource');
    const filterPriority = document.getElementById('filterPriority');
    const filterOwner = document.getElementById('filterOwner');

    function applyFilters() {
        currentFilters.status = filterStatus.value;
        currentFilters.source = filterSource.value;
        currentFilters.priority = filterPriority.value;
        currentFilters.assigned_salesperson = filterOwner.value;
        currentFilters.search = searchInput.value.trim();
        currentPage = 1;
        
        loadLeads();
        loadStats();
    }

    // Bind event handlers
    let searchTimeout = null;
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 500); // debounce search input
    });

    filterStatus.addEventListener('change', applyFilters);
    filterSource.addEventListener('change', applyFilters);
    filterPriority.addEventListener('change', applyFilters);
    filterOwner.addEventListener('change', applyFilters);

    // Sorting Click Handlers
    document.querySelectorAll('th[data-ordering]').forEach(th => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
            const field = th.getAttribute('data-ordering');
            if (currentOrdering === field) {
                // Toggle to descending
                currentOrdering = `-${field}`;
            } else {
                currentOrdering = field;
            }
            loadLeads();
        });
    });

    // --- Add/Create Lead Workflow ---
    document.getElementById('addLeadBtn').addEventListener('click', () => {
        activeLeadId = null;
        
        UIUtils.showLeadCreationDrawer({
            drawerEl: document.getElementById('leadDrawer'),
            bsDrawer: leadDrawer,
            onSuccess: (lead) => {
                UIUtils.showAlert('mainAlertContainer', 'Lead created successfully.');
                loadLeads();
                loadStats();
            }
        });
    });

    // --- View Lead Workflow ---
    async function openViewDrawer(id) {
        activeLeadId = id;
        document.getElementById('drawerTitle').innerText = 'Lead Profile';
        
        try {
            const response = await APIClient.get(`/api/leads/${id}/`);
            if (response.success) {
                const lead = response.data;
                
                document.getElementById('drawerContent').innerHTML = `
                    <div class="card bg-light border-0 mb-4">
                        <div class="card-body">
                            <div class="mb-2 font-monospace text-muted small">${lead.lead_code || 'N/A'}</div>
                            <h4 class="mb-3 text-dark">${lead.full_name}</h4>
                            <div class="mb-2"><strong>Company:</strong> ${lead.company_name}</div>
                            ${lead.website ? `<div class="mb-2"><strong>Website:</strong> <a href="${lead.website}" target="_blank" class="small text-truncate d-inline-block" style="max-width: 180px; vertical-align: bottom;">${lead.website}</a></div>` : ''}
                            ${lead.industry && lead.industry !== 'OTHER' ? `<div class="mb-2"><strong>Industry:</strong> ${lead.industry}</div>` : ''}
                            ${lead.employee_count ? `<div class="mb-2"><strong>Employees:</strong> ${lead.employee_count}</div>` : ''}
                            ${lead.annual_revenue ? `<div class="mb-2"><strong>Annual Revenue:</strong> $${parseFloat(lead.annual_revenue).toLocaleString()}</div>` : ''}
                            <div class="mb-2"><strong>Phone:</strong> ${lead.phone}</div>
                            <div class="mb-2"><strong>Email:</strong> ${lead.email || 'None'}</div>
                            <div class="mb-2"><strong>Status:</strong> ${UIUtils.formatStatus(lead.status)}</div>
                            <div class="mb-2"><strong>Priority:</strong> ${UIUtils.formatPriority(lead.priority)}</div>
                        </div>
                    </div>
                    
                    <!-- Salesperson Owner assignment controls -->
                    <div class="mb-4">
                        <label class="form-label font-weight-medium small text-muted text-uppercase">Assigned Salesperson (RBAC Test)</label>
                        <div class="input-group">
                            <select class="form-select" id="leadOwnerSelect">
                                <option value="" ${!lead.assigned_salesperson ? 'selected' : ''}>Unassigned</option>
                                <option value="1" ${lead.assigned_salesperson === 1 ? 'selected' : ''}>Salesperson #1</option>
                                <option value="2" ${lead.assigned_salesperson === 2 ? 'selected' : ''}>Salesperson #2</option>
                                <option value="3" ${lead.assigned_salesperson === 3 ? 'selected' : ''}>Salesperson #3</option>
                            </select>
                            <button class="btn btn-outline-secondary" id="saveOwnerBtn">Re-assign</button>
                        </div>
                    </div>

                    <!-- Description/Notes -->
                    <div class="mb-4">
                        <h6 class="border-bottom pb-2 font-weight-semibold">Lead Notes</h6>
                        <p class="text-secondary bg-light p-3 rounded small">${lead.notes || 'No description notes available.'}</p>
                    </div>

                    <!-- Action buttons -->
                    <div class="d-flex gap-2 justify-content-start border-bottom pb-4 mb-4">
                        <button class="btn btn-primary" id="viewEditBtn" ${lead.is_converted ? 'disabled' : ''}>Edit Lead</button>
                        <button class="btn btn-success" id="viewConvertBtn" ${lead.is_converted || lead.status === 'LOST' ? 'disabled' : ''}>Convert</button>
                        <button class="btn btn-danger" id="viewLostBtn" ${lead.is_converted ? 'disabled' : ''}>Mark Lost</button>
                        <button class="btn btn-warning text-white" id="viewContactedBtn" ${lead.is_converted || lead.status === 'LOST' || lead.status === 'CONTACTED' || lead.status === 'CONVERTED' ? 'disabled' : ''}>Mark Contacted</button>
                    </div>

                    <!-- Related modules activities & tasks placeholders (empty) -->
                    <div class="mb-4">
                        <h6 class="font-weight-semibold">Activity Timeline</h6>
                        <div class="timeline p-3">
                            <div class="text-muted small">No activities logged yet. (Activity Log module is planned for Phase 2).</div>
                        </div>
                    </div>

                    <div class="mb-4">
                        <h6 class="font-weight-semibold">Related Tasks</h6>
                        <ul class="list-group list-group-flush border rounded">
                            <li class="list-group-item text-muted small py-3">No pending tasks. (Tasks module is planned for Phase 2).</li>
                        </ul>
                    </div>
                `;

                // Bind view details action buttons
                document.getElementById('saveOwnerBtn').addEventListener('click', () => {
                    const ownerId = document.getElementById('leadOwnerSelect').value;
                    handleAssignOwner(lead.id, ownerId);
                });

                document.getElementById('viewEditBtn').addEventListener('click', () => {
                    leadDrawer.hide();
                    setTimeout(() => openEditDrawer(lead.id), 300);
                });
                
                document.getElementById('viewConvertBtn').addEventListener('click', () => {
                    leadDrawer.hide();
                    setTimeout(() => openConvertModal(lead.id), 300);
                });

                document.getElementById('viewContactedBtn').addEventListener('click', async () => {
                    try {
                        const response = await APIClient.post(`/api/leads/${lead.id}/contacted/`);
                        if (response.success) {
                            leadDrawer.hide();
                            UIUtils.showAlert('mainAlertContainer', 'Lead marked as Contacted.');
                            loadLeads();
                        }
                    } catch (error) {
                        UIUtils.showAlert('mainAlertContainer', error.message || 'Failed to mark contacted.', 'danger');
                    }
                });
                
                document.getElementById('viewLostBtn').addEventListener('click', () => {
                    leadDrawer.hide();
                    setTimeout(() => openLostModal(lead.id), 300);
                });

                leadDrawer.show();
            }
        } catch (error) {
            UIUtils.showAlert('mainAlertContainer', error.message || 'Failed to load details.', 'danger');
        }
    }

    // Owner Assignment API handler
    async function handleAssignOwner(leadId, ownerId) {
        try {
            const body = { assigned_salesperson: ownerId ? parseInt(ownerId) : null };
            const response = await APIClient.post(`/api/leads/${leadId}/assign/`, body);
            if (response.success) {
                leadDrawer.hide();
                UIUtils.showAlert('mainAlertContainer', 'Lead assigned successfully.');
                loadLeads();
            }
        } catch (error) {
            UIUtils.showAlert('mainAlertContainer', error.message || 'Failed to update owner.', 'danger');
        }
    }

    // --- Edit Lead Workflow ---
    async function openEditDrawer(id) {
        activeLeadId = id;
        document.getElementById('drawerTitle').innerText = 'Edit Lead';
        
        try {
            const response = await APIClient.get(`/api/leads/${id}/`);
            if (response.success) {
                const lead = response.data;
                
                document.getElementById('drawerContent').innerHTML = `
                    <form id="editLeadForm">
                        <div class="mb-3">
                            <label class="form-label font-weight-medium">Full Name *</label>
                            <input type="text" class="form-control" name="full_name" value="${lead.full_name}" required>
                        </div>
                        <div class="row mb-3">
                            <div class="col">
                                <label class="form-label font-weight-medium">Phone Number</label>
                                <input type="text" class="form-control" name="phone" value="${lead.phone}">
                            </div>
                            <div class="col">
                                <label class="form-label font-weight-medium">Email Address</label>
                                <input type="email" class="form-control" name="email" value="${lead.email || ''}">
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label font-weight-medium">Company Name *</label>
                            <input type="text" class="form-control" name="company_name" value="${lead.company_name}" required>
                        </div>
                        <!-- Company Information section -->
                        <div class="card bg-light border p-3 mb-3">
                            <h6 class="font-weight-semibold mb-2" style="font-size: 0.85rem;">Company Information</h6>
                            <div class="mb-2">
                                <label class="form-label small mb-1">Website</label>
                                <input type="url" class="form-control form-control-sm" name="website" placeholder="https://example.com" value="${lead.website || ''}">
                            </div>
                            <div class="mb-2">
                                <label class="form-label small mb-1">Industry</label>
                                <select class="form-select form-select-sm" name="industry">
                                    <option value="TECHNOLOGY" ${lead.industry === 'TECHNOLOGY' ? 'selected' : ''}>Technology</option>
                                    <option value="FINANCE" ${lead.industry === 'FINANCE' ? 'selected' : ''}>Finance</option>
                                    <option value="HEALTHCARE" ${lead.industry === 'HEALTHCARE' ? 'selected' : ''}>Healthcare</option>
                                    <option value="EDUCATION" ${lead.industry === 'EDUCATION' ? 'selected' : ''}>Education</option>
                                    <option value="RETAIL" ${lead.industry === 'RETAIL' ? 'selected' : ''}>Retail</option>
                                    <option value="MANUFACTURING" ${lead.industry === 'MANUFACTURING' ? 'selected' : ''}>Manufacturing</option>
                                    <option value="OTHER" ${lead.industry === 'OTHER' || !lead.industry ? 'selected' : ''}>Other</option>
                                </select>
                            </div>
                            <div class="row g-2">
                                <div class="col">
                                    <label class="form-label small mb-1">Employees</label>
                                    <input type="number" class="form-control form-control-sm" name="employee_count" min="0" value="${lead.employee_count !== null && lead.employee_count !== undefined ? lead.employee_count : ''}">
                                </div>
                                <div class="col">
                                    <label class="form-label small mb-1">Annual Revenue</label>
                                    <input type="number" step="0.01" class="form-control form-control-sm" name="annual_revenue" min="0" value="${lead.annual_revenue !== null && lead.annual_revenue !== undefined ? lead.annual_revenue : ''}">
                                </div>
                            </div>
                        </div>
                        <div class="row mb-3">
                            <div class="col">
                                <label class="form-label font-weight-medium">Lead Source</label>
                                <select class="form-select" name="source">
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
                            <div class="col">
                                <label class="form-label font-weight-medium">Priority</label>
                                <select class="form-select" name="priority">
                                    <option value="LOW" ${lead.priority === 'LOW' ? 'selected' : ''}>Low</option>
                                    <option value="MEDIUM" ${lead.priority === 'MEDIUM' ? 'selected' : ''}>Medium</option>
                                    <option value="HIGH" ${lead.priority === 'HIGH' ? 'selected' : ''}>High</option>
                                </select>
                            </div>
                        </div>
                        <div class="row mb-3">
                            <div class="col">
                                <label class="form-label font-weight-medium">Contact Attempts</label>
                                <input type="number" class="form-control" name="contact_attempts" value="${lead.contact_attempts}" min="0">
                            </div>
                            <div class="col">
                                <label class="form-label font-weight-medium">Last Contact Date</label>
                                <input type="datetime-local" class="form-control" name="last_contact_date" value="${lead.last_contact_date ? lead.last_contact_date.substring(0,16) : ''}">
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label font-weight-medium">Notes</label>
                            <textarea class="form-control" name="notes" rows="3">${lead.notes || ''}</textarea>
                        </div>
                        <div class="d-flex gap-2 justify-content-end mt-4">
                            <button type="button" class="btn btn-light" data-bs-dismiss="offcanvas">Cancel</button>
                            <button type="submit" class="btn btn-primary px-4">Save Changes</button>
                        </div>
                    </form>
                `;

                document.getElementById('editLeadForm').addEventListener('submit', handleEditSubmit);
                leadDrawer.show();
            }
        } catch (error) {
            UIUtils.showAlert('mainAlertContainer', error.message || 'Failed to load editor data.', 'danger');
        }
    }

    async function handleEditSubmit(e) {
        e.preventDefault();
        const formData = new FormData(e.target);
        const body = Object.fromEntries(formData.entries());
        
        // Clean formats
        body.contact_attempts = parseInt(body.contact_attempts) || 0;
        if (!body.last_contact_date) {
            body.last_contact_date = null;
        }
        if (body.employee_count) {
            body.employee_count = parseInt(body.employee_count, 10);
        } else {
            body.employee_count = null;
        }
        if (body.annual_revenue) {
            body.annual_revenue = parseFloat(body.annual_revenue);
        } else {
            body.annual_revenue = null;
        }

        try {
            const response = await APIClient.put(`/api/leads/${activeLeadId}/`, body);
            if (response.success) {
                leadDrawer.hide();
                UIUtils.showAlert('mainAlertContainer', 'Lead updated successfully.');
                loadLeads();
            }
        } catch (error) {
            UIUtils.showAlert('mainAlertContainer', error.message || 'Failed to save changes.', 'danger');
        }
    }

    // --- Convert Lead Modal Workflow ---
    function openConvertModal(id) {
        activeLeadId = id;
        convertModal.show();
    }

    document.getElementById('confirmConvertBtn').addEventListener('click', async () => {
        try {
            const response = await APIClient.post(`/api/leads/${activeLeadId}/convert/`);
            if (response.success) {
                convertModal.hide();
                UIUtils.showAlert('mainAlertContainer', 'Lead successfully converted. (Entities mapped inside CRM).');
                loadLeads();
                loadStats();
            }
        } catch (error) {
            convertModal.hide();
            UIUtils.showAlert('mainAlertContainer', error.message || 'Failed to convert lead.', 'danger');
        }
    });

    // --- Mark Lead Lost Modal Workflow ---
    function openLostModal(id) {
        activeLeadId = id;
        // Reset form inputs
        document.getElementById('lostReasonSelect').value = 'NOT_INTERESTED';
        document.getElementById('lostNotesInput').value = '';
        lostModal.show();
    }

    document.getElementById('confirmLostBtn').addEventListener('click', async () => {
        const reason = document.getElementById('lostReasonSelect').value;
        const notes = document.getElementById('lostNotesInput').value.trim();

        try {
            const body = { lost_reason: reason, lost_notes: notes };
            const response = await APIClient.post(`/api/leads/${activeLeadId}/lost/`, body);
            if (response.success) {
                lostModal.hide();
                UIUtils.showAlert('mainAlertContainer', 'Lead successfully marked as Lost.');
                loadLeads();
                loadStats();
            }
        } catch (error) {
            lostModal.hide();
            UIUtils.showAlert('mainAlertContainer', error.message || 'Failed to update lost details.', 'danger');
        }
    });

    // --- Initialization ---
    loadLeads();
    loadStats();
});
