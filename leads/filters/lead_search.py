import re
from rest_framework.filters import SearchFilter

class LeadSearchFilter(SearchFilter):
    """
    Custom search filter capable of querying properties (e.g. Lead Code).
    If search terms match the 'LD-XXXXXX' format, filters dynamically by database ID.
    Otherwise, delegates to normal field text search.
    """
    def filter_queryset(self, request, queryset, view):
        search_terms = self.get_search_terms(request)
        if search_terms:
            for term in search_terms:
                # Matches patterns like 'LD-12' or 'LD-000100'
                match = re.match(r'^LD-(\d+)$', term, re.IGNORECASE)
                if match:
                    parsed_id = int(match.group(1))
                    return queryset.filter(id=parsed_id)
        return super().filter_queryset(request, queryset, view)
