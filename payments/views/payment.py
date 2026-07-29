from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination

from payments.filters.payment import PaymentFilter, PaymentSearchFilter
from payments.models import Payment
from payments.permissions.payment import PaymentPermission
from payments.serializers.payment import (
    GenerateInvoiceSerializer,
    PaymentDetailSerializer,
    PaymentListSerializer,
    PaymentRecordSerializer,
    PaymentUpdateSerializer,
)
from payments.services.documents import render_invoice_pdf, render_receipt_pdf
from payments.services.query import PaymentQueryService
from leads.utils.responses import api_success


class PaymentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        total_items = self.page.paginator.count
        page_size = self.get_page_size(self.request) or self.page_size
        total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 0

        return api_success(
            data={
                'pagination': {
                    'page': self.page.number,
                    'page_size': page_size,
                    'total_pages': total_pages,
                    'total_items': total_items,
                    'next': self.get_next_link(),
                    'previous': self.get_previous_link(),
                },
                'results': data,
            },
            message='Payments listed successfully.',
        )


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all().distinct()
    permission_classes = [IsAuthenticated, PaymentPermission]
    pagination_class = PaymentPagination
    filter_backends = [DjangoFilterBackend, PaymentSearchFilter, filters.OrderingFilter]
    filterset_class = PaymentFilter
    ordering_fields = ['created_at', 'payment_date', 'total_amount', 'paid_amount']
    ordering = ['-created_at']
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        qs = PaymentQueryService.get_visible_payments(self.request.user, qs)
        if self.action in ['list', 'retrieve']:
            return qs.prefetch_related('transactions', 'activity_logs').distinct()
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return PaymentRecordSerializer
        if self.action in ['update', 'partial_update']:
            return PaymentUpdateSerializer
        if self.action == 'generate_invoice':
            return GenerateInvoiceSerializer
        if self.action == 'retrieve':
            return PaymentDetailSerializer
        return PaymentListSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data, message='Payments listed successfully.')

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = PaymentDetailSerializer(instance, context={'request': request})
        return api_success(data=serializer.data, message='Payment details retrieved.')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        out = PaymentDetailSerializer(payment, context={'request': request})
        return api_success(
            data=out.data,
            message='Payment recorded successfully.',
            status_code=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        out = PaymentDetailSerializer(payment, context={'request': request})
        return api_success(data=out.data, message='Payment updated successfully.')

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return api_success(message='Payment deleted successfully.', status_code=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='invoice')
    def generate_invoice(self, request):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        out = PaymentDetailSerializer(payment, context={'request': request})
        return api_success(
            data=out.data,
            message='Invoice generated successfully.',
            status_code=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'], url_path='invoice')
    def download_invoice(self, request, pk=None):
        payment = self.get_object()
        return render_invoice_pdf(payment)

    @action(detail=True, methods=['get'], url_path='receipt')
    def print_receipt(self, request, pk=None):
        payment = self.get_object()
        return render_receipt_pdf(payment)
