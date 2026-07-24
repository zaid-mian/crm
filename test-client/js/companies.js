document.addEventListener('DOMContentLoaded', () => {
    // --- State Variables ---
    let companies = [];
    let currentPage = 1;
    let totalPages = 1;
    let currentOrdering = '-created_at';
    let searchTimeout = null;

    // --- UI Elements ---
    const searchBox = document.getElementById('searchBox');
    const filterType = document.getElementById('filterType');
    const filterRating = document.getElementById('filterRating');
    const filterIndustry = document.getElementById('filterIndustry');
    const filterOwner = document.getElementById('filterOwner');

    const companyTable = document.getElementById('companyTable');
    const companyTableBody = companyTable.querySelector('tbody');

    const paginationDisplay = document.getElementById('paginationDisplay');
    const paginationNav = document.getElementById('paginationNav');

    // Forms
    const companyForm = document.getElementById('companyForm');
    const companyIdInput = document.getElementById('companyId');
    const companyNameInput = document.getElementById('companyName');
    const companyEmailInput = document.getElementById('companyEmail');
    const companyPhoneInput = document.getElementById('companyPhone');
    const companyWebsiteInput = document.getElementById('companyWebsite');
    const companyTypeSelect = document.getElementById('companyType');
    const companyRatingSelect = document.getElementById('companyRating');
    const companyIndustrySelect = document.getElementById('companyIndustry');
    const companyRevenueInput = document.getElementById('companyRevenue');
    const companyEmployeesInput = document.getElementById('companyEmployees');
    const companyOwnerInput = document.getElementById('companyOwner');
    const companyDescriptionInput = document.getElementById('companyDescription');

    const formTitle = document.getElementById('formTitle');
    const saveBtn = document.getElementById('saveBtn');
    const cancelBtn = document.getElementById('cancelBtn');

    // Profile Display Card
    const companyProfileCard = document.getElementById('companyProfileCard');
    const closeProfileBtn = document.getElementById('closeProfileBtn');

    // Console logging
    const clearConsoleBtn = document.getElementById('clearConsoleBtn');
    const consoleOutput = document.getElementById('consoleOutput');

    // --- REST Helper Agent ---
    const RESTClient = {
        async request(method, path, body = null) {
            return window.APIClient.request(method, path, body);
        }
    };

    // Listen to global API logs to populate the console output
    window.addEventListener('crm-api-log', (event) => {
        const { method, url, requestBody, status, responseBody } = event.detail;
        let path = url;
        const baseUrl = window.APIClient.getBaseUrl();
        if (url.startsWith(baseUrl)) {
            path = url.substring(baseUrl.length);
        }
        logToConsole(method, path, requestBody, status, responseBody);
    });

    // --- Formatting Helpers ---
    const formatCurrency = (val) => {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0);
    };

    const formatRatingBadge = (rating) => {
        const mappings = {
            'HOT': '<span class="badge bg-danger">Hot</span>',
            'WARM': '<span class="badge bg-warning text-dark">Warm</span>',
            'COLD': '<span class="badge bg-info text-dark">Cold</span>',
            'NONE': '<span class="badge bg-secondary">None</span>'
        };
        return mappings[rating] || `<span class="badge bg-light text-dark">${rating}</span>`;
    };

    const formatTypeBadge = (type) => {
        const mappings = {
            'PROSPECT': '<span class="badge bg-secondary text-uppercase">Prospect</span>',
            'CUSTOMER': '<span class="badge bg-success text-uppercase">Customer</span>',
            'PARTNER': '<span class="badge bg-info text-dark text-uppercase">Partner</span>',
            'COMPETITOR': '<span class="badge bg-danger text-uppercase">Competitor</span>',
            'OTHER': '<span class="badge bg-light text-dark text-uppercase">Other</span>'
        };
        return mappings[type] || `<span class="badge bg-light text-dark text-uppercase">${type}</span>`;
    };

    // --- REST Console Log Appender ---
    function logToConsole(method, url, reqBody, status, resBody) {
        if (!consoleOutput) return;
        const placeholder = consoleOutput.querySelector('.text-secondary');
        if (placeholder) placeholder.remove();

        const badgeClass = status >= 200 && status < 300 ? 'bg-success' : 'bg-danger';
        const timestamp = new Date().toLocaleTimeString();

        const logEntry = document.createElement('div');
        logEntry.className = 'border-bottom border-secondary border-opacity-25 pb-2 mb-2';
        logEntry.innerHTML = `
            <div class="d-flex justify-content-between mb-1">
                <span><strong>[${timestamp}]</strong> <span class="badge ${badgeClass}">${method}</span> <code class="text-info">${url}</code></span>
                <span class="text-muted">Status: ${status}</span>
            </div>
            ${reqBody ? `<div class="text-warning mb-1"><strong>Request Body:</strong> <code>${JSON.stringify(reqBody)}</code></div>` : ''}
            <div><strong>Response Output:</strong> <pre class="mb-0 text-light mt-1">${window.UIUtils.syntaxHighlightJson(resBody)}</pre></div>
        `;
        consoleOutput.appendChild(logEntry);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    }

    clearConsoleBtn.addEventListener('click', () => {
        consoleOutput.innerHTML = '<div class="text-secondary">[Console cleared, awaiting actions...]</div>';
    });

    // --- Parsing and Formatting API Errors ---
    function parseAPIError(err) {
        if (err && typeof err === 'object') {
            if (err.errors && typeof err.errors === 'object') {
                const list = [];
                for (const [key, val] of Object.entries(err.errors)) {
                    const label = key === 'non_field_errors' ? '' : `${key}: `;
                    list.push(`${label}${Array.isArray(val) ? val.join(', ') : val}`);
                }
                return list.join(' | ');
            }
            if (err.detail) {
                return err.detail;
            }
            if (err.message) {
                return err.message;
            }
        }
        return 'An unexpected error occurred.';
    }

    // --- Load Companies list ---
    async function loadCompanies() {
        try {
            const params = new URLSearchParams();
            params.append('page', currentPage);
            params.append('ordering', currentOrdering);

            if (searchBox.value.trim()) {
                params.append('search', searchBox.value.trim());
            }
            if (filterType.value) {
                params.append('type', filterType.value);
            }
            if (filterRating.value) {
                params.append('rating', filterRating.value);
            }
            if (filterIndustry.value) {
                params.append('industry', filterIndustry.value);
            }
            if (filterOwner.value) {
                params.append('assigned_salesperson', filterOwner.value);
            }

            const path = `/api/companies/?${params.toString()}`;
            const response = await RESTClient.request('GET', path);

            if (response.success && response.data) {
                companies = response.data.results || [];
                renderTable();
                updatePaginationControls(response.data.pagination);
                calculateClientStats(companies);
            }
        } catch (error) {
            window.UIUtils.showAlert('mainAlertContainer', parseAPIError(error), 'danger');
        }
    }

    // --- Render list table ---
    function renderTable() {
        if (companies.length === 0) {
            companyTableBody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center py-4 text-secondary">
                        No companies found matching search filters.
                    </td>
                </tr>
            `;
            return;
        }

        companyTableBody.innerHTML = companies.map(c => `
            <tr style="cursor: pointer;" data-id="${c.id}" class="company-row">
                <td style="padding-left: 1.5rem;" class="font-monospace fw-semibold">${c.company_code}</td>
                <td class="fw-semibold text-dark">${c.name}</td>
                <td>${formatTypeBadge(c.type)}</td>
                <td>${formatRatingBadge(c.rating)}</td>
                <td class="text-capitalize small">${c.industry.toLowerCase()}</td>
                <td>${c.phone || '-'}</td>
                <td>${c.email || '-'}</td>
                <td>${c.assigned_salesperson_name || 'Unassigned'}</td>
                <td style="padding-right: 1.5rem;" class="text-end action-cell">
                    <div class="d-inline-flex gap-2">
                        <button class="btn btn-sm btn-outline-primary py-0 px-2 view-details-btn" data-id="${c.id}">Profile</button>
                        <button class="btn btn-sm btn-outline-warning py-0 px-2 edit-btn" data-id="${c.id}">Edit</button>
                        <button class="btn btn-sm btn-outline-danger py-0 px-2 delete-btn" data-id="${c.id}">Delete</button>
                    </div>
                </td>
            </tr>
        `).join('');

        // Row Click opens Details (ignoring action button cells)
        companyTableBody.querySelectorAll('.company-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('.action-cell')) return;
                const companyId = row.getAttribute('data-id');
                loadCompanyDetails(companyId);
            });
        });

        // Bind action click listeners
        companyTableBody.querySelectorAll('.view-details-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                loadCompanyDetails(btn.getAttribute('data-id'));
            });
        });

        companyTableBody.querySelectorAll('.edit-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                loadCompanyForEdit(btn.getAttribute('data-id'));
            });
        });

        companyTableBody.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteCompany(btn.getAttribute('data-id'));
            });
        });
    }

    // --- Client Side Dashboard KPIs calculations ---
    function calculateClientStats(list) {
        document.getElementById('statTotal').textContent = list.length;
        document.getElementById('statProspects').textContent = list.filter(c => c.type === 'PROSPECT').length;
        document.getElementById('statCustomers').textContent = list.filter(c => c.type === 'CUSTOMER').length;
        document.getElementById('statPartners').textContent = list.filter(c => c.type === 'PARTNER').length;
    }

    // --- Pagination rendering ---
    function updatePaginationControls(pagination) {
        if (!pagination) {
            paginationDisplay.textContent = 'Showing 0 of 0 companies.';
            paginationNav.innerHTML = '';
            return;
        }

        currentPage = pagination.page;
        totalPages = pagination.total_pages;

        paginationDisplay.textContent = `Showing page ${pagination.page} of ${pagination.total_pages} (Total: ${pagination.total_items} companies).`;

        let navHtml = `
            <li class="page-item ${pagination.previous ? '' : 'disabled'}">
                <a class="page-link" href="#" data-page="${pagination.page - 1}">&laquo;</a>
            </li>
        `;

        for (let i = 1; i <= pagination.total_pages; i++) {
            navHtml += `
                <li class="page-item ${pagination.page === i ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `;
        }

        navHtml += `
            <li class="page-item ${pagination.next ? '' : 'disabled'}">
                <a class="page-link" href="#" data-page="${pagination.page + 1}">&raquo;</a>
            </li>
        `;

        paginationNav.innerHTML = navHtml;

        paginationNav.querySelectorAll('.page-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const targetPage = parseInt(link.getAttribute('data-page'));
                if (targetPage >= 1 && targetPage <= totalPages) {
                    currentPage = targetPage;
                    loadCompanies();
                }
            });
        });
    }

    // --- Load Profile / Details Drawer Card ---
    async function loadCompanyDetails(id) {
        try {
            const response = await RESTClient.request('GET', `/api/companies/${id}/`);
            if (response.success && response.data) {
                const c = response.data;
                
                // Show Card Display
                companyProfileCard.classList.remove('d-none');
                document.getElementById('profileCodeDisplay').textContent = `${c.company_code} - Company Profile`;
                document.getElementById('profileName').textContent = c.name;
                document.getElementById('profileTypeIndustry').textContent = `${c.type} | ${c.industry}`;
                document.getElementById('profileCode').textContent = c.company_code;
                document.getElementById('profileRating').outerHTML = formatRatingBadge(c.rating);
                document.getElementById('profileEmail').textContent = c.email || 'N/A';
                document.getElementById('profilePhone').textContent = c.phone || 'N/A';
                document.getElementById('profileEmployees').textContent = c.employee_count || '0';
                document.getElementById('profileRevenue').textContent = c.annual_revenue ? formatCurrency(c.annual_revenue) : 'N/A';
                document.getElementById('profileOwner').textContent = c.assigned_salesperson_name || 'Unassigned';
                document.getElementById('profileSource').textContent = c.lead_source || 'N/A';
                document.getElementById('profileDescription').textContent = c.description || 'No description provided.';
                
                if (c.website) {
                    const webLink = document.getElementById('profileWebsite');
                    webLink.textContent = c.website;
                    webLink.href = c.website.startsWith('http') ? c.website : 'http://' + c.website;
                } else {
                    document.getElementById('profileWebsite').textContent = 'N/A';
                }

                // Summary calculations
                document.getElementById('summaryContacts').textContent = c.summary.total_contacts;
                document.getElementById('summaryDeals').textContent = `${c.summary.won_opportunities} Won / ${c.summary.open_opportunities} Open`;
                document.getElementById('summaryRevenue').textContent = formatCurrency(c.summary.total_revenue);

                // Nested Contacts
                const cTableBody = document.getElementById('profileContactsTable').querySelector('tbody');
                if (c.contacts && c.contacts.length > 0) {
                    cTableBody.innerHTML = c.contacts.map(con => `
                        <tr>
                            <td><strong>${con.full_name}</strong></td>
                            <td class="text-muted small">${con.designation || '-'}</td>
                            <td>${con.email || '-'}</td>
                            <td>${con.phone_number || '-'}</td>
                        </tr>
                    `).join('');
                } else {
                    cTableBody.innerHTML = `<tr><td colspan="4" class="text-center py-2 text-muted">No contacts linked.</td></tr>`;
                }

                // Nested Opportunities
                const oTableBody = document.getElementById('profileOpportunitiesTable').querySelector('tbody');
                if (c.opportunities && c.opportunities.length > 0) {
                    oTableBody.innerHTML = c.opportunities.map(opp => `
                        <tr>
                            <td><strong>${opp.name}</strong></td>
                            <td><span class="badge bg-secondary text-uppercase" style="font-size: 0.65rem;">${opp.stage.replace('_', ' ')}</span></td>
                            <td class="fw-semibold">${formatCurrency(opp.value)}</td>
                            <td class="text-secondary small">${opp.expected_close_date || '-'}</td>
                        </tr>
                    `).join('');
                } else {
                    oTableBody.innerHTML = `<tr><td colspan="4" class="text-center py-2 text-muted">No opportunities linked.</td></tr>`;
                }

                // Scroll to profile view smoothly
                companyProfileCard.scrollIntoView({ behavior: 'smooth' });
            }
        } catch (error) {
            window.UIUtils.showAlert('mainAlertContainer', parseAPIError(error), 'danger');
        }
    }

    closeProfileBtn.addEventListener('click', () => {
        companyProfileCard.classList.add('d-none');
    });

    // --- Create / Edit submit ---
    companyForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const payload = {
            name: companyNameInput.value.trim(),
            email: companyEmailInput.value.trim() || null,
            phone: companyPhoneInput.value.trim() || '',
            website: companyWebsiteInput.value.trim() || '',
            type: companyTypeSelect.value,
            rating: companyRatingSelect.value,
            industry: companyIndustrySelect.value,
            annual_revenue: companyRevenueInput.value ? parseFloat(companyRevenueInput.value) : null,
            employee_count: companyEmployeesInput.value ? parseInt(companyEmployeesInput.value) : null,
            assigned_salesperson: companyOwnerInput.value ? parseInt(companyOwnerInput.value) : null,
            description: companyDescriptionInput.value.trim() || ''
        };

        const id = companyIdInput.value;
        try {
            let response;
            if (id) {
                response = await RESTClient.request('PATCH', `/api/companies/${id}/`, payload);
                window.UIUtils.showAlert('mainAlertContainer', 'Company updated successfully.');
            } else {
                response = await RESTClient.request('POST', '/api/companies/', payload);
                window.UIUtils.showAlert('mainAlertContainer', 'Company created successfully.');
            }

            if (response.success) {
                resetForm();
                loadCompanies();
            }
        } catch (error) {
            window.UIUtils.showAlert('mainAlertContainer', parseAPIError(error), 'danger');
        }
    });

    // --- Load for Edit ---
    async function loadCompanyForEdit(id) {
        try {
            const response = await RESTClient.request('GET', `/api/companies/${id}/`);
            if (response.success && response.data) {
                const c = response.data;
                
                companyIdInput.value = c.id;
                companyNameInput.value = c.name;
                companyEmailInput.value = c.email || '';
                companyPhoneInput.value = c.phone || '';
                companyWebsiteInput.value = c.website || '';
                companyTypeSelect.value = c.type;
                companyRatingSelect.value = c.rating;
                companyIndustrySelect.value = c.industry;
                companyRevenueInput.value = c.annual_revenue || '';
                companyEmployeesInput.value = c.employee_count || '';
                companyOwnerInput.value = c.assigned_salesperson || '';
                companyDescriptionInput.value = c.description || '';

                formTitle.textContent = 'Edit Company';
                saveBtn.textContent = 'Save Changes';
                cancelBtn.style.display = 'block';

                companyForm.scrollIntoView({ behavior: 'smooth' });
            }
        } catch (error) {
            window.UIUtils.showAlert('mainAlertContainer', parseAPIError(error), 'danger');
        }
    }

    // --- Delete handler ---
    async function deleteCompany(id) {
        if (!confirm('Are you sure you want to delete this company record?')) return;
        try {
            const response = await RESTClient.request('DELETE', `/api/companies/${id}/`);
            if (response.success) {
                window.UIUtils.showAlert('mainAlertContainer', 'Company record deleted successfully.');
                loadCompanies();
                companyProfileCard.classList.add('d-none');
            }
        } catch (error) {
            window.UIUtils.showAlert('mainAlertContainer', parseAPIError(error), 'danger');
        }
    }

    function resetForm() {
        companyForm.reset();
        companyIdInput.value = '';
        formTitle.textContent = 'Create New Company';
        saveBtn.textContent = 'Create Company';
        cancelBtn.style.display = 'none';
    }

    cancelBtn.addEventListener('click', resetForm);

    // --- Filter Handlers ---
    function applyFilters() {
        currentPage = 1;
        loadCompanies();
    }

    searchBox.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 500);
    });

    filterType.addEventListener('change', applyFilters);
    filterRating.addEventListener('change', applyFilters);
    filterIndustry.addEventListener('change', applyFilters);
    filterOwner.addEventListener('change', applyFilters);

    // --- Table Sorting Ordering Click Handlers ---
    document.querySelectorAll('th[data-ordering]').forEach(th => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
            const field = th.getAttribute('data-ordering');
            if (currentOrdering === field) {
                currentOrdering = `-${field}`;
            } else {
                currentOrdering = field;
            }
            loadCompanies();
        });
    });

    // --- Initial Execution ---
    loadCompanies();
});
