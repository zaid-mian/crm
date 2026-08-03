from django.apps import apps
from django.db import connection, transaction
from roles.models import CRMResource

SYSTEM_APP_PREFIXES = [
    'django.',
]
SYSTEM_APP_NAMES = {
    'corsheaders',
    'django_filters',
    'rest_framework',
    'roles',
}

def is_system_app(app_config):
    name = app_config.name
    if any(name.startswith(prefix) for prefix in SYSTEM_APP_PREFIXES):
        return True
    if name in SYSTEM_APP_NAMES:
        return True
    return False

class CRMRegistry:
    @staticmethod
    def discover_resources():
        """
        Scans registered Django applications, filters out system/Django frameworks,
        and registers non-system apps as CRMResource entries. Idempotent.
        """
        # Safety check to avoid table crashes on initial makemigrations or migrate
        try:
            if 'roles_crmresource' not in connection.introspection.table_names():
                return []
        except Exception:
            return []

        registered_resources = []
        with transaction.atomic():
            for app_config in apps.get_app_configs():
                if is_system_app(app_config):
                    continue
                
                codename = app_config.label.lower()
                name = getattr(app_config, 'verbose_name', codename.title())
                
                resource, created = CRMResource.objects.get_or_create(
                    codename=codename,
                    defaults={'name': name}
                )
                registered_resources.append(resource)
                
        return registered_resources
