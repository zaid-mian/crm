/**
 * CRM Dashboard Module JS Controller.
 * Handles fetching dynamic metrics, rendering pipeline funnel Chart.js bar charts,
 * Lead Sources & Payment doughnut charts, activities feeds, follow-up alarms,
 * and quick-creating new records via API Client.
 */
document.addEventListener('DOMContentLoaded', () => {
    // Check credentials
    const username = localStorage.getItem('auth_username');
    const userType = localStorage.getItem('user_type');
    if (!username) {
        window.location.href = 'login.html';
        return;
    }

    // Populate user display
    const userUsernameSpan = document.getElementById('userUsername') || document.getElementById('adminUsername');
    if (userUsernameSpan) {
        userUsernameSpan.innerText = username;
    }

    // Set logout handler
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                await APIClient.post('/api/logout/');
            } catch (e) {
                // Ignore logout errors
            }
            localStorage.removeItem('auth_username');
            localStorage.removeItem('auth_password');
            localStorage.removeItem('user_type');
            window.location.href = 'login.html';
        });
    }

    // Relative timestamp helper for activity timeline
    function getRelativeTime(timestamp) {
        const elapsed = Date.now() - new Date(timestamp).getTime();
        const mins = Math.round(elapsed / 60000);
        const hours = Math.round(mins / 60);
        const days = Math.round(hours / 24);

        if (mins < 1) return 'just now';
        if (mins < 60) return `${mins}m ago`;
        if (hours < 24) return `${hours}h ago`;
        return `${days}d ago`;
    }

    // Relative due date helper for reminders list
    function getRelativeDueDate(dateStr) {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const dueDate = new Date(dateStr);
        dueDate.setHours(0, 0, 0, 0);

        const diffTime = dueDate.getTime() - today.getTime();
        const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

        if (diffDays === 0) return 'Today';
        if (diffDays === 1) return 'Tomorrow';
        if (diffDays === -1) return 'Yesterday';
        if (diffDays > 1) return `${diffDays} days left`;
        return `${Math.abs(diffDays)} days ago`;
    }

    // Load Dashboard Data
    async function loadDashboard() {
        try {
            await Promise.all([
                loadSummary(),
                loadPipeline(),
                loadActivity(),
                loadFollowups(),
                loadCharts()
            ]);
            // Update last updated timestamp in footer
            document.getElementById('lastUpdatedTime').innerText = new Date().toLocaleTimeString();
        } catch (err) {
            console.error("Error loading dashboard data:", err);
        }
    }

    async function loadSummary() {
        const data = await APIClient.get('/api/dashboard/summary/');
        
        document.getElementById('kpiTotalLeads').innerText = data.total_leads;
        document.getElementById('kpiNewLeads').innerText = data.new_leads;
        document.getElementById('kpiConvertedLeads').innerText = data.converted_leads;
        
        document.getElementById('kpiActiveOpps').innerText = data.active_opportunities;
        document.getElementById('kpiWonDeals').innerText = data.won_deals;
        document.getElementById('kpiLostDeals').innerText = data.lost_deals;
        
        document.getElementById('kpiPipelineValue').innerText = '$' + parseFloat(data.total_pipeline_value).toLocaleString(undefined, {minimumFractionDigits: 2});
        document.getElementById('kpiWonRevenue').innerText = '$' + parseFloat(data.won_revenue).toLocaleString(undefined, {minimumFractionDigits: 2});
        document.getElementById('kpiAvgDealSize').innerText = '$' + parseFloat(data.average_deal_size).toLocaleString(undefined, {minimumFractionDigits: 2});
        
        document.getElementById('kpiPendingPayments').innerText = '$' + parseFloat(data.pending_payments).toLocaleString(undefined, {minimumFractionDigits: 2});
        document.getElementById('kpiPaidPayments').innerText = '$' + parseFloat(data.paid_payments).toLocaleString(undefined, {minimumFractionDigits: 2});
        
        document.getElementById('kpiTotalCompanies').innerText = data.total_companies;
        document.getElementById('kpiTotalContacts').innerText = data.total_contacts;
        document.getElementById('kpiConversionRate').innerText = parseFloat(data.conversion_rate).toFixed(1) + '%';
    }

    // Chart instances references to allow dynamic reloading/redrawing
    let pipelineChartInstance = null;
    let leadSourcesChartInstance = null;
    let paymentsChartInstance = null;

    // Custom inline plugin to display record values directly next to/on horizontal bars
    const barValuePlugin = {
        id: 'barValuePlugin',
        afterDatasetsDraw(chart, args, options) {
            const { ctx } = chart;
            ctx.save();
            ctx.font = 'bold 11px Inter';
            ctx.fillStyle = '#f8fafc';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';

            chart.data.datasets.forEach((dataset, i) => {
                const meta = chart.getDatasetMeta(i);
                meta.data.forEach((bar, index) => {
                    const count = dataset.data[index];
                    const val = chart.options.pipelineValues[index];
                    const valueText = `${count} records ($${parseFloat(val).toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})})`;
                    // Display text 8 pixels to the right of the bar boundary
                    ctx.fillText(valueText, bar.x + 8, bar.y);
                });
            });
            ctx.restore();
        }
    };

    async function loadPipeline() {
        const data = await APIClient.get('/api/dashboard/pipeline/');
        const canvas = document.getElementById('pipelineFunnelChart');
        
        if (pipelineChartInstance) {
            pipelineChartInstance.destroy();
        }

        // Refinement: Filter and hide empty pipeline stages
        const activeStages = data.filter(stage => (stage.lead_count + stage.opportunity_count) > 0 || parseFloat(stage.total_value) > 0);

        if (activeStages.length === 0) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = "#94a3b8";
            ctx.font = "14px Inter";
            ctx.textAlign = "center";
            ctx.fillText("No active pipeline stages found.", canvas.width / 2, canvas.height / 2);
            return;
        }

        const labels = activeStages.map(stage => `${stage.stage_name} (${stage.entity_type})`);
        const counts = activeStages.map(stage => stage.lead_count + stage.opportunity_count);
        const colors = activeStages.map(stage => stage.color || '#3b82f6');
        const values = activeStages.map(stage => parseFloat(stage.total_value || 0));

        pipelineChartInstance = new Chart(canvas, {
            type: 'bar',
            plugins: [barValuePlugin],
            data: {
                labels: labels,
                datasets: [{
                    data: counts,
                    backgroundColor: colors,
                    borderRadius: 6,
                    borderWidth: 0,
                    barThickness: 16
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                pipelineValues: values, // Attach to options for inline plugin access
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94a3b8' }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { color: '#f8fafc', font: { family: 'Inter', size: 11 } }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            afterBody: function(context) {
                                const index = context[0].dataIndex;
                                const val = values[index];
                                return `Total Value: $${val.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
                            }
                        }
                    }
                }
            }
        });
    }

    async function loadActivity() {
        const data = await APIClient.get('/api/dashboard/activity/');
        const container = document.getElementById('recentActivityContainer');
        container.innerHTML = '';
        
        if (data.length === 0) {
            container.innerHTML = '<div class="text-muted py-2 small"><i class="bi bi-info-circle"></i> No recent activity logs.</div>';
            return;
        }

        // Build vertical timeline with relative times
        let html = '<div class="crm-timeline">';
        data.forEach(act => {
            let badgeClass = 'bg-primary text-white';
            let iconClass = 'bi-bell-fill';
            
            if (act.type === 'LEAD_CREATED') {
                badgeClass = 'bg-primary text-white';
                iconClass = 'bi-person-plus-fill';
            } else if (act.type === 'LEAD_CONVERTED') {
                badgeClass = 'bg-warning text-dark';
                iconClass = 'bi-person-check-fill';
            } else if (act.type === 'OPPORTUNITY_WON') {
                badgeClass = 'bg-success text-white';
                iconClass = 'bi-award-fill';
            } else if (act.type === 'PAYMENT_RECEIVED') {
                badgeClass = 'bg-info text-dark';
                iconClass = 'bi-cash-coin';
            } else if (act.type === 'COMPANY_CREATED') {
                badgeClass = 'bg-secondary text-white';
                iconClass = 'bi-building-fill';
            }

            html += `
                <div class="crm-timeline-item">
                    <div class="crm-timeline-badge ${badgeClass}">
                        <i class="bi ${iconClass}"></i>
                    </div>
                    <div>
                        <div class="small text-white font-weight-medium">${act.description}</div>
                        <div class="text-secondary" style="font-size: 0.72rem;">${getRelativeTime(act.timestamp)}</div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    async function loadFollowups() {
        const data = await APIClient.get('/api/dashboard/followups/');
        const container = document.getElementById('upcomingFollowupsContainer');
        container.innerHTML = '';
        
        if (data.length === 0) {
            container.innerHTML = '<div class="text-muted py-2 small"><i class="bi bi-info-circle"></i> No upcoming reminders.</div>';
            return;
        }

        data.forEach(f => {
            let priorityBadge = 'bg-secondary text-light';
            if (f.priority === 'HIGH') priorityBadge = 'bg-danger text-white';
            if (f.priority === 'MEDIUM') priorityBadge = 'bg-warning text-dark';

            const followupHtml = `
                <div class="d-flex mb-3 align-items-center justify-content-between border-bottom border-secondary border-opacity-10 pb-2">
                    <div>
                        <div class="small font-weight-semibold text-white">${f.title}</div>
                        <div class="text-secondary" style="font-size: 0.72rem;">
                            <span class="text-warning font-weight-medium">${getRelativeDueDate(f.date)}</span> (${f.date})
                        </div>
                    </div>
                    <span class="badge ${priorityBadge}" style="font-size: 0.65rem;">${f.priority}</span>
                </div>
            `;
            container.insertAdjacentHTML('beforeend', followupHtml);
        });
    }

    async function loadCharts() {
        const data = await APIClient.get('/api/dashboard/charts/');
        
        // 1. Lead Sources Doughnut Chart
        const srcCanvas = document.getElementById('leadSourcesChart');
        if (leadSourcesChartInstance) {
            leadSourcesChartInstance.destroy();
        }

        const sources = data.lead_sources;
        const srcLabels = Object.keys(sources);
        const srcData = Object.values(sources);
        const srcSum = srcData.reduce((a, b) => a + b, 0);

        if (srcSum === 0) {
            leadSourcesChartInstance = new Chart(srcCanvas, {
                type: 'doughnut',
                data: {
                    labels: ['No Lead Data'],
                    datasets: [{
                        data: [1],
                        backgroundColor: ['#475569'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right', labels: { color: '#94a3b8', font: { family: 'Inter', size: 10 } } }
                    }
                }
            });
        } else {
            leadSourcesChartInstance = new Chart(srcCanvas, {
                type: 'doughnut',
                data: {
                    labels: srcLabels,
                    datasets: [{
                        data: srcData,
                        backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right', labels: { color: '#94a3b8', font: { family: 'Inter', size: 10 } } }
                    }
                }
            });
        }

        // 2. Payments Doughnut Chart
        const ps = data.payment_summary;
        const payCanvas = document.getElementById('paymentsSummaryChart');
        
        if (paymentsChartInstance) {
            paymentsChartInstance.destroy();
        }

        // Update raw numbers below chart
        document.getElementById('psPaidAmount').innerText = '$' + parseFloat(ps.paid.amount).toLocaleString(undefined, {minimumFractionDigits: 2});
        document.getElementById('psPendingAmount').innerText = '$' + parseFloat(ps.pending.amount).toLocaleString(undefined, {minimumFractionDigits: 2});
        document.getElementById('psOverdueAmount').innerText = '$' + parseFloat(ps.overdue.amount).toLocaleString(undefined, {minimumFractionDigits: 2});

        const payData = [parseFloat(ps.paid.amount), parseFloat(ps.pending.amount), parseFloat(ps.overdue.amount)];
        const paySum = payData.reduce((a, b) => a + b, 0);

        if (paySum === 0) {
            paymentsChartInstance = new Chart(payCanvas, {
                type: 'doughnut',
                data: {
                    labels: ['No Invoices'],
                    datasets: [{
                        data: [1],
                        backgroundColor: ['#475569'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right', labels: { color: '#94a3b8', font: { family: 'Inter', size: 10 } } }
                    }
                }
            });
        } else {
            paymentsChartInstance = new Chart(payCanvas, {
                type: 'doughnut',
                data: {
                    labels: ['Paid', 'Pending', 'Overdue'],
                    datasets: [{
                        data: payData,
                        backgroundColor: ['#10b981', '#f59e0b', '#ef4444'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right', labels: { color: '#94a3b8', font: { family: 'Inter', size: 10 } } }
                    }
                }
            });
        }
    }

    // Quick Actions Form API Verification
    const actionResult = document.getElementById('quickActionResult');
    function logResult(success, message) {
        actionResult.className = `alert mt-3 py-2 small ${success ? 'alert-success' : 'alert-danger'}`;
        actionResult.innerText = message;
        actionResult.classList.remove('d-none');
        setTimeout(() => actionResult.classList.add('d-none'), 5000);
    }

    document.getElementById('qaNewLead').addEventListener('click', async () => {
        try {
            const mockLead = {
                full_name: "Mock Lead " + Math.round(Math.random() * 1000),
                company_name: "Mock Corp",
                source: "WEBSITE",
                priority: "MEDIUM"
            };
            const res = await APIClient.post('/api/leads/', mockLead);
            logResult(true, `Quick Action: Lead '${res.full_name}' created successfully (API Verified).`);
            loadDashboard();
        } catch (err) {
            logResult(false, `API Error: ${err.message || 'Failed to create lead.'}`);
        }
    });

    document.getElementById('qaNewCompany').addEventListener('click', async () => {
        try {
            const mockCompany = {
                name: "Mock Company " + Math.round(Math.random() * 1000),
                type: "PROSPECT",
                industry: "TECHNOLOGY"
            };
            const res = await APIClient.post('/api/companies/', mockCompany);
            logResult(true, `Quick Action: Company '${res.name}' created successfully (API Verified).`);
            loadDashboard();
        } catch (err) {
            logResult(false, `API Error: ${err.message || 'Failed to create company.'}`);
        }
    });

    document.getElementById('qaNewOpportunity').addEventListener('click', async () => {
        try {
            const companies = await APIClient.get('/api/companies/');
            const contacts = await APIClient.get('/api/contacts/');
            const leads = await APIClient.get('/api/leads/');
            
            if (companies.length === 0 || contacts.length === 0 || leads.length === 0) {
                logResult(false, "To create an opportunity, please create a Lead, Company, and Contact first.");
                return;
            }

            const mockOpp = {
                name: "Mock Opp " + Math.round(Math.random() * 1000),
                company: companies[0].id,
                source_lead: leads[0].id,
                primary_contact: contacts[0].id,
                stage: "QUALIFICATION",
                amount: "15000.00",
                priority: "MEDIUM",
                expected_close_date: new Date(Date.now() + 30*24*60*60*1000).toISOString().split('T')[0]
            };
            const res = await APIClient.post('/api/opportunities/', mockOpp);
            logResult(true, `Quick Action: Opportunity '${res.name}' created successfully (API Verified).`);
            loadDashboard();
        } catch (err) {
            logResult(false, `API Error: ${err.message || 'Failed to create opportunity.'}`);
        }
    });

    // Run Dashboard Initial Load
    loadDashboard();
});
