from django.db.models import QuerySet
from opportunities.models import Opportunity

class OpportunityQueryService:
    @staticmethod
    def get_visible_opportunities(user) -> QuerySet:
        """
        Filters the Opportunity queryset based on the requesting user's role.
        Admins/Managers see all; Salespeople see only their assigned deals.
        """
        queryset = Opportunity.objects.all().select_related('assigned_salesperson', 'primary_contact', 'source_lead')
        
        if user.is_superuser or getattr(user, 'is_staff', False):
            return queryset

        if not user or not user.is_authenticated:
            return queryset
            
        return queryset.filter(assigned_salesperson=user)
