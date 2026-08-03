from django.db import migrations

def backfill_roles_and_permissions(apps, schema_editor):
    Role = apps.get_model('roles', 'Role')
    UserProfile = apps.get_model('leads', 'UserProfile')
    
    # Initialize standard system roles
    admin_role, _ = Role.objects.get_or_create(
        name="Administrator",
        defaults={"description": "System Administrator with full capabilities", "is_system": True}
    )
    salesperson_role, _ = Role.objects.get_or_create(
        name="Salesperson",
        defaults={"description": "Sales agent scoped to assigned pipeline data", "is_system": True}
    )
    manager_role, _ = Role.objects.get_or_create(
        name="Manager",
        defaults={"description": "Manager with scoped administrative capabilities", "is_system": True}
    )
    
    # Backfill role mapping on UserProfile
    for profile in UserProfile.objects.all():
        if profile.user_type == 'ADMIN':
            profile.role = admin_role
        else:
            profile.role = salesperson_role
        profile.save()

def reverse_backfill_roles(apps, schema_editor):
    UserProfile = apps.get_model('leads', 'UserProfile')
    for profile in UserProfile.objects.all():
        profile.role = None
        profile.save()

class Migration(migrations.Migration):

    dependencies = [
        ('roles', '0001_initial'),
        ('leads', '0008_userprofile_role'),
    ]

    operations = [
        migrations.RunPython(backfill_roles_and_permissions, reverse_code=reverse_backfill_roles),
    ]
