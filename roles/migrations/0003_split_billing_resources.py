from django.db import migrations

GRANULAR_BILLING_RESOURCES = [
    ('billing_analytics', 'Revenue Analytics'),
    ('billing_customers', 'Billing Customers'),
    ('billing_subscriptions', 'Subscriptions'),
    ('billing_invoices', 'Invoices'),
    ('billing_payments', 'Payments Ledger'),
]

def split_billing_resources(apps, schema_editor):
    CRMResource = apps.get_model('roles', 'CRMResource')
    RolePermission = apps.get_model('roles', 'RolePermission')

    # 1. Create the 5 new granular resources
    new_resources = {}
    for codename, name in GRANULAR_BILLING_RESOURCES:
        res, _ = CRMResource.objects.get_or_create(
            codename=codename,
            defaults={'name': name}
        )
        new_resources[codename] = res

    # 2. Look for existing monolithic 'billing' resource and clone its permissions
    old_billing_res = CRMResource.objects.filter(codename='billing').first()
    if old_billing_res:
        existing_billing_perms = list(RolePermission.objects.filter(resource=old_billing_res))
        for old_perm in existing_billing_perms:
            for new_res in new_resources.values():
                RolePermission.objects.get_or_create(
                    role=old_perm.role,
                    resource=new_res,
                    action=old_perm.action,
                    defaults={'scope': old_perm.scope}
                )
        # 3. Delete the legacy monolithic 'billing' resource
        old_billing_res.delete()

    # Invalidate cache if redis/cache is available
    try:
        from django.core.cache import cache
        cache.clear()
    except Exception:
        pass


def reverse_split_billing_resources(apps, schema_editor):
    CRMResource = apps.get_model('roles', 'CRMResource')
    RolePermission = apps.get_model('roles', 'RolePermission')

    # Re-create monolithic 'billing' resource
    billing_res, _ = CRMResource.objects.get_or_create(
        codename='billing',
        defaults={'name': 'Billing'}
    )

    # Delete the 5 granular resources
    for codename, _ in GRANULAR_BILLING_RESOURCES:
        CRMResource.objects.filter(codename=codename).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('roles', '0002_backfill_roles'),
    ]

    operations = [
        migrations.RunPython(split_billing_resources, reverse_code=reverse_split_billing_resources),
    ]
