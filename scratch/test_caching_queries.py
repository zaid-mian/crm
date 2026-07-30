import os
import sys
import time
import django
from django.db import connection

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = ['*']

from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.cache import cache

User = get_user_model()
user = User.objects.get(username='admin')

client = Client()
client.force_login(user)

url = reverse('dashboard:dashboard-summary')

# Clear Cache
cache.clear()

print("--- 1. First Request (Uncached) ---")
connection.queries_log.clear()
start_time = time.time()
res1 = client.get(url)
duration1 = time.time() - start_time
queries1 = len(connection.queries)
print(f"Status: {res1.status_code} | Latency: {duration1:.6f}s | Query Count: {queries1}")

# Show list of queries executed in first request (first 5 for brevity)
print("First few SQL queries executed:")
for idx, q in enumerate(connection.queries[:5], 1):
    print(f"  {idx}. {q['sql'][:120]}...")

print("\n--- 2. Second Request (Cached) ---")
connection.queries_log.clear()
start_time = time.time()
res2 = client.get(url)
duration2 = time.time() - start_time
queries2 = len(connection.queries)
print(f"Status: {res2.status_code} | Latency: {duration2:.6f}s | Query Count: {queries2}")
print("Second SQL queries executed:")
for idx, q in enumerate(connection.queries, 1):
    print(f"  {idx}. {q['sql'][:120]}...")

# Explain caching result
cache_key = f"dashboard_summary_user_{user.id}"
print(f"\nCache Key Used: {cache_key}")
print(f"Performance Gain: {((duration1 - duration2) / duration1 * 100):.2f}% speedup")
is_bypassed = all("django_session" in q['sql'] or "auth_user" in q['sql'] or "leads_userprofile" in q['sql'] for q in connection.queries)
print("Is Database Bypassed for aggregations? ", is_bypassed)
