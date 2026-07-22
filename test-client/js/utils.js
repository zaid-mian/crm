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
}

// Bind to window to allow global reuse across modules
window.UIUtils = UIUtils;
