from django.dispatch import receiver
from accounts.signals import registration_approved
from leads.models import UserProfile
from roles.services import RoleService

@receiver(registration_approved)
def provision_crm_workspace(sender, user, organization, **kwargs):
    """
    Onboards a newly approved tenant user into the CRM module workspace
    by creating or updating their UserProfile based on organization plan.
    """
    has_crm = False
    if organization.plan:
        has_crm = organization.plan.modules.filter(code='sales-crm').exists()
    else:
        has_crm = True  # Default to True for legacy/test organizations with no plan

    if has_crm:
        from roles.services import RoleService
        role_obj = RoleService.get_default_admin_role()
        u_type = 'ADMIN'
    else:
        role_obj = None
        u_type = 'USER'

    profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={'user_type': u_type, 'role': role_obj, 'organization': organization}
    )
    if not created:
        profile.user_type = u_type
        profile.role = role_obj
        profile.organization = organization
        profile.save()
