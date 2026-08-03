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
        from roles.permissions import get_scoped_queryset
        return get_scoped_queryset(queryset, user, resource_codename='opportunities', owner_field='assigned_salesperson')
