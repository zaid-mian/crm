from django.dispatch import receiver
from accounts.signals import organization_activated
from leads.models import UserProfile
from roles.services import RoleService

@receiver(organization_activated)
def provision_crm_workspace(sender, user, organization, **kwargs):
    """
    Onboards a newly approved tenant user into the CRM module workspace
    by creating or updating their UserProfile to 'ADMIN' with the
    'Administrator' dynamic RBAC system role.
    """
    role_obj = RoleService.get_default_role('Administrator')
    profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={'user_type': 'ADMIN', 'role': role_obj}
    )
    if not created:
        profile.user_type = 'ADMIN'
        profile.role = role_obj
        profile.save()
