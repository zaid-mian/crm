from rest_framework.permissions import BasePermission
from django.apps import apps

class IsSupportStaff(BasePermission):
    """
    Permission class allowing access to helpdesk administrative functions
    (e.g., ticket assignment, global ticketing lists) for staff users,
    superusers, or CRM users with a support-specific dynamic role.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True
        
        # Check dynamic CRM roles if the leads app is loaded
        if apps.is_installed('leads'):
            try:
                profile = getattr(request.user, 'profile', None) or getattr(request.user, 'userprofile', None)
                if profile:
                    if profile.user_type == 'ADMIN':
                        return True
                    if profile.role and profile.role.name in ('Administrator', 'Support Agent', 'Support Manager'):
                        return True
            except Exception:
                pass
                
        return False
