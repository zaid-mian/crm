from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination

from contacts.models import Contact, Opportunity, Task
from contacts.services import ContactQueryService
from contacts.filters import ContactFilter, ContactSearchFilter
from contacts.permissions import IsContactOwnerOrManager
from contacts.utils.responses import api_success, api_error
from contacts.serializers import (
    ContactListSerializer,
    ContactDetailSerializer,
    ContactCreateSerializer,
    ContactUpdateSerializer,
    OpportunitySerializer,
    TaskSerializer,
)

class ContactPagination(PageNumberPagination):
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
            message="Contacts listed successfully."
        )


class ContactViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet
):
    queryset = Contact.objects.filter(is_deleted=False)
    permission_classes = [IsAuthenticated, IsContactOwnerOrManager]
    pagination_class = ContactPagination

    filter_backends = [DjangoFilterBackend, ContactSearchFilter, filters.OrderingFilter]
    filterset_class = ContactFilter
    search_fields = ['full_name', 'phone_number', 'email', 'company_name', 'designation']
    ordering_fields = ['created_at', 'updated_at', 'full_name', 'company_name', 'status']
    ordering = ['-created_at']

    serializer_action_classes = {
        'create': ContactCreateSerializer,
        'update': ContactUpdateSerializer,
        'partial_update': ContactUpdateSerializer,
        'retrieve': ContactDetailSerializer,
        'list': ContactListSerializer,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        return ContactQueryService.get_visible_contacts(self.request.user, qs)

    def get_serializer_class(self):
        return self.serializer_action_classes.get(self.action, ContactListSerializer)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return api_success(
            data={"results": serializer.data},
            message="Contacts listed successfully."
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_success(
            data=serializer.data,
            message="Contact details retrieved."
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact = serializer.save()
        
        detail_serializer = ContactDetailSerializer(contact)
        return api_success(
            data=detail_serializer.data,
            message="Contact created successfully.",
            status_code=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        contact = serializer.save()

        detail_serializer = ContactDetailSerializer(contact)
        return api_success(
            data=detail_serializer.data,
            message="Contact updated successfully."
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete()
        return api_success(
            data=None,
            message="Contact deleted successfully.",
            status_code=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='opportunities')
    def create_opportunity(self, request, pk=None):
        contact = self.get_object()
        name = request.data.get('name')
        stage = request.data.get('stage', 'Negotiation')
        value = request.data.get('value', '$15,000')

        if not name:
            return api_error("Opportunity name is required.")

        opp = Opportunity.objects.create(contact=contact, name=name, stage=stage, value=value)
        return api_success(
            data=OpportunitySerializer(opp).data,
            message="Opportunity created successfully.",
            status_code=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'], url_path='tasks')
    def create_task(self, request, pk=None):
        contact = self.get_object()
        name = request.data.get('name')
        status_val = request.data.get('status', 'Pending')

        if not name:
            return api_error("Task name is required.")

        t = Task.objects.create(contact=contact, name=name, status=status_val)
        return api_success(
            data=TaskSerializer(t).data,
            message="Task created successfully.",
            status_code=status.HTTP_201_CREATED
        )
