from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination

from leads.models import Lead
from leads.services import LeadQueryService, LeadStatsService, LeadWorkflowService
from leads.filters import LeadFilter, LeadSearchFilter
from leads.permissions import IsAdminOrSalesManager, IsLeadOwnerOrManager, is_manager_or_admin
from leads.utils.responses import api_success, api_error
from leads.serializers import (
    LeadListSerializer,
    LeadDetailSerializer,
    LeadCreateSerializer,
    LeadUpdateSerializer,
    LeadAssignSerializer,
    LeadLostSerializer,
)

class LeadPagination(PageNumberPagination):
    """Pagination that wraps results inside a dedicated pagination object."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        total_items = self.page.paginator.count
        page_size = self.get_page_size(self.request) or self.page_size
        total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 0

        # Format standardized response envelope
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
            message="Leads listed successfully."
        )


class LeadViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet
):
    """
    LeadViewSet coordinating list, retrieve, update, and custom operations.
    Delegates query logic to LeadQueryService and transitions to LeadWorkflowService.
    """
    queryset = Lead.objects.all()
    permission_classes = [IsAuthenticated, IsLeadOwnerOrManager]
    pagination_class = LeadPagination
    
    # Filter engine registration
    filter_backends = [DjangoFilterBackend, LeadSearchFilter, filters.OrderingFilter]
    filterset_class = LeadFilter
    search_fields = ['full_name', 'phone', 'email', 'company_name']
    ordering_fields = ['created_at', 'priority', 'status', 'updated_at']
    ordering = ['-created_at']

    # Declarative action-to-serializer lookup map
    serializer_action_classes = {
        'create': LeadCreateSerializer,
        'update': LeadUpdateSerializer,
        'partial_update': LeadUpdateSerializer,
        'retrieve': LeadDetailSerializer,
        'list': LeadListSerializer,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        return LeadQueryService.get_visible_leads(self.request.user, qs)

    def get_serializer_class(self):
        return self.serializer_action_classes.get(self.action, LeadListSerializer)

    # Standard actions overridden for custom wrapping
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return api_success(
            data={"results": serializer.data},
            message="Leads listed successfully."
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_success(
            data=serializer.data,
            message="Lead details retrieved."
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return api_success(
            data=serializer.data,
            message="Lead created successfully.",
            status_code=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # Converted leads cannot be modified
        if instance.is_converted:
            return api_error("Converted leads are read-only and cannot be modified.")

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return api_success(
            data=serializer.data,
            message="Lead updated successfully."
        )

    # Custom Action: Assign Lead
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdminOrSalesManager])
    def assign(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        salesperson = serializer.validated_data['assigned_salesperson']
        lead = LeadWorkflowService.assign_salesperson(lead, salesperson)

        return api_success(
            data={
                "id": lead.id,
                "lead_code": lead.lead_code,
                "status": lead.status,
                "assigned_salesperson": lead.assigned_salesperson_id,
                "updated_at": lead.updated_at
            },
            message="Lead assigned successfully."
        )

    # Custom Action: Convert Lead
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdminOrSalesManager])
    def convert(self, request, pk=None):
        lead = self.get_object()
        lead = LeadWorkflowService.convert_lead(lead)

        return api_success(
            data={
                "id": lead.id,
                "lead_code": lead.lead_code,
                "status": lead.status,
                "is_converted": lead.is_converted,
                "converted_at": lead.converted_at,
                "updated_at": lead.updated_at
            },
            message="Lead converted successfully."
        )

    # Custom Action: Mark Lost
    @action(detail=True, methods=['post'])
    def lost(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadLostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data['lost_reason']
        notes = serializer.validated_data.get('lost_notes', '')
        lead = LeadWorkflowService.mark_lead_lost(lead, reason, notes)

        return api_success(
            data={
                "id": lead.id,
                "lead_code": lead.lead_code,
                "status": lead.status,
                "lost_reason": lead.lost_reason,
                "lost_notes": lead.lost_notes,
                "updated_at": lead.updated_at
            },
            message="Lead marked as Lost."
        )

    # Custom Action: Mark Contacted
    @action(detail=True, methods=['post'])
    def contacted(self, request, pk=None):
        lead = self.get_object()
        lead = LeadWorkflowService.mark_contacted(lead)

        return api_success(
            data={
                "id": lead.id,
                "lead_code": lead.lead_code,
                "status": lead.status,
                "updated_at": lead.updated_at
            },
            message="Lead marked as Contacted."
        )

    # Custom Action: Stats
    @action(detail=False, methods=['get'])
    def stats(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        stats_data = LeadStatsService.get_status_grouped_stats(queryset)

        return api_success(
            data=stats_data,
            message="Statistics retrieved successfully."
        )
