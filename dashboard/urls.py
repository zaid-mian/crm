from django.urls import path
from dashboard.views import (
    DashboardSummaryView,
    PipelineFunnelView,
    RecentActivityView,
    UpcomingFollowupsView,
    ChartDataView,
    UserPerformanceReportView,
    UserPerformancePDFView,
    LeaderboardView
)

app_name = 'dashboard'

urlpatterns = [
    path('dashboard/summary/', DashboardSummaryView.as_view(), name='dashboard-summary'),
    path('dashboard/pipeline/', PipelineFunnelView.as_view(), name='dashboard-pipeline'),
    path('dashboard/activity/', RecentActivityView.as_view(), name='dashboard-activity'),
    path('dashboard/followups/', UpcomingFollowupsView.as_view(), name='dashboard-followups'),
    path('dashboard/charts/', ChartDataView.as_view(), name='dashboard-charts'),
    path('dashboard/leaderboard/', LeaderboardView.as_view(), name='dashboard-leaderboard'),
    path('reports/user-performance/pdf/', UserPerformancePDFView.as_view(), name='user-performance-pdf'),
    path('reports/user-performance/', UserPerformanceReportView.as_view(), name='user-performance-report'),
    path('dashboard/user-reporting/', UserPerformanceReportView.as_view(), name='dashboard-user-reporting'),
]
