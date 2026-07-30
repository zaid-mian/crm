import os
import sys
import time
import subprocess
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Setup django environment to create seed data and verification users
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from leads.models import Lead
from companies.models import Company
from contacts.models import Contact
from opportunities.models import Opportunity
from payments.models import Payment
from pipeline.models import Pipeline, PipelineStage

User = get_user_model()

def bootstrap_data():
    print("Bootstrapping verification seed data...")
    # Create or update user
    admin_user, created = User.objects.get_or_create(
        username='admin_user_test',
        defaults={'email': 'admin_test@test.com', 'is_superuser': True, 'is_staff': True}
    )
    admin_user.set_password('password123')
    admin_user.save()

    # Seed some base models if not exist
    pipeline, _ = Pipeline.objects.get_or_create(name="Verification Pipeline", defaults={"is_default": True})
    
    stage, _ = PipelineStage.objects.get_or_create(
        pipeline=pipeline,
        name="Verification Stage New",
        defaults={"entity_type": "LEAD", "stage_type": "NORMAL_LEAD", "order": 0, "color": "#000000"}
    )
    
    company, _ = Company.objects.get_or_create(
        name="Verification Company",
        defaults={"assigned_salesperson": admin_user}
    )
    
    contact, _ = Contact.objects.get_or_create(
        full_name="Verification Contact",
        defaults={"company": company, "assigned_salesperson": admin_user}
    )
    
    lead, _ = Lead.objects.get_or_create(
        full_name="Verification Lead",
        defaults={
            "company_name": "Verification Company",
            "pipeline": pipeline,
            "pipeline_stage": stage,
            "assigned_salesperson": admin_user,
            "source": "WEBSITE",
            "status": "NEW"
        }
    )
    
    opp, _ = Opportunity.objects.get_or_create(
        name="Verification Opportunity",
        defaults={
            "company": company,
            "source_lead": lead,
            "primary_contact": contact,
            "assigned_salesperson": admin_user,
            "stage": "QUALIFICATION",
            "pipeline": pipeline,
            "pipeline_stage": stage,
            "amount": 12000.00,
            "expected_close_date": "2026-09-30"
        }
    )
    
    Payment.objects.get_or_create(
        invoice_number="INV-VERIFY-001",
        defaults={
            "company": company,
            "opportunity": opp,
            "total_amount": 12000.00,
            "paid_amount": 5000.00,
            "status": "PARTIALLY_PAID",
            "assigned_salesperson": admin_user
        }
    )
    print("Seed data bootstrapped successfully.")

def cleanup_data():
    print("Cleaning up verification data...")
    Payment.objects.filter(invoice_number="INV-VERIFY-001").delete()
    Opportunity.objects.filter(name="Verification Opportunity").delete()
    Contact.objects.filter(full_name="Verification Contact").delete()
    Lead.objects.filter(full_name="Verification Lead").delete()
    Company.objects.filter(name="Verification Company").delete()
    User.objects.filter(username='admin_user_test').delete()
    print("Cleanup completed.")

def main():
    bootstrap_data()

    # Start dev server
    print("Starting Django development server...")
    server_process = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", "127.0.0.1:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    time.sleep(3)
    
    try:
        # Run verify_dashboard_apis.py
        print("Invoking api validation...")
        from scratch import verify_dashboard_apis
        verify_dashboard_apis.main()
    finally:
        print("Stopping Django development server...")
        server_process.terminate()
        server_process.wait()
        cleanup_data()

if __name__ == "__main__":
    main()
