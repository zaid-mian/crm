import os
import sys
import json
import django
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = ['*']

from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse

# Custom JSON encoder to handle Decimal objects
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

User = get_user_model()

admin_user = User.objects.get(username='admin')
sales_user = User.objects.get(username='salesperson2')

client = Client()

endpoints = {
    "summary": reverse('dashboard:dashboard-summary'),
    "pipeline": reverse('dashboard:dashboard-pipeline'),
    "activity": reverse('dashboard:dashboard-activity'),
    "followups": reverse('dashboard:dashboard-followups'),
    "charts": reverse('dashboard:dashboard-charts')
}

for role, user in [("Admin", admin_user), ("Salesperson", sales_user)]:
    print(f"\n==========================================")
    print(f"ROLE: {role} (User: {user.username})")
    print(f"==========================================\n")
    client.force_login(user)
    
    for name, url in endpoints.items():
        res = client.get(url)
        print(f"--- GET {url} ---")
        # Use our custom encoder to dump response
        data = res.data if hasattr(res, 'data') else res.json()
        print(json.dumps(data, cls=DecimalEncoder, indent=2))
        print()
