from rest_framework import permissions

def is_manager_or_admin(user):
    """Central role-check evaluation."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or getattr(user, 'is_staff', False) or user.groups.filter(name='Sales Manager').exists()

class IsAdminOrSalesManager(permissions.BasePermission):
    """Endpoint access restricted to Admin or Sales Manager users."""
    def has_permission(self, request, view):
        return is_manager_or_admin(request.user)

class IsOpportunityOwnerOrManager(permissions.BasePermission):
    """Row-level access protection: Owner or Manager."""
    def has_object_permission(self, request, view, obj):
        if is_manager_or_admin(request.user):
            return True
        return obj.assigned_salesperson == request.user
