document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const rolesList = document.getElementById('rolesList');
    const roleDetailsCard = document.getElementById('roleDetailsCard');
    const noRoleSelectedCard = document.getElementById('noRoleSelectedCard');
    const selectedRoleName = document.getElementById('selectedRoleName');
    const systemRoleBadge = document.getElementById('systemRoleBadge');
    
    const roleNameInput = document.getElementById('roleNameInput');
    const roleDescriptionInput = document.getElementById('roleDescriptionInput');
    const saveRoleMetaBtn = document.getElementById('saveRoleMetaBtn');
    const deleteRoleBtn = document.getElementById('deleteRoleBtn');
    const savePermissionsBtn = document.getElementById('savePermissionsBtn');
    const permissionMatrixBody = document.getElementById('permissionMatrixBody');
    
    const createRoleForm = document.getElementById('createRoleForm');
    const newRoleName = document.getElementById('newRoleName');
    const newRoleDescription = document.getElementById('newRoleDescription');
    const createRoleModalEl = document.getElementById('createRoleModal');
    const createRoleModal = new bootstrap.Modal(createRoleModalEl);
    const addRoleBtn = document.getElementById('addRoleBtn');
    
    const clearLogsBtn = document.getElementById('clearLogsBtn');
    const devConsoleLog = document.getElementById('devConsoleLog');
    const mainAlertContainer = document.getElementById('mainAlertContainer');

    // Global State
    let allResources = [];
    let activeRole = null;

    // Show banner notifications
    function showAlert(message, type = 'success') {
        mainAlertContainer.innerHTML = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                <strong>${type === 'danger' ? 'Error:' : 'Success:'}</strong> ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
    }

    // Set connected base display
    document.getElementById('connectedBaseDisplay').innerText = APIClient.getBaseUrl();

    // Dev Console Panel logger wiring
    window.addEventListener('crm-api-log', (e) => {
        if (!devConsoleLog) return;
        const placeholder = devConsoleLog.querySelector('.text-muted');
        if (placeholder) placeholder.remove();
        
        const log = e.detail;
        const item = document.createElement('div');
        item.className = `log-item p-2 mb-2 border-start border-3 border-${log.status >= 400 ? 'danger' : (log.status >= 300 ? 'warning' : 'success')} bg-light text-dark rounded-end`;
        item.style.fontSize = '0.75rem';
        
        item.innerHTML = `
            <div class="d-flex justify-content-between font-weight-semibold">
                <span>${log.method} ${new URL(log.url).pathname}</span>
                <span class="badge bg-${log.status >= 400 ? 'danger' : 'success'}">${log.status}</span>
            </div>
            <div class="text-muted mt-1" style="font-size: 0.65rem;">Time: ${log.timestamp} | Latency: ${log.duration}ms</div>
            <div class="mt-1">
                <a href="#" class="view-payload-btn text-primary text-decoration-none small" style="font-size: 0.65rem;">View Payload Details</a>
                <pre class="json-viewer mt-2 d-none">${JSON.stringify(log, null, 2)}</pre>
            </div>
        `;
        
        item.querySelector('.view-payload-btn').addEventListener('click', (ev) => {
            ev.preventDefault();
            const pre = item.querySelector('pre');
            pre.classList.toggle('d-none');
        });
        
        devConsoleLog.prepend(item);
    });

    clearLogsBtn.addEventListener('click', () => {
        devConsoleLog.innerHTML = '<div class="text-muted small">No API calls recorded. Trigger actions in the UI to see fetch payloads.</div>';
    });

    // Fetch resources list (CRM modules)
    async function loadResources() {
        try {
            allResources = await APIClient.get('/api/roles/resources/');
        } catch (e) {
            showAlert('Failed to load auto-discovered CRM resources: ' + e.message, 'danger');
        }
    }

    // Populate permission matrix template rows
    function buildMatrixSkeleton() {
        permissionMatrixBody.innerHTML = '';
        const actions = ['VIEW', 'CREATE', 'EDIT', 'DELETE', 'EXPORT', 'APPROVE', 'ASSIGN'];
        
        allResources.forEach(res => {
            const tr = document.createElement('tr');
            
            // Name cell
            const tdName = document.createElement('td');
            tdName.className = 'text-start font-weight-semibold';
            tdName.innerText = res.name;
            tr.appendChild(tdName);
            
            // Action cells
            actions.forEach(action => {
                const tdAction = document.createElement('td');
                tdAction.className = 'permission-cell';
                
                const select = document.createElement('select');
                select.className = 'form-select form-select-sm scope-NONE';
                select.id = `scope-${res.codename}-${action}`;
                select.innerHTML = `
                    <option value="NONE">NONE</option>
                    <option value="OWN">OWN</option>
                    <option value="ALL">ALL</option>
                `;
                
                // Color formatting on change
                select.addEventListener('change', () => {
                    select.className = `form-select form-select-sm scope-${select.value}`;
                });
                
                tdAction.appendChild(select);
                tr.appendChild(tdAction);
            });
            
            permissionMatrixBody.appendChild(tr);
        });
    }

    // Fetch and populate Roles List
    async function loadRoles() {
        try {
            rolesList.innerHTML = '<div class="text-center py-4 text-muted">Loading roles...</div>';
            const roles = await APIClient.get('/api/roles/');
            rolesList.innerHTML = '';
            
            roles.forEach(role => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center py-3';
                button.innerHTML = `
                    <div>
                        <div class="font-weight-semibold">${role.name}</div>
                        <div class="small text-muted text-truncate" style="max-width: 200px;">${role.description || 'No description.'}</div>
                    </div>
                    ${role.is_system ? '<span class="badge bg-secondary">System</span>' : ''}
                `;
                
                button.addEventListener('click', () => {
                    // Update active styling
                    Array.from(rolesList.children).forEach(child => child.classList.remove('active'));
                    button.classList.add('active');
                    selectRole(role);
                });
                
                rolesList.appendChild(button);
            });
        } catch (e) {
            showAlert('Failed to load system roles: ' + e.message, 'danger');
        }
    }

    // Select and configure active role
    async function selectRole(role) {
        activeRole = role;
        noRoleSelectedCard.classList.add('d-none');
        roleDetailsCard.classList.remove('d-none');
        
        // Metadata inputs
        selectedRoleName.innerText = role.name;
        roleNameInput.value = role.name;
        roleDescriptionInput.value = role.description || '';
        
        // System roles protection check
        if (role.is_system) {
            systemRoleBadge.classList.remove('d-none');
            roleNameInput.disabled = true;
            deleteRoleBtn.classList.add('d-none');
        } else {
            systemRoleBadge.classList.add('d-none');
            roleNameInput.disabled = false;
            deleteRoleBtn.classList.remove('d-none');
        }
        
        buildMatrixSkeleton();
        
        // Fetch role permission configurations
        try {
            const permissions = await APIClient.get(`/api/roles/${role.id}/permissions/`);
            permissions.forEach(perm => {
                const select = document.getElementById(`scope-${perm.resource_codename}-${perm.action}`);
                if (select) {
                    select.value = perm.scope;
                    select.className = `form-select form-select-sm scope-${perm.scope}`;
                }
            });
        } catch (e) {
            showAlert('Failed to load permissions configuration: ' + e.message, 'danger');
        }
    }

    // Save Role description / rename profiles
    document.getElementById('roleMetadataForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeRole) return;
        
        const payload = {
            name: roleNameInput.value.trim(),
            description: roleDescriptionInput.value.trim()
        };
        
        try {
            const updated = await APIClient.put(`/api/roles/${activeRole.id}/`, payload);
            showAlert('Role metadata profile updated successfully.');
            loadRoles();
            // Refresh detail header
            selectedRoleName.innerText = updated.name;
            activeRole = updated;
        } catch (err) {
            showAlert(err.message, 'danger');
        }
    });

    // Save Permission Matrix Overwrites
    savePermissionsBtn.addEventListener('click', async () => {
        if (!activeRole) return;
        
        const payload = [];
        const actions = ['VIEW', 'CREATE', 'EDIT', 'DELETE', 'EXPORT', 'APPROVE', 'ASSIGN'];
        
        allResources.forEach(res => {
            actions.forEach(action => {
                const select = document.getElementById(`scope-${res.codename}-${action}`);
                if (select && select.value !== 'NONE') {
                    payload.push({
                        resource_codename: res.codename,
                        action: action,
                        scope: select.value
                    });
                }
            });
        });
        
        try {
            await APIClient.put(`/api/roles/${activeRole.id}/permissions/`, payload);
            showAlert('Role permissions matrix saved and user caches invalidated successfully!');
        } catch (e) {
            showAlert('Failed to save permissions matrix: ' + e.message, 'danger');
        }
    });

    // Open create modal
    addRoleBtn.addEventListener('click', () => {
        newRoleName.value = '';
        newRoleDescription.value = '';
        createRoleModal.show();
    });

    // Create custom role
    createRoleForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            name: newRoleName.value.trim(),
            description: newRoleDescription.value.trim()
        };
        
        try {
            await APIClient.post('/api/roles/', payload);
            createRoleModal.hide();
            showAlert('Custom role created successfully.');
            loadRoles();
        } catch (err) {
            showAlert(err.message, 'danger');
        }
    });

    // Delete custom role
    deleteRoleBtn.addEventListener('click', async () => {
        if (!activeRole || activeRole.is_system) return;
        
        if (!confirm(`Are you sure you want to delete the role "${activeRole.name}"?`)) {
            return;
        }
        
        try {
            await APIClient.delete(`/api/roles/${activeRole.id}/`);
            showAlert('Role deleted successfully.');
            activeRole = null;
            roleDetailsCard.classList.add('d-none');
            noRoleSelectedCard.classList.remove('d-none');
            loadRoles();
        } catch (err) {
            showAlert('Delete failed: ' + err.message, 'danger');
        }
    });

    // Bootstrap Initialization
    async function init() {
        await loadResources();
        await loadRoles();
    }
    
    init();
});
