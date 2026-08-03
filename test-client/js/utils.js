/**
 * Shared layout, formatting, and UI alert helpers.
 */
class UIUtils {
    /**
     * Formats dates into human-readable locale strings.
     */
    static formatDate(dateString) {
        if (!dateString) return 'N/A';
        const d = new Date(dateString);
        return d.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    /**
     * Standardizes badge labels for lead priorities.
     */
    static formatPriority(priority) {
        const val = (priority || '').toLowerCase();
        let cls = 'badge-priority-medium';
        if (val === 'low') cls = 'badge-priority-low';
        if (val === 'high') cls = 'badge-priority-high';
        return `<span class="badge ${cls} text-capitalize">${priority || 'Medium'}</span>`;
    }

    /**
     * Standardizes badge labels for lead statuses.
     */
    static formatStatus(status) {
        const val = (status || '').toLowerCase();
        const label = (status || '').replace('_', ' ');
        return `<span class="badge-status badge-status-${val} text-capitalize">${label || 'New'}</span>`;
    }

    /**
     * Renders standard Bootstrap alert blocks dynamically inside target container.
     */
    static showAlert(containerId, message, type = 'success') {
        const container = document.getElementById(containerId);
        if (!container) return;

        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show shadow-sm`;
        alertDiv.role = 'alert';
        alertDiv.innerHTML = `
            <div>${message}</div>
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        
        container.innerHTML = '';
        container.appendChild(alertDiv);

        // Auto-close after 5 seconds
        setTimeout(() => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alertDiv);
            if (bsAlert) bsAlert.close();
        }, 5000);
    }

    /**
     * Renders parsed JSON outputs into structured, color-coded HTML text blocks.
     */
    static syntaxHighlightJson(json) {
        if (typeof json !== 'string') {
            json = JSON.stringify(json, undefined, 4);
        }
        
        // Escape HTML tags to prevent cross-site execution
        json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        
        return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, function (match) {
            let cls = 'number';
            if (/^"/.test(match)) {
                if (/:$/.test(match)) {
                    cls = 'key';
                } else {
                    cls = 'string';
                }
            } else if (/true|false/.test(match)) {
                cls = 'boolean';
            } else if (/null/.test(match)) {
                cls = 'null';
            }
            return '<span class="' + cls + '">' + match + '</span>';
        });
    }

    /**
     * Shows a shared Lead Creation Form inside a drawer/offcanvas.
     * @param {Object} options
     * @param {HTMLElement} options.drawerEl - The offcanvas drawer element
     * @param {bootstrap.Offcanvas} options.bsDrawer - The Bootstrap Offcanvas instance
     * @param {number} [options.preselectedPipelineId] - Optional pipeline ID to preselect
     * @param {Array} [options.pipelinesList] - Optional pre-loaded pipelines list
     * @param {function} options.onSuccess - Callback triggered after successful lead creation
     */
    static async showLeadCreationDrawer({ drawerEl, bsDrawer, preselectedPipelineId = null, pipelinesList = null, onSuccess }) {
        const titleEl = drawerEl.querySelector('.offcanvas-title') || document.getElementById('drawerTitle');
        if (titleEl) titleEl.innerText = 'Add Lead';

        const bodyEl = drawerEl.querySelector('.offcanvas-body') || document.getElementById('drawerContent');
        if (!bodyEl) return;

        bodyEl.innerHTML = `
            <div class="text-center py-5 text-muted">
                <div class="spinner-border text-primary" role="status"></div>
                <div class="mt-2">Loading pipelines...</div>
            </div>
        `;
        bsDrawer.show();

        // 1. Fetch or reuse pipelines list
        let pipelines = pipelinesList;
        if (!pipelines || pipelines.length === 0) {
            try {
                const response = await APIClient.get('/api/pipelines/');
                if (Array.isArray(response)) {
                    pipelines = response;
                } else if (response && response.hasOwnProperty('success')) {
                    pipelines = response.data || [];
                } else if (response && response.results) {
                    pipelines = response.results;
                } else {
                    pipelines = [];
                }
            } catch (e) {
                console.error("Failed to load pipelines in drawer:", e);
                bodyEl.innerHTML = '<div class="alert alert-danger">Failed to load pipelines.</div>';
                return;
            }
        }

        let isAdminOrManager = false;
        try {
            const meRes = await APIClient.get('/api/me/');
            const meData = meRes.data || meRes;
            isAdminOrManager = meData.user_type === 'ADMIN';
        } catch (e) {
            console.error("Failed to load user profile via /api/me/:", e);
        }

        // Render form
        bodyEl.innerHTML = `
            <form id="leadForm">
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Full Name *</label>
                    <input type="text" class="form-control" name="full_name" required>
                </div>
                <div class="row mb-3">
                    <div class="col">
                        <label class="form-label font-weight-medium">Phone Number *</label>
                        <input type="text" class="form-control" name="phone" placeholder="+15551234" required>
                    </div>
                    <div class="col">
                        <label class="form-label font-weight-medium">Email Address</label>
                        <input type="email" class="form-control" name="email">
                    </div>
                </div>
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Company Name *</label>
                    <input type="text" class="form-control" name="company_name" required>
                </div>
                <!-- Company Information section -->
                <div class="card bg-light border p-3 mb-3">
                    <h6 class="font-weight-semibold mb-2" style="font-size: 0.85rem;">Company Information</h6>
                    <div class="mb-2">
                        <label class="form-label small mb-1">Website</label>
                        <input type="url" class="form-control form-control-sm" name="website" placeholder="https://example.com">
                    </div>
                    <div class="mb-2">
                        <label class="form-label small mb-1">Industry</label>
                        <select class="form-select form-select-sm" name="industry">
                            <option value="TECHNOLOGY">Technology</option>
                            <option value="FINANCE">Finance</option>
                            <option value="HEALTHCARE">Healthcare</option>
                            <option value="EDUCATION">Education</option>
                            <option value="RETAIL">Retail</option>
                            <option value="MANUFACTURING">Manufacturing</option>
                            <option value="OTHER" selected>Other</option>
                        </select>
                    </div>
                    <div class="row g-2">
                        <div class="col">
                            <label class="form-label small mb-1">Employees</label>
                            <input type="number" class="form-control form-control-sm" name="employee_count" min="0">
                        </div>
                        <div class="col">
                            <label class="form-label small mb-1">Annual Revenue</label>
                            <input type="number" step="0.01" class="form-control form-control-sm" name="annual_revenue" min="0">
                        </div>
                    </div>
                </div>
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Lead Source</label>
                    <select class="form-select" name="source">
                        <option value="WEBSITE">Website</option>
                        <option value="FACEBOOK">Facebook</option>
                        <option value="GOOGLE_ADS">Google Ads</option>
                        <option value="REFERRAL">Referral</option>
                        <option value="WALK_IN">Walk-in</option>
                        <option value="PHONE_CALL">Phone Call</option>
                        <option value="EMAIL_CAMPAIGN">Email Campaign</option>
                        <option value="OTHER" selected>Other</option>
                    </select>
                </div>
                ${isAdminOrManager ? `
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Assigned Salesperson</label>
                    <select class="form-select" name="assigned_salesperson">
                        <option value="">Unassigned</option>
                        <option value="1">Admin</option>
                        <option value="2">Sales Manager</option>
                        <option value="3">Salesperson 1</option>
                        <option value="4">Salesperson 2</option>
                    </select>
                </div>
                ` : ''}
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Pipeline *</label>
                    <select class="form-select" name="pipeline" id="leadFormPipelineSelect" required>
                        <!-- Pipelines options will go here -->
                    </select>
                    <div class="mt-2" id="firstStageHelper"></div>
                </div>
                <div class="mb-3">
                    <label class="form-label font-weight-medium">Notes</label>
                    <textarea class="form-control" name="notes" rows="3"></textarea>
                </div>
                <div id="drawerAlertContainer" class="mb-3"></div>
                <div class="d-flex gap-2 justify-content-end mt-4">
                    <button type="button" class="btn btn-light" data-bs-dismiss="offcanvas">Cancel</button>
                    <button type="submit" class="btn btn-primary px-4" id="saveLeadFormBtn">Save Lead</button>
                </div>
            </form>
        `;

        const pipelineSelect = bodyEl.querySelector('#leadFormPipelineSelect');
        const helperEl = bodyEl.querySelector('#firstStageHelper');

        // Populate dropdown
        pipelines.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            pipelineSelect.appendChild(opt);
        });

        // Set default selection
        let selectedPipelineId = preselectedPipelineId;
        if (!selectedPipelineId) {
            const defaultPipeline = pipelines.find(p => p.is_default);
            selectedPipelineId = defaultPipeline ? defaultPipeline.id : (pipelines.length > 0 ? pipelines[0].id : null);
        }
        if (selectedPipelineId) {
            pipelineSelect.value = selectedPipelineId;
        }

        // Setup stage caching
        if (!UIUtils.stagesCache) {
            UIUtils.stagesCache = {};
        }
        const stagesCache = UIUtils.stagesCache;

        async function updateFirstStageHelper(pipelineId) {
            if (!pipelineId) {
                helperEl.innerHTML = '';
                return;
            }
            
            helperEl.innerHTML = '<span class="spinner-border spinner-border-sm text-secondary me-2"></span>Loading stage details...';

            if (stagesCache[pipelineId]) {
                const firstStageName = stagesCache[pipelineId];
                helperEl.innerHTML = `<span class="text-muted small">Lead will be created in: <strong>${firstStageName}</strong> (first stage of the selected pipeline)</span>`;
                return;
            }

            try {
                const stagesRes = await APIClient.get(`/api/pipeline/stages/?pipeline=${pipelineId}`);
                let stages = [];
                if (Array.isArray(stagesRes)) stages = stagesRes;
                else if (stagesRes && stagesRes.data) stages = stagesRes.data;
                else if (stagesRes && stagesRes.results) stages = stagesRes.results;
                
                stages.sort((a, b) => a.order - b.order);
                if (stages.length > 0) {
                    const firstStageName = stages[0].name;
                    stagesCache[pipelineId] = firstStageName; // Cache it!
                    helperEl.innerHTML = `<span class="text-muted small">Lead will be created in: <strong>${firstStageName}</strong> (first stage of the selected pipeline)</span>`;
                } else {
                    helperEl.innerHTML = '<span class="text-danger small">⚠️ Selected pipeline has no active stages configured.</span>';
                }
            } catch (err) {
                helperEl.innerHTML = '<span class="text-warning small">⚠️ Unable to verify pipeline stages.</span>';
            }
        }

        // Initialize helper status
        if (pipelineSelect.value) {
            updateFirstStageHelper(pipelineSelect.value);
        }

        pipelineSelect.addEventListener('change', () => {
            updateFirstStageHelper(pipelineSelect.value);
        });

        // Submit binding
        const form = bodyEl.querySelector('#leadForm');
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const saveBtn = bodyEl.querySelector('#saveLeadFormBtn');
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Saving...';

            const formData = new FormData(form);
            const body = Object.fromEntries(formData.entries());
            if (body.pipeline) {
                body.pipeline = parseInt(body.pipeline);
            }
            if (body.assigned_salesperson) {
                body.assigned_salesperson = parseInt(body.assigned_salesperson, 10);
            } else {
                delete body.assigned_salesperson;
            }
            if (body.employee_count) {
                body.employee_count = parseInt(body.employee_count, 10);
            } else {
                delete body.employee_count;
            }
            if (body.annual_revenue) {
                body.annual_revenue = parseFloat(body.annual_revenue);
            } else {
                delete body.annual_revenue;
            }

            try {
                const response = await APIClient.post('/api/leads/', body);
                if (response.success) {
                    bsDrawer.hide();
                    if (onSuccess) {
                        onSuccess(response.data || response);
                    }
                }
            } catch (err) {
                UIUtils.showAlert('drawerAlertContainer', err.message || 'Validation failed during creation.', 'danger');
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Lead';
            }
        });
    }
}

// Bind to window to allow global reuse across modules
window.UIUtils = UIUtils;
