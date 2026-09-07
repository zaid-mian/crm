import os
import sys
import django
from django.test import Client
from rest_framework import status
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, timedelta

# Add workspace directory to path and setup Django
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = ['testserver', '127.0.0.1', 'localhost']

from leads.models import Lead, UserProfile
from opportunities.models import Opportunity
from contacts.models import Contact
from companies.models import Company
from payments.models import Payment
from pipeline.models import Pipeline, PipelineStage
from roles.models import Role, CRMResource, RolePermission

User = get_user_model()

def run_qa_flow():
    print("==================================================")
    print("PHASE 2 - CRM RBAC & BUSINESS-FLOW VERIFICATION")
    print("==================================================")

    # 1. Fetch Users
    sales_user = User.objects.get(email='shahreen2005@gmail.com')
    manager_user = User.objects.get(email='mianshb_test@example.com')
    admin_user = User.objects.get(email='zaidqa_test@example.com')

    # Link Salesperson permissions (should have scope OWN for Leads, Opportunities, Contacts, Companies, Payments, Pipeline)
    print("Verifying permission scopes for Salesperson in DB...")
    sales_role = sales_user.profile.role
    print(f"Salesperson Role: {sales_role.name}")

    # Pre-run cleanup of QA testing records
    print("Clearing any existing QA records with 'phase2lead@example.com'...")
    existing_leads = Lead.objects.filter(email="phase2lead@example.com")
    for el in existing_leads:
        if el.converted_opportunity:
            el.converted_opportunity.delete()
        if el.converted_contact:
            el.converted_contact.delete()
        if el.converted_company:
            el.converted_company.delete()
        el.delete()
    
    # 2. Setup Client
    client = Client()

    # ==================================================
    # PART 1 & 2: SALESPERSON TEST (SHAHREEN)
    # ==================================================
    print("\n[PART 1 & 2] Authenticating as shahreen2005@gmail.com...")
    client.force_login(sales_user)

    # A. Check existing Leads
    response = client.get('/api/leads/')
    print(f"Leads list response status: {response.status_code}")
    leads_data = response.json().get('data', {}).get('results', [])
    print(f"Total Leads returned for Shahreen: {len(leads_data)}")
    all_own = all(lead.get('assigned_salesperson') == sales_user.id or lead.get('assigned_salesperson') is None for lead in leads_data)
    print(f"Confirm only Shahreen-owned or unassigned Leads are visible: {all_own}")

    # B. Create a new Lead (Phase 2 Test Lead)
    # Get a pipeline and stage for creation
    pipeline = Pipeline.objects.first()
    first_stage = PipelineStage.objects.filter(pipeline=pipeline, stage_type='NORMAL_LEAD').first()
    
    lead_payload = {
        "full_name": "Phase2 Test Lead",
        "email": "phase2lead@example.com",
        "phone": "03000000000",
        "company_name": "Phase 2 QA Company",
        "source": "WEBSITE",
        "priority": "MEDIUM",
        "assigned_salesperson": sales_user.id
    }
    create_lead_res = client.post('/api/leads/', data=lead_payload)
    print(f"Create Lead response status: {create_lead_res.status_code}")
    lead_id = None
    if create_lead_res.status_code == 201:
        lead_id = create_lead_res.json().get('data', {}).get('id')
        print(f"Created Lead ID: {lead_id}")
        created_lead = Lead.objects.get(pk=lead_id)
        print(f"Created Lead assigned owner: {created_lead.assigned_salesperson.email}")
    else:
        print(f"Create Lead error: {create_lead_res.json()}")

    # C. Test editing the Lead
    update_payload = {
        "full_name": "Phase2 Test Lead Updated",
        "phone": "03001111111",
        "priority": "HIGH",
        "source": "REFERRAL"
    }
    update_lead_res = client.patch(f'/api/leads/{lead_id}/', data=update_payload, content_type='application/json')
    print(f"Update Lead response status: {update_lead_res.status_code}")
    if update_lead_res.status_code == 200:
        lead_refreshed = Lead.objects.get(pk=lead_id)
        print(f"Updated Lead name: {lead_refreshed.full_name}")
        print(f"Updated Lead phone: {lead_refreshed.phone}")
        print(f"Updated Lead priority: {lead_refreshed.priority}")
        print(f"Updated Lead source: {lead_refreshed.source}")

    # D. Test direct API assignment bypass (reassign to sp1@gmail.com)
    import json
    other_sales_user = User.objects.get(email='sp1@gmail.com')
    bypass_assign_res = client.post(
        f'/api/leads/{lead_id}/assign/', 
        data=json.dumps({"assigned_salesperson": other_sales_user.id}), 
        content_type='application/json'
    )
    print(f"Reassign lead to other salesperson response status: {bypass_assign_res.status_code}")
    print(f"Reassign lead to other salesperson response body: {bypass_assign_res.json()}")
    if bypass_assign_res.status_code == 400:
        print("PASS: Backend correctly blocked reassigning to another user.")
    else:
        print(f"FAIL: Backend returned {bypass_assign_res.status_code}")

    # ==================================================
    # PART 3: LEAD -> PIPELINE CONVERSION FLOW
    # ==================================================
    print("\n[PART 3] Moving Lead and converting to Opportunity...")
    
    # Dynamically query and supply required custom fields for conversion
    custom_values = {}
    lead_refreshed = Lead.objects.get(pk=lead_id)
    if lead_refreshed.pipeline:
        try:
            custom_form = lead_refreshed.pipeline.custom_form
            if custom_form.is_active:
                for field in custom_form.fields.filter(required=True):
                    if field.field_type == 'NUMBER':
                        custom_values[field.label] = "20000"
                    elif field.field_type == 'DATE':
                        custom_values[field.label] = str(date.today() + timedelta(days=90))
                    elif field.field_type == 'CHECKBOX':
                        custom_values[field.label] = True
                    else:
                        custom_values[field.label] = "QA field value"
        except Exception as e:
            print(f"Error checking custom form: {e}")

    # Trigger Lead conversion
    # Opp data structure required
    opp_payload = {
        "opp_data": {
            "name": "Phase 2 QA Company - Initial Opportunity",
            "amount": 15000.00,
            "expected_close_date": str(date.today() + timedelta(days=30)),
            "description": "QA Opportunity description"
        },
        "custom_values": custom_values
    }
    convert_res = client.post(f'/api/leads/{lead_id}/convert/', data=opp_payload, content_type='application/json')
    print(f"Convert Lead response status: {convert_res.status_code}")
    if convert_res.status_code == 200:
        print("Lead converted successfully.")
        lead_refreshed = Lead.objects.get(pk=lead_id)
        print(f"Lead status after conversion: {lead_refreshed.status}")
        print(f"Is Lead converted: {lead_refreshed.is_converted}")
        print(f"Created Company: {lead_refreshed.converted_company.name if lead_refreshed.converted_company else 'None'}")
        print(f"Created Contact: {lead_refreshed.converted_contact.full_name if lead_refreshed.converted_contact else 'None'}")
        print(f"Created Opportunity: {lead_refreshed.converted_opportunity.name if lead_refreshed.converted_opportunity else 'None'}")
    else:
        print(f"Conversion error: {convert_res.json()}")


    # ==================================================
    # PART 4: OPPORTUNITY FLOW
    # ==================================================
    print("\n[PART 4] Checking Opportunity lifecycle...")
    created_opp = lead_refreshed.converted_opportunity
    print(f"Opportunity ID: {created_opp.id} | Name: {created_opp.name}")
    print(f"Opportunity Owner: {created_opp.assigned_salesperson.email if created_opp.assigned_salesperson else 'None'}")
    print(f"Opportunity Company: {created_opp.company.name if created_opp.company else 'None'}")
    print(f"Opportunity Primary Contact: {created_opp.primary_contact.full_name if created_opp.primary_contact else 'None'}")
    print(f"Opportunity Amount: {created_opp.amount}")

    # A. Try to change owner directly via API
    bypass_opp_assign = client.patch(f'/api/opportunities/{created_opp.id}/', data={"assigned_salesperson": other_sales_user.id}, content_type='application/json')
    print(f"Reassign Opportunity directly to other salesperson response status: {bypass_opp_assign.status_code}")
    if bypass_opp_assign.status_code == 400:
        print("PASS: Backend correctly blocked Opportunity reassignment.")
    else:
        print(f"FAIL: Backend returned {bypass_opp_assign.status_code}")

    # ==================================================
    # PART 5 & 6: COMPANIES & CONTACTS
    # ==================================================
    print("\n[PART 5 & 6] Checking Companies & Contacts...")
    # List companies
    companies_res = client.get('/api/companies/')
    companies_list = companies_res.json().get('data', {}).get('results', [])
    print(f"Total Companies returned for Shahreen: {len(companies_list)}")
    print(f"Confirm only Shahreen-owned or unassigned Companies: {all(c.get('assigned_salesperson') == sales_user.id or c.get('assigned_salesperson') is None for c in companies_list)}")

    # Try to access self.company_a from sp1@gmail.com
    # First find a company owned by salesperson1 (sp1@gmail.com)
    other_company = Company.objects.filter(assigned_salesperson=other_sales_user).first()
    if other_company:
        other_company_res = client.get(f'/api/companies/{other_company.id}/')
        print(f"Access other salesperson's company response status: {other_company_res.status_code}")
        if other_company_res.status_code == 404:
            print("PASS: Access to another salesperson's company is correctly restricted (returns 404).")
        else:
            print(f"FAIL: Returned {other_company_res.status_code}")

    # Contacts verification
    contacts_res = client.get('/api/contacts/')
    contacts_list = contacts_res.json().get('data', {}).get('results', [])
    print(f"Total Contacts returned for Shahreen: {len(contacts_list)}")
    print(f"Confirm only Shahreen-owned or unassigned Contacts: {all(c.get('assigned_salesperson') == sales_user.id or c.get('assigned_salesperson') is None for c in contacts_list)}")

    # ==================================================
    # PART 7: PAYMENTS
    # ==================================================
    print("\n[PART 7] Checking Payments...")
    payments_res = client.get('/api/payments/')
    payments_list = payments_res.json().get('data', {}).get('results', [])
    print(f"Total Payments returned for Shahreen: {len(payments_list)}")

    # ==================================================
    # PART 10-15: MANAGER TEST (MIAN)
    # ==================================================
    print("\n[PART 10-15] Authenticating as mianshb_test@example.com (Manager)...")
    client.force_login(manager_user)

    # A. Check Organization-wide access
    leads_res_mian = client.get('/api/leads/')
    leads_list_mian = leads_res_mian.json().get('data', {}).get('results', [])
    print(f"Total Leads returned for Manager: {len(leads_list_mian)}")
    
    # Check if we can see leads belonging to multiple salespeople
    salespersons = set(lead.get('assigned_salesperson') for lead in leads_list_mian if lead.get('assigned_salesperson'))
    print(f"Leads belong to {len(salespersons)} different salespersons: {salespersons}")

    # Create a temporary non-converted lead assigned to Shahreen
    temp_lead = Lead.objects.create(
        organization=sales_user.profile.organization,
        full_name="Temp Manager Lead",
        email="temp_mgr_lead@example.com",
        phone="03009999999",
        company_name="Temp Company",
        source="WEBSITE",
        assigned_salesperson=sales_user
    )
    print(f"Created temporary lead for Manager reassignment check. ID: {temp_lead.id}")

    # B. Test manager capability to assign lead to another user
    reassign_manager_res = client.post(
        f'/api/leads/{temp_lead.id}/assign/', 
        data=json.dumps({"assigned_salesperson": other_sales_user.id}), 
        content_type='application/json'
    )
    print(f"Manager reassign lead response status: {reassign_manager_res.status_code}")
    if reassign_manager_res.status_code == 200:
        temp_lead.refresh_from_db()
        print(f"Lead assigned owner after Manager action: {temp_lead.assigned_salesperson.email}")
        print("PASS: Manager can reassign records organization-wide.")
    else:
        print(f"FAIL: Manager reassignment returned {reassign_manager_res.status_code}")
        print(f"FAIL body: {reassign_manager_res.json()}")

    # Clean up the temporary lead
    temp_lead.delete()

    # ==================================================
    # PART 16: ACCOUNTS / CATALOG / SUPPORT MODULES
    # ==================================================
    print("\n[PART 16] Checking JTS Manager-Only Modules...")
    
    # 1. Catalog Dashboard
    catalog_res = client.get('/api/products/')
    print(f"Manager access to Catalog Products response status: {catalog_res.status_code}")
    
    # 2. Support Tickets
    support_res = client.get('/api/tickets/')
    print(f"Manager access to Support Tickets response status: {support_res.status_code}")
    if support_res.status_code == 200:
        print(f"Support tickets visible: {len(support_res.json())}")

    # Clean up Phase 2 test records
    print("\nCleaning up created QA records...")
    first_lead = Lead.objects.get(pk=lead_id)
    first_lead.converted_opportunity.delete()
    first_lead.converted_contact.delete()
    first_lead.converted_company.delete()
    first_lead.delete()
    print("Cleanup completed.")

if __name__ == '__main__':
    run_qa_flow()
