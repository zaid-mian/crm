from rest_framework import viewsets, status, mixins, filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from django.db.models import ProtectedError
from django_filters.rest_framework import DjangoFilterBackend

from companies.models import Company
from companies.services.query import CompanyQueryService
from companies.filters import CompanyFilter, CompanySearchFilter
from companies.permissions import IsCompanyOwnerOrManager
from companies.utils.responses import api_success
from companies.serializers import (
    CompanyListSerializer,
    CompanyDetailSerializer,
    CompanyCreateUpdateSerializer
)

class CompanyPagination(PageNumberPagination):
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
            message="Companies listed successfully."
        )


class CompanyViewSet(viewsets.ModelViewSet):
    """
    CompanyViewSet coordinating CRUD, query scoping, and delete protection.
    """
    queryset = Company.objects.all()
    permission_classes = [IsAuthenticated, IsCompanyOwnerOrManager]
    pagination_class = CompanyPagination
    filter_backends = [DjangoFilterBackend, CompanySearchFilter, filters.OrderingFilter]
    filterset_class = CompanyFilter
    ordering_fields = ['created_at', 'updated_at', 'name', 'annual_revenue']
    ordering = ['-created_at']
    search_fields = ['name', 'company_code', 'website', 'email']

    serializer_action_classes = {
        'create': CompanyCreateUpdateSerializer,
        'update': CompanyCreateUpdateSerializer,
        'partial_update': CompanyCreateUpdateSerializer,
        'retrieve': CompanyDetailSerializer,
        'list': CompanyListSerializer,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        qs = CompanyQueryService.get_visible_companies(self.request.user, qs)
        if self.action == 'list':
            return qs.select_related('assigned_salesperson')
        elif self.action == 'retrieve':
            return qs.prefetch_related('contacts', 'opportunities')
        return qs

    def get_serializer_class(self):
        return self.serializer_action_classes.get(self.action, CompanyListSerializer)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_success(
            data=serializer.data,
            message="Company details retrieved."
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = serializer.save()

        out_serializer = CompanyDetailSerializer(company)
        return api_success(
            data=out_serializer.data,
            message="Company created successfully.",
            status_code=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        company = serializer.save()

        out_serializer = CompanyDetailSerializer(company)
        return api_success(
            data=out_serializer.data,
            message="Company updated successfully.",
            status_code=status.HTTP_200_OK
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
            return api_success(message="Company deleted successfully.", status_code=status.HTTP_200_OK)
        except ProtectedError:
            contacts_count = instance.contacts.count()
            opps_count = instance.opportunities.count()
            msg = f"Cannot delete company because it has {contacts_count} related contacts and {opps_count} opportunities."
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
