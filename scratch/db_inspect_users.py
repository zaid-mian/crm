import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

print("--- USERS IN DATABASE ---")
for u in User.objects.all():
    print(f"ID: {u.id} | Username: {u.username} | Email: {u.email} | Staff: {u.is_staff} | Superuser: {u.is_superuser}")
print("-------------------------")
