from roles.models import Role

class RoleService:
    @staticmethod
    def get_default_role(role_name):
        """
        Resolves system roles by name, dynamically creating them if absent 
        to prevent lookup crashes or database anomalies during bootstrapping.
        """
        defaults = {
            "is_system": True,
            "description": f"Default system role for {role_name}"
        }
        if role_name == "Administrator":
            defaults["description"] = "System Administrator with full capabilities"
        elif role_name == "Salesperson":
            defaults["description"] = "Sales agent scoped to assigned pipeline data"
        elif role_name == "Manager":
            defaults["description"] = "Manager with scoped administrative capabilities"
            
        role, _ = Role.objects.get_or_create(name=role_name, defaults=defaults)
        return role

class PermissionService:
    @staticmethod
    def get_permission_cache_key(user_id):
        return f"permissions_user_{user_id}"

    @classmethod
    def get_permission_scope(cls, user, resource_codename, action):
        """
        Resolves the permission scope ('ALL', 'OWN', 'NONE') for a given user,
        resource, and action, utilizing user-scoped response caching.
        """
        if not user or not user.is_authenticated:
            return 'NONE'
            
        # Superuser always has full global scope
        if user.is_superuser:
            return 'ALL'

        from django.core.cache import cache
        cache_key = cls.get_permission_cache_key(user.id)
        
        # Try retrieving resolved permissions dict from cache
        perms_dict = cache.get(cache_key)
        
        if perms_dict is None:
            # Cache miss - compute permissions dynamically from DB
            perms_dict = cls.compute_user_permissions(user)
            cache.set(cache_key, perms_dict, timeout=3600)  # Cache for 1 hour

        res_code = resource_codename.lower()
        if perms_dict and res_code in perms_dict and action in perms_dict[res_code]:
            return perms_dict[res_code][action]

        return 'NONE'

    @classmethod
    def compute_user_permissions(cls, user):
        """Compiles the permission matrix for a user based on their assigned Role."""
        from leads.models import UserProfile
        from roles.models import RolePermission, CRMResource

        try:
            profile = user.profile
            role = profile.role
        except (UserProfile.DoesNotExist, AttributeError):
            return {}

        if not role:
            return {}

        perms_dict = {}

        # 1. Fetch explicitly configured permissions from the database
        role_permissions = list(RolePermission.objects.filter(role=role).select_related('resource'))
        
        if role_permissions:
            for p in role_permissions:
                res_code = p.resource.codename.lower()
                if res_code not in perms_dict:
                    perms_dict[res_code] = {}
                perms_dict[res_code][p.action] = p.scope
            return perms_dict

        # 2. Otherwise (clean test database or unconfigured role), fallback to baseline system defaults
        resources = ['leads', 'companies', 'contacts', 'opportunities', 'payments', 'pipeline']
        is_admin_or_manager = (
            role.name in ("Administrator", "Manager") or 
            user.is_superuser or 
            user.is_staff or 
            user.groups.filter(name='Sales Manager').exists()
        )
        
        for res_code in resources:
            perms_dict[res_code] = {}
            if is_admin_or_manager:
                for act in ('VIEW', 'CREATE', 'EDIT', 'DELETE', 'EXPORT', 'APPROVE', 'ASSIGN'):
                    perms_dict[res_code][act] = 'ALL'
            else:
                for act in ('VIEW', 'CREATE', 'EDIT'):
                    perms_dict[res_code][act] = 'OWN'
                for act in ('DELETE', 'EXPORT', 'APPROVE', 'ASSIGN'):
                    perms_dict[res_code][act] = 'NONE'
            
        return perms_dict

    @classmethod
    def clear_user_permission_cache(cls, user_id):
        from django.core.cache import cache
        cache_key = cls.get_permission_cache_key(user_id)
        cache.delete(cache_key)

