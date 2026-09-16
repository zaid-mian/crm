def get_billing_tenant_organization(user):
    """
    Resolves the organization for a given user at runtime without static imports from CRM domain apps.
    1. Returns None if user is anonymous or unauthenticated.
    2. Inspects user.ownerprofile (defined in accounts).
    3. Inspects user.profile (runtime descriptor attached to User instance by leads.UserProfile).
    4. For platform staff / superusers without an organization, returns None (allowing platform access).
    """
    if not user or not user.is_authenticated:
        return None

    # Check accounts.OwnerProfile descriptor
    owner_profile = getattr(user, 'ownerprofile', None)
    if owner_profile and getattr(owner_profile, 'organization', None):
        return owner_profile.organization

    # Check user profile descriptor attached to User at runtime
    profile = getattr(user, 'profile', None)
    if profile and getattr(profile, 'organization', None):
        return profile.organization

    return None
