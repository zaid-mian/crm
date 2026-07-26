document.addEventListener('DOMContentLoaded', () => {
    const canModify = window.CRM_CAN_MODIFY === true;
    let currentPage = 1;
    let totalPages = 1;
    let selectedPaymentId = null;
    let opportunities = [];

    const drawer = document.getElementById('paymentDrawer');
    const backdrop = document.getElementById('drawerBackdrop');
    const tbody = document.querySelector('#paymentsTable tbody');
    const loadingState = document.getElementById('loadingState');
    const emptyState = document.getElementById('emptyState');

    const formatMoney = (val) =>
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0);

    function statusBadge(status, label) {
        const map = {
            UNPAID: 'crm-badge-unpaid',
            PARTIALLY_PAID: 'crm-badge-partial',
            PAID: 'crm-badge-paid',
        };
        const text = label || status;
        return `<span class="crm-badge ${map[status] || ''}">${text}</span>`;
    }

    function showAlert(message, type = 'success') {
        const container = document.getElementById('mainAlertContainer');
        const cls = type === 'success' ? 'crm-alert-success' : 'crm-alert-error';
        const icon = type === 'success' ? '✓' : '❌';
        container.innerHTML = `<div class="crm-alert ${cls}">${icon} ${message}</div>`;
        setTimeout(() => {
            container.innerHTML = '';
        }, 4000);
    }

    function openDrawer() {
        drawer.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');
        backdrop.hidden = false;
    }

    function closeDrawer() {
        drawer.classList.remove('open');
        drawer.setAttribute('aria-hidden', 'true');
        backdrop.hidden = true;
    }

    document.getElementById('closeDrawerBtn')?.addEventListener('click', closeDrawer);
    document.getElementById('cancelDrawerBtn')?.addEventListener('click', closeDrawer);
    backdrop?.addEventListener('click', closeDrawer);

    async function loadReferenceData() {
        const companyRes = await window.APIClient.get('/api/companies/?page_size=100');
        const companies = companyRes.data?.results || [];
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
            const sp = document.getElementById('filterSalesperson').value;
            if (sp) params.append('assigned_salesperson', sp);
            const from = document.getElementById('filterDateFrom').value;
            const to = document.getElementById('filterDateTo').value;
            if (from) params.append('date_after', from);
            if (to) params.append('date_before', to);

            const res = await window.APIClient.get(`/api/payments/?${params.toString()}`);
            const payments = res.data?.results || [];
            const pagination = res.data?.pagination;
            totalPages = pagination?.total_pages || 1;
            currentPage = pagination?.page || 1;

            loadingState.classList.add('d-none');
            if (!payments.length) {
                emptyState.classList.remove('d-none');
            } else {
                payments.forEach((p, idx) => {
                    const tr = document.createElement('tr');
                    const editBtn = canModify
                        ? `<button class="crm-btn-icon" data-action="edit" data-id="${p.id}" title="Edit">✏</button>`
                        : '';
                    const payBtn = canModify
                        ? `<button class="crm-btn-icon" data-action="pay" data-id="${p.id}" title="Record">💰</button>`
                        : '';
                    tr.innerHTML = `
                        <td>${(currentPage - 1) * 20 + idx + 1}</td>
                        <td><strong>${p.invoice_number}</strong></td>
                        <td>${p.company_name}</td>
                        <td>${p.opportunity_name}</td>
                        <td>${formatMoney(p.total_amount)}</td>
                        <td>${formatMoney(p.paid_amount)}</td>
                        <td>${formatMoney(p.balance)}</td>
                        <td>${statusBadge(p.status, p.status_display)}</td>
                        <td>${p.payment_date || '—'}</td>
                        <td class="text-nowrap">
                            <button class="crm-btn-icon" data-action="view" data-id="${p.id}" title="View">👁</button>
                            ${editBtn}
                            <button class="crm-btn-icon" data-action="invoice" data-id="${p.id}" title="Invoice">🧾</button>
                            ${payBtn}
                        </td>`;
                    tbody.appendChild(tr);
                });
            }
            document.getElementById('paginationDisplay').textContent =
                `Page ${currentPage} of ${totalPages || 1}`;
            renderPagination();
        } catch (err) {
            loadingState.classList.add('d-none');
            showAlert(err.message || 'Payment processing failed.', 'error');
        }
    }

    function renderPagination() {
        const nav = document.getElementById('paginationNav');
        nav.innerHTML = '';
        const prev = document.createElement('button');
        prev.textContent = 'Prev';
        prev.disabled = currentPage <= 1;
        prev.onclick = () => {
            currentPage -= 1;
            loadPayments();
        };
        const next = document.createElement('button');
        next.textContent = 'Next';
        next.disabled = currentPage >= totalPages;
        next.onclick = () => {
            currentPage += 1;
            loadPayments();
        };
        nav.append(prev, next);
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
        document.getElementById('recordAnotherBtn').classList.toggle('d-none', !canModify);
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
        openDrawer();
    }

    async function openViewDrawer(id) {
        selectedPaymentId = id;
        const res = await window.APIClient.get(`/api/payments/${id}/`);
        const p = res.data;
        const latestTxn = (p.transactions && p.transactions[0]) || null;
        document.getElementById('drawerTitle').textContent = 'Payment Details';
        setFormMode('view');
        document.getElementById('viewDetails').innerHTML = `
            <dt>Invoice Number</dt><dd>${p.invoice_number}</dd>
            <dt>Company</dt><dd>${p.company_name}</dd>
            <dt>Opportunity</dt><dd>${p.opportunity_name}</dd>
            <dt>Customer</dt><dd>${p.customer_name || '—'}</dd>
            <dt>Salesperson</dt><dd>${p.assigned_salesperson_name || '—'}</dd>
            <dt>Total Amount</dt><dd>${formatMoney(p.total_amount)}</dd>
            <dt>Paid Amount</dt><dd>${formatMoney(p.paid_amount)}</dd>
            <dt>Remaining Balance</dt><dd>${formatMoney(p.balance)}</dd>
            <dt>Payment Method</dt><dd>${latestTxn ? latestTxn.payment_method_display : '—'}</dd>
            <dt>Transaction Reference</dt><dd>${latestTxn ? latestTxn.transaction_reference || '—' : '—'}</dd>
            <dt>Payment Date</dt><dd>${p.payment_date || '—'}</dd>
            <dt>Status</dt><dd>${statusBadge(p.status, p.status_display)}</dd>`;
        document.getElementById('viewHistory').innerHTML = (p.payment_history || [])
            .map((h) => `<li>✓ ${h.description}</li>`)
            .join('') || '<li>No history yet.</li>';
        openDrawer();
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
        openDrawer();
    }

    function openAddPaymentDrawer(id) {
        document.getElementById('drawerTitle').textContent = 'Record Payment';
        document.getElementById('paymentId').value = id;
        document.getElementById('formAmountReceived').value = '';
        document.getElementById('formReference').value = '';
        document.getElementById('formDate').value = new Date().toISOString().slice(0, 10);
        setFormMode('add_payment');
        openDrawer();
    }

    document.getElementById('paymentsTable').addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const id = btn.dataset.id;
        const action = btn.dataset.action;
        try {
            if (action === 'view') await openViewDrawer(id);
            if (action === 'edit' && canModify) await openEditDrawer(id);
            if (action === 'pay' && canModify) openAddPaymentDrawer(id);
            if (action === 'invoice') {
                await window.APIClient.download(`/api/payments/${id}/invoice/`, `invoice-${id}.pdf`);
            }
        } catch (err) {
            showAlert(err.message, 'error');
        }
    });

    if (canModify) {
        document.getElementById('openRecordBtn')?.addEventListener('click', openCreateDrawer);
    }

    document.getElementById('recordAnotherBtn')?.addEventListener('click', () => {
        if (selectedPaymentId && canModify) openAddPaymentDrawer(selectedPaymentId);
    });
    document.getElementById('viewDownloadInvoice')?.addEventListener('click', () => {
        if (selectedPaymentId) {
            window.APIClient.download(`/api/payments/${selectedPaymentId}/invoice/`, 'invoice.pdf');
        }
    });
    document.getElementById('viewPrintReceipt')?.addEventListener('click', () => {
        if (selectedPaymentId) {
            window.APIClient.download(`/api/payments/${selectedPaymentId}/receipt/`, 'receipt.pdf');
        }
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
                showAlert('Payment updated successfully.');
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
                showAlert('Payment recorded successfully.');
            }
            closeDrawer();
            loadPayments();
        } catch (err) {
            showAlert(err.message || 'Payment processing failed.', 'error');
        }
    });

    ['searchBox', 'filterStatus', 'filterMethod', 'filterCompany', 'filterDateFrom', 'filterDateTo', 'filterSalesperson'].forEach((id) => {
        const el = document.getElementById(id);
        el?.addEventListener('change', () => {
            currentPage = 1;
            loadPayments();
        });
        if (id === 'searchBox') {
            el?.addEventListener('keydown', (ev) => {
                if (ev.key === 'Enter') {
                    currentPage = 1;
                    loadPayments();
                }
            });
        }
    });

    loadReferenceData()
        .then(loadPayments)
        .catch((err) => showAlert(err.message, 'error'));
});
