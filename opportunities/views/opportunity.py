from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination

from opportunities.models import Opportunity
from opportunities.services import OpportunityQueryService, OpportunityStatsService, OpportunityWorkflowService
from opportunities.filters import OpportunityFilter, OpportunitySearchFilter
from opportunities.permissions import IsOpportunityOwnerOrManager
from opportunities.serializers import (
    OpportunityListSerializer,
    OpportunityDetailSerializer,
    OpportunityUpdateSerializer,
)
from leads.utils.responses import api_success, api_error

class OpportunityPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        total_items = self.page.paginator.count
        page_size = self.get_page_size(self.request) or self.page_size
        total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 0

        return api_success(
            data={
                "pagination": {
                    "page": self.page.number,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "total_items": total_items,
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link()
                },
                "results": data
            },
            message="Opportunities listed successfully."
        )


class OpportunityViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet
):
    """
    OpportunityViewSet coordinating list, retrieve, update, and custom operations.
    """
    queryset = Opportunity.objects.all()
    pagination_class = OpportunityPagination
    filter_backends = [DjangoFilterBackend, OpportunitySearchFilter, filters.OrderingFilter]
    filterset_class = OpportunityFilter
    ordering_fields = ['created_at', 'amount', 'expected_close_date']
    ordering = ['-created_at']
    search_fields = ['name', 'company__name']

    def get_permissions(self):
        """
        Salespeople and Managers must be authenticated.
        Row-level security applies on retrieve and update.
        """
        if self.action in ['retrieve', 'update', 'partial_update', 'change_stage']:
            permission_classes = [IsAuthenticated, IsOpportunityOwnerOrManager]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == 'list':
            return OpportunityListSerializer
        elif self.action in ['update', 'partial_update']:
            return OpportunityUpdateSerializer
        return OpportunityDetailSerializer

    def list(self, request, *args, **kwargs):
        queryset = OpportunityQueryService.get_visible_opportunities(request.user)
        queryset = self.filter_queryset(queryset)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data, message="Opportunities listed successfully.")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_success(data=serializer.data, message="Opportunity details retrieved.")

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return api_success(data=serializer.data, message="Opportunity updated successfully.")

    # Custom Action: Change Stage
    @action(detail=True, methods=['post'], url_path='change-stage')
    def change_stage(self, request, pk=None):
        opportunity = self.get_object()
        new_stage = request.data.get('stage')
        lost_reason = request.data.get('lost_reason', '')

        opportunity = OpportunityWorkflowService.change_stage(
            opportunity, new_stage, lost_reason, request.user
        )

        serializer = OpportunityDetailSerializer(opportunity)
        return api_success(data=serializer.data, message="Opportunity stage updated successfully.")

    # Custom Action: Stats
    @action(detail=False, methods=['get'])
    def stats(self, request):
        queryset = OpportunityQueryService.get_visible_opportunities(request.user)
        queryset = self.filter_queryset(queryset)
        stats_data = OpportunityStatsService.get_summary_stats(queryset)

        return api_success(
            data=stats_data,
            message="Statistics retrieved successfully."
        )
