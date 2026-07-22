from leads.models import Lead

class LeadQueryService:
    """Handles read queries and scopes lead visibility based on user access."""
    
    @staticmethod
    def get_visible_leads(user, base_queryset=None):
        if base_queryset is None:
            base_queryset = Lead.objects.all()
            
        # Optimize query execution by pre-fetching salesperson relation
        base_queryset = base_queryset.select_related('assigned_salesperson')
            
        from leads.permissions import is_manager_or_admin
        if not is_manager_or_admin(user):
            # Salesperson sees only assigned leads
            return base_queryset.filter(assigned_salesperson=user)
        return base_queryset
