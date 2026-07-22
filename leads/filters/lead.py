import django_filters
from leads.models import Lead

class LeadFilter(django_filters.FilterSet):
    """
    Dedicated FilterSet supporting range matching on created dates and
    membership queries.
    """
    created_at_after = django_filters.DateTimeFilter(field_name="created_at", lookup_expr='gte')
    created_at_before = django_filters.DateTimeFilter(field_name="created_at", lookup_expr='lte')

    class Meta:
        model = Lead
        fields = {
            'status': ['exact', 'in'],
            'priority': ['exact', 'in'],
            'source': ['exact', 'in'],
            'assigned_salesperson': ['exact', 'isnull'],
        }
