from leads.models import Lead

class LeadQueryService:
    """Handles read queries and scopes lead visibility based on user access."""
    
    @staticmethod
    def get_visible_leads(user, base_queryset=None):
        if base_queryset is None:
            base_queryset = Lead.objects.all()
            
        # Optimize query execution by pre-fetching salesperson relation
        base_queryset = base_queryset.select_related('assigned_salesperson')
            
        from roles.permissions import get_scoped_queryset
        return get_scoped_queryset(base_queryset, user, resource_codename='leads', owner_field='assigned_salesperson')
