from django.apps import AppConfig


class RolesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'roles'

    def ready(self):
        import sys
        import os
        
        # Skip discovery during migration, system checks, or static collections
        ignored_commands = {'makemigrations', 'migrate', 'showmigrations', 'check', 'collectstatic'}
        if any(cmd in sys.argv for cmd in ignored_commands):
            return
            
        # Skip executing in the parent supervisor thread of runserver autoreloader
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return

        from roles.registry import CRMRegistry
        CRMRegistry.discover_resources()
