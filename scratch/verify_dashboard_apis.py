import time
import requests
from django.contrib.auth import get_user_model

# We will run this script locally with django context initialized
# to create a test user, run the dev server, hit the endpoints, and print outputs.

def main():
    session = requests.Session()
    base_url = "http://127.0.0.1:8000"

    print("--- 1. Authenticating ---")
    login_url = f"{base_url}/api/login/"
    # We will log in with the test admin user
    login_data = {
        "username": "admin_user_test",
        "password": "password123"
    }
    r = session.post(login_url, json=login_data)
    print("Login Status Code:", r.status_code)
    print("Login Response JSON:", r.json())
    
    # Define endpoints
    endpoints = {
        "Summary": "/api/dashboard/summary/",
        "Pipeline": "/api/dashboard/pipeline/",
        "Activity": "/api/dashboard/activity/",
        "Followups": "/api/dashboard/followups/",
        "Charts": "/api/dashboard/charts/"
    }

    # Verify each endpoint
    for name, path in endpoints.items():
        print(f"\n--- 2. Fetching {name} Endpoint: {path} ---")
        url = f"{base_url}{path}"
        
        # Measure latency
        start_time = time.time()
        res1 = session.get(url)
        elapsed1 = time.time() - start_time
        print(f"Request 1 Status: {res1.status_code} | Latency: {elapsed1:.4f}s")
        print("Response Keys/Shape:", list(res1.json().keys()) if isinstance(res1.json(), dict) else f"List length {len(res1.json())}")

        if name in ["Summary", "Pipeline", "Charts"]:
            # Measure cached response latency
            start_time = time.time()
            res2 = session.get(url)
            elapsed2 = time.time() - start_time
            print(f"Request 2 (Cached) Status: {res2.status_code} | Latency: {elapsed2:.4f}s")
            # Verify data is identical
            print("Responses Match:", res1.json() == res2.json())

if __name__ == "__main__":
    main()
