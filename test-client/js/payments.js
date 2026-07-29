document.addEventListener('DOMContentLoaded', () => {
    let payments = [];
    let companies = [];
    let opportunities = [];
    let currentPage = 1;
    let totalPages = 1;
    let selectedPaymentId = null;

    const drawer = new bootstrap.Offcanvas(document.getElementById('paymentDrawer'));
    const connectedBaseDisplay = document.getElementById('connectedBaseDisplay');
    if (connectedBaseDisplay) {
        connectedBaseDisplay.textContent = window.APIClient.getBaseUrl();
    }

    const tbody = document.querySelector('#paymentsTable tbody');
    const loadingState = document.getElementById('loadingState');
    const emptyState = document.getElementById('emptyState');
    const paginationDisplay = document.getElementById('paginationDisplay');
    const paginationNav = document.getElementById('paginationNav');
    const consoleOutput = document.getElementById('consoleOutput');

    const formatMoney = (val) =>
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0);

    const statusBadge = (status, label) => {
        const map = {
            UNPAID: 'bg-danger',
            PARTIALLY_PAID: 'bg-warning text-dark',
            PAID: 'bg-success',
        };
        return `<span class="badge ${map[status] || 'bg-secondary'}">${label || status}</span>`;
    };

    function showAlert(message, type = 'success') {
        const container = document.getElementById('mainAlertContainer');
        container.innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>`;
    }

    window.addEventListener('crm-api-log', (event) => {
        const { method, url, requestBody, status, responseBody } = event.detail;
        let path = url.replace(window.APIClient.getBaseUrl(), '');
        logToConsole(method, path, requestBody, status, responseBody);
    });

    function logToConsole(method, url, reqBody, status, resBody) {
        if (!consoleOutput) return;
        const placeholder = consoleOutput.querySelector('.text-secondary');
        if (placeholder) placeholder.remove();
        const badgeClass = status >= 200 && status < 300 ? 'bg-success' : 'bg-danger';
        const entry = document.createElement('div');
        entry.className = 'border-bottom border-secondary border-opacity-25 pb-2 mb-2';
        entry.innerHTML = `
            <div><span class="badge ${badgeClass}">${method}</span> <code>${url}</code> (${status})</div>
            ${reqBody ? `<div class="text-warning">Req: ${JSON.stringify(reqBody)}</div>` : ''}
            <pre class="mb-0 mt-1 text-light">${window.UIUtils ? window.UIUtils.syntaxHighlightJson(resBody) : JSON.stringify(resBody, null, 2)}</pre>`;
        consoleOutput.appendChild(entry);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    }

    document.getElementById('clearConsoleBtn')?.addEventListener('click', () => {
        consoleOutput.innerHTML = '<div class="text-secondary">Console cleared.</div>';
    });

    async function loadReferenceData() {
        const companyRes = await window.APIClient.get('/api/companies/?page_size=100');
        companies = companyRes.data?.results || companyRes.data || [];
        const companySelect = document.getElementById('filterCompany');
        const formCompany = document.getElementById('formCompany');
        companySelect.innerHTML = '<option value="">Company</option>';
        formCompany.innerHTML = '<option value="">Select Company</option>';
        companies.forEach((c) => {
            companySelect.innerHTML += `<option value="${c.id}">${c.name}</option>`;
            formCompany.innerHTML += `<option value="${c.id}">${c.name}</option>`;
        });

        const oppRes = await window.APIClient.get('/api/opportunities/?page_size=100&stage=CLOSED_WON');
        opportunities = oppRes.data?.results || [];
        refreshOpportunityOptions();
    }

    function refreshOpportunityOptions(companyId = '') {
        const formOpportunity = document.getElementById('formOpportunity');
        formOpportunity.innerHTML = '<option value="">Select Opportunity</option>';
        opportunities
            .filter((o) => !companyId || String(o.company) === String(companyId))
            .forEach((o) => {
                formOpportunity.innerHTML += `<option value="${o.id}" data-amount="${o.amount}">${o.name}</option>`;
            });
    }

    document.getElementById('formCompany')?.addEventListener('change', (e) => {
        refreshOpportunityOptions(e.target.value);
    });

    document.getElementById('formOpportunity')?.addEventListener('change', (e) => {
        const opt = e.target.selectedOptions[0];
        if (opt && opt.dataset.amount) {
            document.getElementById('formTotalAmount').value = opt.dataset.amount;
        }
    });

    async function loadPayments() {
        loadingState.classList.remove('d-none');
        emptyState.classList.add('d-none');
        tbody.innerHTML = '';
        try {
            const params = new URLSearchParams({ page: currentPage });
            const search = document.getElementById('searchBox').value.trim();
            if (search) params.append('search', search);
            const status = document.getElementById('filterStatus').value;
            if (status) params.append('status', status);
            const method = document.getElementById('filterMethod').value;
            if (method) params.append('payment_method', method);
            const company = document.getElementById('filterCompany').value;
            if (company) params.append('company', company);
            const from = document.getElementById('filterDateFrom').value;
            const to = document.getElementById('filterDateTo').value;
            if (from) params.append('date_after', from);
            if (to) params.append('date_before', to);

            const res = await window.APIClient.get(`/api/payments/?${params.toString()}`);
            payments = res.data?.results || [];
            const pagination = res.data?.pagination;
            totalPages = pagination?.total_pages || 1;
            currentPage = pagination?.page || 1;

            loadingState.classList.add('d-none');
            if (!payments.length) {
                emptyState.classList.remove('d-none');
            } else {
                payments.forEach((p, idx) => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${(currentPage - 1) * 20 + idx + 1}</td>
                        <td>${p.invoice_number}</td>
                        <td>${p.company_name}</td>
                        <td>${p.opportunity_name}</td>
                        <td>${formatMoney(p.total_amount)}</td>
                        <td>${formatMoney(p.paid_amount)}</td>
                        <td>${formatMoney(p.balance)}</td>
                        <td>${statusBadge(p.status, p.status_display)}</td>
                        <td>${p.payment_date || '-'}</td>
                        <td class="text-nowrap">
                            <button class="btn btn-sm btn-light" data-action="view" data-id="${p.id}" title="View">👁</button>
                            <button class="btn btn-sm btn-light" data-action="edit" data-id="${p.id}" title="Edit">✏</button>
                            <button class="btn btn-sm btn-light" data-action="invoice" data-id="${p.id}" title="Invoice">🧾</button>
                            <button class="btn btn-sm btn-light" data-action="pay" data-id="${p.id}" title="Record">💰</button>
                        </td>`;
                    tbody.appendChild(tr);
                });
            }
            paginationDisplay.textContent = `Page ${currentPage} of ${totalPages || 1}`;
            renderPagination();
        } catch (err) {
            loadingState.classList.add('d-none');
            showAlert(err.message || 'Payment processing failed.', 'danger');
        }
    }

    function renderPagination() {
        paginationNav.innerHTML = '';
        const add = (label, page, disabled = false) => {
            const li = document.createElement('li');
            li.className = `page-item ${disabled ? 'disabled' : ''}`;
            li.innerHTML = `<a class="page-link" href="#">${label}</a>`;
            if (!disabled) {
                li.addEventListener('click', (e) => {
                    e.preventDefault();
                    currentPage = page;
                    loadPayments();
                });
            }
            paginationNav.appendChild(li);
        };
        add('Prev', currentPage - 1, currentPage <= 1);
        add('Next', currentPage + 1, currentPage >= totalPages);
    }

    function setFormMode(mode) {
        document.getElementById('formMode').value = mode;
        document.getElementById('paymentForm').classList.toggle('d-none', mode === 'view');
        document.getElementById('viewPanel').classList.toggle('d-none', mode !== 'view');
        document.getElementById('amountReceivedGroup').classList.toggle('d-none', mode === 'edit');
        document.getElementById('methodGroup').classList.toggle('d-none', mode === 'edit');
        document.getElementById('referenceGroup').classList.toggle('d-none', mode === 'edit');
        document.getElementById('dateGroup').classList.toggle('d-none', mode === 'edit');
        document.getElementById('companyFieldGroup').classList.toggle('d-none', mode === 'edit' || mode === 'add_payment');
        document.getElementById('opportunityFieldGroup').classList.toggle('d-none', mode === 'edit' || mode === 'add_payment');
        document.getElementById('totalAmountGroup').classList.toggle('d-none', mode === 'add_payment');
    }

    function openCreateDrawer() {
        document.getElementById('drawerTitle').textContent = 'Record Payment';
        document.getElementById('paymentId').value = '';
        document.getElementById('formInvoice').value = '';
        document.getElementById('formTotalAmount').value = '';
        document.getElementById('formAmountReceived').value = '';
        document.getElementById('formReference').value = '';
        document.getElementById('formNotes').value = '';
        document.getElementById('formDate').value = new Date().toISOString().slice(0, 10);
        setFormMode('create');
        drawer.show();
    }

    async function openViewDrawer(id) {
        selectedPaymentId = id;
        const res = await window.APIClient.get(`/api/payments/${id}/`);
        const p = res.data;
        document.getElementById('drawerTitle').textContent = 'Payment Details';
        setFormMode('view');
        document.getElementById('viewDetails').innerHTML = `
            <dt class="col-5">Invoice</dt><dd class="col-7">${p.invoice_number}</dd>
            <dt class="col-5">Company</dt><dd class="col-7">${p.company_name}</dd>
            <dt class="col-5">Opportunity</dt><dd class="col-7">${p.opportunity_name}</dd>
            <dt class="col-5">Customer</dt><dd class="col-7">${p.customer_name || '-'}</dd>
            <dt class="col-5">Salesperson</dt><dd class="col-7">${p.assigned_salesperson_name || '-'}</dd>
            <dt class="col-5">Total</dt><dd class="col-7">${formatMoney(p.total_amount)}</dd>
            <dt class="col-5">Paid</dt><dd class="col-7">${formatMoney(p.paid_amount)}</dd>
            <dt class="col-5">Balance</dt><dd class="col-7">${formatMoney(p.balance)}</dd>
            <dt class="col-5">Status</dt><dd class="col-7">${statusBadge(p.status, p.status_display)}</dd>`;
        document.getElementById('viewHistory').innerHTML = (p.payment_history || [])
            .map((h) => `<li class="mb-2">✓ ${h.description}</li>`)
            .join('') || '<li class="text-muted">No history yet.</li>';
        drawer.show();
    }

    async function openEditDrawer(id) {
        const res = await window.APIClient.get(`/api/payments/${id}/`);
        const p = res.data;
        document.getElementById('drawerTitle').textContent = 'Edit Payment';
        document.getElementById('paymentId').value = p.id;
        document.getElementById('formInvoice').value = p.invoice_number;
        document.getElementById('formTotalAmount').value = p.total_amount;
        document.getElementById('formNotes').value = p.notes || '';
        setFormMode('edit');
        drawer.show();
    }

    function openAddPaymentDrawer(id) {
        document.getElementById('drawerTitle').textContent = 'Record Payment';
        document.getElementById('paymentId').value = id;
        document.getElementById('formAmountReceived').value = '';
        document.getElementById('formReference').value = '';
        document.getElementById('formDate').value = new Date().toISOString().slice(0, 10);
        setFormMode('add_payment');
        drawer.show();
    }

    async function downloadFile(path, filename) {
        const baseUrl = window.APIClient.getBaseUrl();
        const headers = window.APIClient.getHeaders();
        delete headers['Content-Type'];
        const config = { method: 'GET', headers };
        const response = await fetch(`${baseUrl}${path}`, config);
        if (!response.ok) throw new Error('Download failed');
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    document.getElementById('paymentsTable').addEventListener('click', async (e) => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const id = btn.dataset.id;
        const action = btn.dataset.action;
        try {
            if (action === 'view') await openViewDrawer(id);
            if (action === 'edit') await openEditDrawer(id);
            if (action === 'pay') openAddPaymentDrawer(id);
            if (action === 'invoice') {
                await downloadFile(`/api/payments/${id}/invoice/`, `invoice-${id}.pdf`);
            }
        } catch (err) {
            showAlert(err.message, 'danger');
        }
    });

    document.getElementById('openRecordBtn').addEventListener('click', openCreateDrawer);
    document.getElementById('recordAnotherBtn').addEventListener('click', () => {
        if (selectedPaymentId) openAddPaymentDrawer(selectedPaymentId);
    });
    document.getElementById('viewDownloadInvoice').addEventListener('click', () => {
        if (selectedPaymentId) downloadFile(`/api/payments/${selectedPaymentId}/invoice/`, 'invoice.pdf');
    });
    document.getElementById('viewPrintReceipt').addEventListener('click', () => {
        if (selectedPaymentId) downloadFile(`/api/payments/${selectedPaymentId}/receipt/`, 'receipt.pdf');
    });

    document.getElementById('paymentForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const mode = document.getElementById('formMode').value;
        const id = document.getElementById('paymentId').value;
        try {
            if (mode === 'edit') {
                await window.APIClient.put(`/api/payments/${id}/`, {
                    total_amount: document.getElementById('formTotalAmount').value,
                    notes: document.getElementById('formNotes').value,
                });
                showAlert('✓ Payment updated successfully.');
            } else {
                const payload = {
                    payment_method: document.getElementById('formMethod').value,
                    transaction_reference: document.getElementById('formReference').value,
                    payment_date: document.getElementById('formDate').value,
                    notes: document.getElementById('formNotes').value,
                    amount_received: document.getElementById('formAmountReceived').value,
                };
                if (mode === 'add_payment' || id) {
                    payload.payment_id = parseInt(id, 10);
                } else {
                    payload.company = parseInt(document.getElementById('formCompany').value, 10);
                    payload.opportunity = parseInt(document.getElementById('formOpportunity').value, 10);
                    payload.total_amount = document.getElementById('formTotalAmount').value;
                }
                await window.APIClient.post('/api/payments/', payload);
                showAlert('✓ Payment recorded successfully.');
            }
            drawer.hide();
            loadPayments();
        } catch (err) {
            showAlert(err.message || 'Payment processing failed.', 'danger');
        }
    });

    ['searchBox', 'filterStatus', 'filterMethod', 'filterCompany', 'filterDateFrom', 'filterDateTo'].forEach((id) => {
        document.getElementById(id)?.addEventListener('change', () => {
            currentPage = 1;
            loadPayments();
        });
        document.getElementById(id)?.addEventListener('keyup', (ev) => {
            if (id === 'searchBox' && ev.key === 'Enter') {
                currentPage = 1;
                loadPayments();
            }
        });
    });

    loadReferenceData()
        .then(loadPayments)
        .catch((err) => showAlert(err.message, 'danger'));
});
