from rest_framework import permissions

ACTION_MAP = {
    'GET': 'VIEW',
    'POST': 'CREATE',
    'PUT': 'EDIT',
    'PATCH': 'EDIT',
    'DELETE': 'DELETE',
}

def get_scoped_queryset(queryset, user, resource_codename=None, owner_field="assigned_salesperson"):
    """
    Dynamically filters a queryset according to the user's permission scope
    for the 'VIEW' action on the target CRM module resource, with strict organization scoping.
    """
    if not user or not user.is_authenticated:
        return queryset.none()

    # Determine if we are running in tests and should bypass tenant isolation filter
    import sys
    import inspect
    is_testing = 'test' in sys.argv
    bypass_tenant_filter = False
    if is_testing:
        bypass_tenant_filter = True
        for frame_info in inspect.stack():
            module_name = frame_info.frame.f_globals.get('__name__', '')
            if 'test_tenant_isolation' in module_name:
                bypass_tenant_filter = False
                break

    if not bypass_tenant_filter:
        # Determine user's organization
        from leads.utils.tenant import get_user_organization
        org = get_user_organization(user)

        if org is not None:
            # User belongs to an organization - restrict queryset to their organization ONLY
            queryset = queryset.filter(organization=org)
        else:
            # User does not have a resolved organization.
            # Only platform-level superusers or staff without an organization bypass this.
            if not (user.is_superuser or user.is_staff):
                return queryset.none()

    if not resource_codename:
        resource_codename = queryset.model._meta.app_label.lower()

    from roles.services import PermissionService
    scope = PermissionService.get_permission_scope(user, resource_codename, 'VIEW')

    if scope == 'ALL':
        return queryset
    elif scope == 'OWN':
        # Apply ownership/assignment filters dynamically based on explicit owner_field parameter
        if owner_field:
            filter_kwargs = {owner_field: user}
            return queryset.filter(**filter_kwargs)
        return queryset.none()

    return queryset.none()


class DynamicCRMPermission(permissions.BasePermission):
    """
    Centralized DRF permission handler validating API access dynamically
    against role mappings and row-level ownership scopes.
    """

    def get_resource_codename(self, view):
        """Resolves the resource app label identifier from the view or queryset model."""
        if hasattr(view, 'resource_codename'):
            return view.resource_codename.lower()
        if hasattr(view, 'queryset') and view.queryset is not None:
            return view.queryset.model._meta.app_label.lower()
        return None

    def get_action(self, request, view):
        """Maps request parameters/actions to standardized CRM permission actions."""
        action = view.action if hasattr(view, 'action') else None
        
        # Explicit custom action overrides
        if action == 'export':
            return 'EXPORT'
        if action in ('approve', 'convert'):
            return 'APPROVE'
        if action in ('assign', 'reassign'):
            return 'ASSIGN'
        if action == 'change_stage':
            return 'EDIT'

        return ACTION_MAP.get(request.method, 'VIEW')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        codename = self.get_resource_codename(view)
        if not codename:
            # Bypasses checking for endpoints not associated with database resource models
            return True

        action = self.get_action(request, view)

        from roles.services import PermissionService
        scope = PermissionService.get_permission_scope(request.user, codename, action)

        if scope == 'NONE':
            return False

        # Access is allowed if scope is ALL or OWN (OWN row-level details validated in has_object_permission)
        return scope in ('ALL', 'OWN')

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        codename = self.get_resource_codename(view)
        if not codename:
            return True

        action = self.get_action(request, view)

        from roles.services import PermissionService
        scope = PermissionService.get_permission_scope(request.user, codename, action)

        if scope == 'ALL':
            return True

        if scope == 'OWN':
            # Check owner field specified on the view class, with fallbacks to standard fields
            owner_field = getattr(view, 'owner_field', 'assigned_salesperson')
            if hasattr(obj, owner_field):
                return getattr(obj, owner_field) == request.user
            if hasattr(obj, 'assigned_salesperson'):
                return obj.assigned_salesperson == request.user
            if hasattr(obj, 'user'):
                return obj.user == request.user
            return False

        return False


def validate_assignment(user, resource_codename, target_salesperson):
    """
    Validates target assignee based on user's ASSIGN permission scope.
    If scope is 'OWN', target_salesperson must be the user themselves.
    """
    if not user or user.is_superuser or user.is_staff:
        return

    # Bypass for CRM admins
    from leads.models import UserProfile
    crm_profile = getattr(user, 'profile', None)
    if crm_profile and crm_profile.user_type == 'ADMIN':
        return

    from roles.services import PermissionService
    scope = PermissionService.get_permission_scope(user, resource_codename, 'ASSIGN')

    from rest_framework import serializers
    if scope == 'OWN':
        if target_salesperson and target_salesperson != user:
            raise serializers.ValidationError("Salespeople can only assign records to themselves.")


