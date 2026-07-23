import re
from django_filters import rest_framework as django_filters
from rest_framework.filters import SearchFilter
from companies.models import Company

class CompanyFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    type = django_filters.CharFilter(field_name='type', lookup_expr='iexact')
    rating = django_filters.CharFilter(field_name='rating', lookup_expr='iexact')
    industry = django_filters.CharFilter(field_name='industry', lookup_expr='iexact')
    assigned_salesperson = django_filters.NumberFilter(field_name='assigned_salesperson_id')

    class Meta:
        model = Company
        fields = ['name', 'type', 'rating', 'industry', 'assigned_salesperson']


class CompanySearchFilter(SearchFilter):
    """
    Custom search filter supporting lookup by Company Code (CO-XXXXXX or COXXXXXX).
    """
    def filter_queryset(self, request, queryset, view):
        search_terms = self.get_search_terms(request)
        if search_terms:
            for term in search_terms:
                match = re.match(r'^CO-?(\d+)$', term, re.IGNORECASE)
                if match:
                    parsed_id = int(match.group(1))
                    return queryset.filter(id=parsed_id)
        return super().filter_queryset(request, queryset, view)
