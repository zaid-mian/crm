from django.urls import path
from dashboard.views import (
    DashboardSummaryView,
    PipelineFunnelView,
    RecentActivityView,
    UpcomingFollowupsView,
    ChartDataView
)

app_name = 'dashboard'

urlpatterns = [
    path('dashboard/summary/', DashboardSummaryView.as_view(), name='dashboard-summary'),
    path('dashboard/pipeline/', PipelineFunnelView.as_view(), name='dashboard-pipeline'),
    path('dashboard/activity/', RecentActivityView.as_view(), name='dashboard-activity'),
    path('dashboard/followups/', UpcomingFollowupsView.as_view(), name='dashboard-followups'),
    path('dashboard/charts/', ChartDataView.as_view(), name='dashboard-charts'),
]
