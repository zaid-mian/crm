import re
import django_filters
from rest_framework.filters import SearchFilter
from opportunities.models import Opportunity

class OpportunityFilter(django_filters.FilterSet):
    """
    FilterSet supporting parameters for opportunities.
    """
    created_at_after = django_filters.DateTimeFilter(field_name="created_at", lookup_expr='gte')
    created_at_before = django_filters.DateTimeFilter(field_name="created_at", lookup_expr='lte')
    expected_close_date_after = django_filters.DateFilter(field_name="expected_close_date", lookup_expr='gte')
    expected_close_date_before = django_filters.DateFilter(field_name="expected_close_date", lookup_expr='lte')

    class Meta:
        model = Opportunity
        fields = {
            'stage': ['exact', 'in'],
            'assigned_salesperson': ['exact', 'isnull'],
            'lead_source': ['exact', 'in'],
        }


class OpportunitySearchFilter(SearchFilter):
    """
    Custom search filter supporting lookup by Opportunity Code (OP-XXXXXX or OPXXXXXX).
    """
    def filter_queryset(self, request, queryset, view):
        search_terms = self.get_search_terms(request)
        if search_terms:
            for term in search_terms:
                match = re.match(r'^OP-?(\d+)$', term, re.IGNORECASE)
                if match:
                    parsed_id = int(match.group(1))
                    return queryset.filter(id=parsed_id)
        return super().filter_queryset(request, queryset, view)
