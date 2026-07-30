from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from dashboard.services import DashboardService
from dashboard.serializers import (
    DashboardSummarySerializer,
    PipelineFunnelSerializer,
    DashboardActivitySerializer,
    FollowUpSerializer,
    ChartDataSerializer
)


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cache_key = f"dashboard_summary_user_{request.user.id}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        data = DashboardService.get_summary_metrics(request.user)
        serializer = DashboardSummarySerializer(data)
        response_data = serializer.data
        cache.set(cache_key, response_data, timeout=60)
        return Response(response_data)


class PipelineFunnelView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cache_key = f"dashboard_pipeline_user_{request.user.id}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        data = DashboardService.get_pipeline_funnel(request.user)
        serializer = PipelineFunnelSerializer(data, many=True)
        response_data = serializer.data
        cache.set(cache_key, response_data, timeout=60)
        return Response(response_data)


class RecentActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = DashboardService.get_recent_activities(request.user)
        serializer = DashboardActivitySerializer(data, many=True)
        return Response(serializer.data)


class UpcomingFollowupsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = DashboardService.get_upcoming_followups(request.user)
        serializer = FollowUpSerializer(data, many=True)
        return Response(serializer.data)


class ChartDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cache_key = f"dashboard_charts_user_{request.user.id}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        data = DashboardService.get_chart_data(request.user)
        serializer = ChartDataSerializer(data)
        response_data = serializer.data
        cache.set(cache_key, response_data, timeout=60)
        return Response(response_data)
