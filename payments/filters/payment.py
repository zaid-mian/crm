from django_filters import rest_framework as filters
from rest_framework.filters import SearchFilter

from payments.models import Payment


class PaymentFilter(filters.FilterSet):
    status = filters.CharFilter(field_name='status', lookup_expr='iexact')
    company = filters.NumberFilter(field_name='company__id')
    payment_method = filters.CharFilter(field_name='transactions__payment_method', lookup_expr='iexact')
    assigned_salesperson = filters.NumberFilter(field_name='assigned_salesperson__id')
    date_after = filters.DateFilter(field_name='payment_date', lookup_expr='gte')
    date_before = filters.DateFilter(field_name='payment_date', lookup_expr='lte')

    class Meta:
        model = Payment
        fields = [
            'status',
            'company',
            'payment_method',
            'assigned_salesperson',
            'date_after',
            'date_before',
        ]


class PaymentSearchFilter(SearchFilter):
    search_param = 'search'

    def get_search_fields(self, view, request):
        return [
            'invoice_number',
            'company__name',
            'opportunity__name',
            'transactions__transaction_reference',
            'notes',
        ]
