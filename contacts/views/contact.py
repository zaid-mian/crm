from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets, status, filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from roles.permissions import DynamicCRMPermission, get_scoped_queryset

from contacts.models import Contact
from contacts.services import ContactQueryService
from contacts.filters import ContactFilter, ContactSearchFilter
from contacts.utils.responses import api_success
from contacts.serializers import (
    ContactListSerializer,
    ContactDetailSerializer,
    ContactCreateSerializer,
    ContactUpdateSerializer,
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
    queryset = Contact.objects.filter(is_deleted=False).select_related('company', 'assigned_salesperson')
    permission_classes = [IsAuthenticated, DynamicCRMPermission]
    resource_codename = 'contacts'
    owner_field = 'assigned_salesperson'
    pagination_class = ContactPagination

    filter_backends = [DjangoFilterBackend, ContactSearchFilter, filters.OrderingFilter]
    filterset_class = ContactFilter
    search_fields = ['full_name', 'phone_number', 'email', 'company__name', 'designation']
    ordering_fields = ['created_at', 'updated_at', 'full_name', 'company__name', 'status']
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

    def perform_create(self, serializer):
        user = self.request.user
        from roles.services import PermissionService
        scope = PermissionService.get_permission_scope(user, 'contacts', 'ASSIGN')
        if scope == 'NONE':
            return serializer.save(assigned_salesperson=user)
        else:
            return serializer.save()

    def perform_update(self, serializer):
        user = self.request.user
        from roles.services import PermissionService
        scope = PermissionService.get_permission_scope(user, 'contacts', 'ASSIGN')
        if scope == 'NONE':
            return serializer.save(assigned_salesperson=serializer.instance.assigned_salesperson)
        else:
            return serializer.save()

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
        contact = self.perform_create(serializer)
        
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
        contact = self.perform_update(serializer)

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
