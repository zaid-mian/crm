from rest_framework import permissions


def is_finance_or_admin(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_staff', False):
        return True
    return user.groups.filter(name='Finance').exists()


def is_manager_or_admin(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_staff', False):
        return True
    return user.groups.filter(name__in=['Sales Manager', 'Finance']).exists()


class PaymentPermission(permissions.BasePermission):
    """Finance/Admin modify; others read within row scope."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if view.action in ('create', 'update', 'partial_update', 'destroy', 'generate_invoice'):
            return is_finance_or_admin(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if is_manager_or_admin(request.user):
            return True
        if view.action in ('update', 'partial_update', 'destroy'):
            return is_finance_or_admin(request.user)
        return obj.assigned_salesperson_id == request.user.id
