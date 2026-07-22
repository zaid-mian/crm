document.addEventListener('DOMContentLoaded', () => {
    const apiBaseUrl = localStorage.getItem('api_base_url') || 'http://localhost:8000';
    document.getElementById('connectedBaseDisplay').textContent = apiBaseUrl;

    const contactsTableBody = document.querySelector('#contactsTable tbody');
    const recordCounter = document.getElementById('recordCounter');
    
    // Filters & Search
    const searchBox = document.getElementById('searchBox');
    const filterCompany = document.getElementById('filterCompany');
    const filterStatus = document.getElementById('filterStatus');
    const filterSalesperson = document.getElementById('filterSalesperson');
    const filterDesignation = document.getElementById('filterDesignation');

    // Drawers & Modals
    const addContactDrawer = new bootstrap.Offcanvas(document.getElementById('addContactDrawer'));
    const editContactDrawer = new bootstrap.Offcanvas(document.getElementById('editContactDrawer'));
    const viewContactDrawer = new bootstrap.Offcanvas(document.getElementById('viewContactDrawer'));
    const deleteContactModal = new bootstrap.Modal(document.getElementById('deleteContactModal'));

    let currentContactIdToDelete = null;
    let currentViewingContact = null;

    function getAuthHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const authMethod = localStorage.getItem('auth_method') || 'basic';
        if (authMethod === 'basic') {
            const user = localStorage.getItem('auth_username') || 'admin';
            const pass = localStorage.getItem('auth_password') || 'admin123';
            headers['Authorization'] = 'Basic ' + btoa(user + ':' + pass);
        } else if (authMethod === 'token') {
            const token = localStorage.getItem('auth_token');
            if (token) headers['Authorization'] = token;
        }
        return headers;
    }

    async function loadUsers() {
        try {
            // NOTE: Temporary hardcoded list for the development test client.
            // This will be replaced with a backend API request once the User module is implemented.
            const users = [
                { id: 1, name: "Admin" },
                { id: 2, name: "Manager" },
                { id: 3, name: "Salesperson 1" },
                { id: 4, name: "Salesperson 2" }
            ];

            const addSelect = document.getElementById('addSalespersonSelect');
            const editSelect = document.getElementById('editSalespersonSelect');
            const filterSelect = document.getElementById('filterSalesperson');

            const options = users.map(u => `<option value="${u.id}">${u.name}</option>`).join('');
            addSelect.innerHTML = '<option value="">Select User</option>' + options;
            editSelect.innerHTML = '<option value="">Select User</option>' + options;
            filterSelect.innerHTML = '<option value="">All Salespersons</option>' + options;
        } catch (err) {
            console.error(err);
        }
    }

    async function loadContacts() {
        contactsTableBody.innerHTML = `
            <tr>
                <td colspan="9" class="text-center py-5 text-muted">
                    <div class="spinner-border spinner-border-sm text-primary me-2" role="status"></div>
                    Loading contacts...
                </td>
            </tr>
        `;

        try {
            const params = new URLSearchParams();
            if (searchBox.value.trim()) params.append('search', searchBox.value.trim());
            if (filterCompany.value.trim()) params.append('company_name', filterCompany.value.trim());
            if (filterStatus.value) params.append('status', filterStatus.value);
            if (filterSalesperson.value) params.append('assigned_salesperson', filterSalesperson.value);
            if (filterDesignation.value.trim()) params.append('designation', filterDesignation.value.trim());

            const response = await fetch(`${apiBaseUrl}/api/contacts/?${params.toString()}`, {
                headers: getAuthHeaders()
            });

            const data = await response.json();

            if (response.ok && data.data) {
                const results = data.data.results || data.data;
                recordCounter.textContent = `${results.length} record(s)`;
                renderContacts(results);
            } else {
                recordCounter.textContent = '0 records';
                contactsTableBody.innerHTML = `
                    <tr>
                        <td colspan="9" class="text-center py-4 text-danger">
                            Failed to load contacts: ${data.message || 'Error'}
                        </td>
                    </tr>
                `;
            }
        } catch (error) {
            contactsTableBody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center py-4 text-danger">
                        Network Error connecting to ${apiBaseUrl}
                    </td>
                </tr>
            `;
        }
    }

    function renderContacts(contacts) {
        if (!contacts || contacts.length === 0) {
            contactsTableBody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center py-4 text-muted">
                        No contact records found matching filters.
                    </td>
                </tr>
            `;
            return;
        }

        contactsTableBody.innerHTML = contacts.map((c, index) => `
            <tr>
                <td class="ps-4 text-secondary font-monospace">${index + 1}</td>
                <td class="fw-semibold text-dark">${c.full_name}</td>
                <td>${c.company_name || '-'}</td>
                <td>${c.designation || '-'}</td>
                <td>${c.phone || c.phone_number || '-'}</td>
                <td class="text-secondary">${c.email || '-'}</td>
                <td>${c.assigned_salesperson_name || 'Unassigned'}</td>
                <td>
                    <span class="badge ${c.status === 'Active' ? 'bg-success' : 'bg-secondary'}">
                        ${c.status}
                    </span>
                </td>
                <td class="text-end pe-4">
                    <span class="action-icon text-primary view-icon" data-id="${c.id}" title="View Contact">👁</span>
                    <span class="action-icon text-secondary edit-icon" data-id="${c.id}" title="Edit Contact">✏️</span>
                    <span class="action-icon text-success call-icon" data-phone="${c.phone || c.phone_number}" title="Call Contact">📞</span>
                    <span class="action-icon text-info email-icon" data-email="${c.email}" title="Send Email">✉️</span>
                    <span class="action-icon text-danger delete-icon" data-id="${c.id}" title="Delete Contact">🗑</span>
                </td>
            </tr>
        `).join('');

        // Action Handlers
        document.querySelectorAll('.view-icon').forEach(el => {
            el.addEventListener('click', (e) => openViewDrawer(e.target.getAttribute('data-id')));
        });
        document.querySelectorAll('.edit-icon').forEach(el => {
            el.addEventListener('click', (e) => openEditDrawer(e.target.getAttribute('data-id')));
        });
        document.querySelectorAll('.call-icon').forEach(el => {
            el.addEventListener('click', (e) => {
                const phone = e.target.getAttribute('data-phone');
                alert(`Calling ${phone || 'contact'}...`);
            });
        });
        document.querySelectorAll('.email-icon').forEach(el => {
            el.addEventListener('click', (e) => {
                const email = e.target.getAttribute('data-email');
                if (email && email !== 'null') {
                    window.location.href = `mailto:${email}`;
                } else {
                    alert('No email address provided for this contact.');
                }
            });
        });
        document.querySelectorAll('.delete-icon').forEach(el => {
            el.addEventListener('click', (e) => {
                currentContactIdToDelete = e.target.getAttribute('data-id');
                deleteContactModal.show();
            });
        });
    }

    // Open View Contact Drawer
    async function openViewDrawer(id) {
        try {
            const response = await fetch(`${apiBaseUrl}/api/contacts/${id}/`, { headers: getAuthHeaders() });
            const data = await response.json();
            if (response.ok && data.data) {
                const c = data.data;
                currentViewingContact = c;

                document.getElementById('viewCode').textContent = c.contact_code || `CT${c.id}`;
                document.getElementById('viewFullName').textContent = c.full_name;
                document.getElementById('viewCompany').textContent = c.company_name || '-';
                document.getElementById('viewDesignation').textContent = c.designation || '-';
                document.getElementById('viewPhone').textContent = c.phone || c.phone_number || '-';
                document.getElementById('viewEmail').textContent = c.email || '-';
                document.getElementById('viewWhatsapp').textContent = c.whatsapp || '-';
                document.getElementById('viewAddress').textContent = [c.address, c.city, c.country].filter(Boolean).join(', ') || '-';
                document.getElementById('viewOwner').textContent = c.assigned_salesperson_name || 'Unassigned';
                document.getElementById('viewStatus').innerHTML = `<span class="badge ${c.status === 'Active' ? 'bg-success' : 'bg-secondary'}">${c.status}</span>`;
                document.getElementById('viewCreatedDate').textContent = new Date(c.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });

                // Render Opportunities
                const oppsBody = document.getElementById('viewOpportunitiesBody');
                const opps = c.related_opportunities || [];
                if (opps.length > 0) {
                    oppsBody.innerHTML = opps.map(o => `
                        <tr>
                            <td class="fw-medium">${o.name}</td>
                            <td><span class="badge bg-info text-dark">${o.stage}</span></td>
                            <td class="fw-bold">${o.value}</td>
                        </tr>
                    `).join('');
                } else {
                    oppsBody.innerHTML = `<tr><td colspan="3" class="text-muted">No opportunities linked.</td></tr>`;
                }

                // Render Timeline
                const timelineBody = document.getElementById('viewTimelineBody');
                const activities = c.activities || [];
                if (activities.length > 0) {
                    timelineBody.innerHTML = activities.map(a => `<div class="timeline-item small text-dark">${a.title || a.action}</div>`).join('');
                } else {
                    timelineBody.innerHTML = `<div class="timeline-item small text-muted">Contact Created</div>`;
                }

                // Render Tasks
                const tasksBody = document.getElementById('viewTasksBody');
                const tasks = c.related_tasks || [];
                if (tasks.length > 0) {
                    tasksBody.innerHTML = tasks.map(t => `<li class="list-group-item px-0 d-flex justify-content-between"><span>• ${t.name}</span><span class="badge bg-light text-secondary border">${t.status}</span></li>`).join('');
                } else {
                    tasksBody.innerHTML = `<li class="list-group-item px-0 text-muted">No tasks assigned.</li>`;
                }

                viewContactDrawer.show();
            }
        } catch (err) {
            console.error(err);
        }
    }

    // Open Edit Contact Drawer
    async function openEditDrawer(id) {
        try {
            const response = await fetch(`${apiBaseUrl}/api/contacts/${id}/`, { headers: getAuthHeaders() });
            const data = await response.json();
            if (response.ok && data.data) {
                const c = data.data;
                document.getElementById('editContactId').value = c.id;
                document.getElementById('editFullName').value = c.full_name || '';
                document.getElementById('editCompanyName').value = c.company_name || '';
                document.getElementById('editDesignation').value = c.designation || '';
                document.getElementById('editPhoneNumber').value = c.phone_number || c.phone || '';
                document.getElementById('editEmail').value = c.email || '';
                document.getElementById('editWhatsapp').value = c.whatsapp || '';
                document.getElementById('editAddress').value = c.address || '';
                document.getElementById('editCity').value = c.city || '';
                document.getElementById('editCountry').value = c.country || '';
                document.getElementById('editSalespersonSelect').value = c.assigned_salesperson || '1';
                document.getElementById('editStatus').value = c.status || 'Active';
                document.getElementById('editNotes').value = c.notes || '';

                editContactDrawer.show();
            }
        } catch (err) {
            console.error(err);
        }
    }

    // Drawer triggers
    document.getElementById('openAddDrawerBtn').addEventListener('click', () => {
        document.getElementById('addContactForm').reset();
        addContactDrawer.show();
    });

    document.getElementById('viewDrawerEditBtn').addEventListener('click', () => {
        if (currentViewingContact) {
            viewContactDrawer.hide();
            openEditDrawer(currentViewingContact.id);
        }
    });

    // Save New Contact
    document.getElementById('saveAddContactBtn').addEventListener('click', async () => {
        const form = document.getElementById('addContactForm');
        const formData = new FormData(form);
        const payload = Object.fromEntries(formData.entries());

        try {
            const response = await fetch(`${apiBaseUrl}/api/contacts/`, {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (response.ok) {
                addContactDrawer.hide();
                loadContacts();
            } else {
                alert('Validation Error: ' + JSON.stringify(data.errors || data.message));
            }
        } catch (err) {
            console.error(err);
        }
    });

    // Save Edit Contact
    document.getElementById('saveEditContactBtn').addEventListener('click', async () => {
        const id = document.getElementById('editContactId').value;
        const form = document.getElementById('editContactForm');
        const formData = new FormData(form);
        const payload = Object.fromEntries(formData.entries());

        try {
            const response = await fetch(`${apiBaseUrl}/api/contacts/${id}/`, {
                method: 'PUT',
                headers: getAuthHeaders(),
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (response.ok) {
                editContactDrawer.hide();
                loadContacts();
            } else {
                alert('Validation Error: ' + JSON.stringify(data.errors || data.message));
            }
        } catch (err) {
            console.error(err);
        }
    });

    // Confirm Delete
    document.getElementById('confirmDeleteBtn').addEventListener('click', async () => {
        if (!currentContactIdToDelete) return;
        try {
            const response = await fetch(`${apiBaseUrl}/api/contacts/${currentContactIdToDelete}/`, {
                method: 'DELETE',
                headers: getAuthHeaders()
            });
            const data = await response.json();
            deleteContactModal.hide();
            if (response.ok) {
                loadContacts();
            } else {
                alert('Delete Error: ' + (data.message || 'Permission denied'));
            }
        } catch (err) {
            console.error(err);
        }
    });

    // Filter listeners
    [searchBox, filterCompany, filterStatus, filterSalesperson, filterDesignation].forEach(el => {
        el.addEventListener('input', loadContacts);
        el.addEventListener('change', loadContacts);
    });

    loadUsers();
    loadContacts();
});
