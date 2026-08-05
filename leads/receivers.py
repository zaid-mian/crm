from django.dispatch import receiver
from accounts.signals import registration_approved
from leads.models import UserProfile
from roles.services import RoleService

@receiver(registration_approved)
def provision_crm_workspace(sender, user, organization, **kwargs):
    """
    Onboards a newly approved tenant user into the CRM module workspace
    by creating or updating their UserProfile to 'ADMIN' with the
    default dynamic system administrator role.
    """
    role_obj = RoleService.get_default_admin_role()
    profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={'user_type': 'ADMIN', 'role': role_obj}
    )
    if not created:
        profile.user_type = 'ADMIN'
        profile.role = role_obj
        profile.save()
