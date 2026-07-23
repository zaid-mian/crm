from django_filters import rest_framework as filters
from contacts.models import Contact

class ContactFilter(filters.FilterSet):
    full_name = filters.CharFilter(field_name='full_name', lookup_expr='icontains')
    company_name = filters.CharFilter(field_name='company__name', lookup_expr='icontains')
    designation = filters.CharFilter(field_name='designation', lookup_expr='icontains')
    status = filters.CharFilter(field_name='status', lookup_expr='iexact')
    assigned_salesperson = filters.NumberFilter(field_name='assigned_salesperson_id')

    class Meta:
        model = Contact
        fields = ['full_name', 'company_name', 'designation', 'status', 'assigned_salesperson']
