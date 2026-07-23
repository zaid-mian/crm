from rest_framework import permissions

def is_manager_or_admin(user):
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.is_staff or user.groups.filter(name='Sales Manager').exists()

class IsCompanyOwnerOrManager(permissions.BasePermission):
    """Row-level access protection: Owner or Manager."""
    def has_object_permission(self, request, view, obj):
        if is_manager_or_admin(request.user):
            return True
        return obj.assigned_salesperson == request.user
