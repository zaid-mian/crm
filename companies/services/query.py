from django.db.models import QuerySet
from companies.models import Company

class CompanyQueryService:
    @staticmethod
    def get_visible_companies(user, queryset=None) -> QuerySet:
        """
        Filters the Company queryset based on the requesting user's role.
        Admins/Managers see all; Salespeople see only their assigned companies.
        """
        if queryset is None:
            queryset = Company.objects.all()
            
        queryset = queryset.select_related('assigned_salesperson')
        
        if user.is_superuser or getattr(user, 'is_staff', False):
            return queryset
            
        return queryset.filter(assigned_salesperson=user)
