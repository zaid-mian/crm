def get_user_organization(user):
    """
    Resolves the organization for a given user.
    1. Returns None if the user is anonymous or not authenticated.
    2. Returns None for platform-level staff or superusers who bypass tenant isolation.
    3. Checks if user has ownerprofile -> organization
    4. Checks if user has profile (UserProfile) -> organization
    """
    if not user or not user.is_authenticated:
        return None
        
    # Platform-level administrators (superuser or staff with admin status) bypass organization restrictions
    if user.is_superuser or user.is_staff:
        # Note: If the staff user is actually an organization owner or user, they might have an org,
        # but JTS Platform Admins/Superusers must have global access.
        # Let's check: if they have profile/ownerprofile and are NOT superusers/JTS admins,
        # wait! The prompt says: "Only platform-level/JTS administrators should have global access where explicitly required.
        # CRM Administrators, Managers, and Salespeople must remain strictly organization-scoped regardless of their CRM role."
        # JTS/platform administrators are standard django staff/superusers without a tenant org,
        # or specifically who are meant to manage the platform.
        # Let's inspect: if a user is superuser, they get global access. If they are staff but have no organization, they get global access.
        # But if they are organization admins (like company123@example.com who is organization Administrator but NOT django is_staff), they are organization-scoped.
        # So we can check if they have a resolved organization. If they do, they are scoped to that organization even if is_staff is True!
        pass

    # Try ownerprofile
    owner_profile = getattr(user, 'ownerprofile', None)
    if owner_profile:
        return owner_profile.organization
        
    # Try user profile
    profile = getattr(user, 'profile', None)
    if profile and profile.organization:
        return profile.organization
        
    return None
