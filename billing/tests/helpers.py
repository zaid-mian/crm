from roles.models import Role, RolePermission, CRMResource

BILLING_RESOURCE_CODENAMES = [
    'billing_analytics',
    'billing_customers',
    'billing_subscriptions',
    'billing_invoices',
    'billing_payments',
]

def setup_billing_test_permissions(admin_role=None, manager_role=None, sales_role=None):
    """
    Helper to set up permissions for all 5 granular Billing resources in tests.
    """
    resources = {}
    for code in BILLING_RESOURCE_CODENAMES:
        res, _ = CRMResource.objects.get_or_create(
            codename=code,
            defaults={'name': code.replace('_', ' ').title()}
        )
        resources[code] = res

        if admin_role:
            for act in ('VIEW', 'CREATE', 'EDIT', 'DELETE', 'EXPORT', 'APPROVE', 'ASSIGN'):
                RolePermission.objects.get_or_create(role=admin_role, resource=res, action=act, defaults={'scope': 'ALL'})
        if manager_role:
            for act in ('VIEW', 'CREATE', 'EDIT', 'DELETE', 'EXPORT', 'APPROVE', 'ASSIGN'):
                RolePermission.objects.get_or_create(role=manager_role, resource=res, action=act, defaults={'scope': 'ALL'})
        if sales_role:
            RolePermission.objects.get_or_create(role=sales_role, resource=res, action='VIEW', defaults={'scope': 'OWN'})
            RolePermission.objects.get_or_create(role=sales_role, resource=res, action='CREATE', defaults={'scope': 'OWN'})
            RolePermission.objects.get_or_create(role=sales_role, resource=res, action='EDIT', defaults={'scope': 'OWN'})
            RolePermission.objects.get_or_create(role=sales_role, resource=res, action='DELETE', defaults={'scope': 'NONE'})
            RolePermission.objects.get_or_create(role=sales_role, resource=res, action='EXPORT', defaults={'scope': 'NONE'})
            RolePermission.objects.get_or_create(role=sales_role, resource=res, action='APPROVE', defaults={'scope': 'NONE'})
            RolePermission.objects.get_or_create(role=sales_role, resource=res, action='ASSIGN', defaults={'scope': 'NONE'})
            
    return resources
