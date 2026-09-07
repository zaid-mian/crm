from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.api.responses import api_success

from dashboard.services import DashboardService
from dashboard.serializers import (
    DashboardSummarySerializer,
    PipelineFunnelSerializer,
    DashboardActivitySerializer,
    FollowUpSerializer,
    ChartDataSerializer
)


def _extract_filters(request):
    return {
        'pipeline_id': request.GET.get('pipeline_id') or request.GET.get('pipeline'),
        'salesperson_id': request.GET.get('salesperson_id') or request.GET.get('salesperson'),
        'date_range': request.GET.get('date_range'),
    }


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filters = _extract_filters(request)
        cache_key = f"dashboard_summary_u{request.user.id}_p{filters['pipeline_id']}_s{filters['salesperson_id']}_d{filters['date_range']}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return api_success(data=cached_data, message="Dashboard summary metrics retrieved successfully")

        data = DashboardService.get_summary_metrics(request.user, filters)
        serializer = DashboardSummarySerializer(data)
        response_data = serializer.data
        cache.set(cache_key, response_data, timeout=30)
        return api_success(data=response_data, message="Dashboard summary metrics retrieved successfully")


class PipelineFunnelView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filters = _extract_filters(request)
        cache_key = f"dashboard_pipeline_u{request.user.id}_p{filters['pipeline_id']}_s{filters['salesperson_id']}_d{filters['date_range']}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return api_success(data=cached_data, message="Pipeline funnel metrics retrieved successfully")

        data = DashboardService.get_pipeline_funnel(request.user, filters)
        serializer = PipelineFunnelSerializer(data, many=True)
        response_data = serializer.data
        cache.set(cache_key, response_data, timeout=30)
        return api_success(data=response_data, message="Pipeline funnel metrics retrieved successfully")


class RecentActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filters = _extract_filters(request)
        data = DashboardService.get_recent_activities(request.user, filters)
        serializer = DashboardActivitySerializer(data, many=True)
        return api_success(data=serializer.data, message="Recent activity logs retrieved successfully")


class UpcomingFollowupsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filters = _extract_filters(request)
        data = DashboardService.get_upcoming_followups(request.user, filters)
        serializer = FollowUpSerializer(data, many=True)
        return api_success(data=serializer.data, message="Upcoming follow-up items retrieved successfully")


class ChartDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filters = _extract_filters(request)
        cache_key = f"dashboard_charts_u{request.user.id}_p{filters['pipeline_id']}_s{filters['salesperson_id']}_d{filters['date_range']}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return api_success(data=cached_data, message="Analytical chart metrics retrieved successfully")

        data = DashboardService.get_chart_data(request.user, filters)
        serializer = ChartDataSerializer(data)
        response_data = serializer.data
        cache.set(cache_key, response_data, timeout=30)
        return api_success(data=response_data, message="Analytical chart metrics retrieved successfully")


class UserPerformanceReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from dashboard.services import UserReportingService
        filters = {
            'search': request.GET.get('search'),
            'role_id': request.GET.get('role_id'),
            'date_from': request.GET.get('date_from'),
            'date_to': request.GET.get('date_to'),
            'pipeline_id': request.GET.get('pipeline_id'),
        }
        data = UserReportingService.get_user_performance_report(request.user, filters)
        return api_success(data=data, message="User performance report retrieved successfully")


class LeaderboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filters = _extract_filters(request)
        data = DashboardService.get_leaderboard(request.user, filters)
        return api_success(data=data, message="Leaderboard retrieved successfully")


class UserPerformancePDFView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.http import HttpResponse
        from playwright.sync_api import sync_playwright

        html_content = request.data.get('html_content')
        if not html_content:
            from core.api.responses import api_error
            return api_error(message="html_content is required.", status_code=400)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_content, wait_until='networkidle')
            pdf_bytes = page.pdf(
                format='A4',
                margin={'top': '20px', 'right': '20px', 'bottom': '20px', 'left': '20px'},
                print_background=True
            )
            browser.close()

        filename = request.data.get('filename') or 'User_Performance_Report.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
