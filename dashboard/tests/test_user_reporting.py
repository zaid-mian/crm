from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal

from accounts.models import Organization
from leads.models import Lead, UserProfile
from opportunities.models import Opportunity, OpportunityStage
from pipeline.models import Pipeline, PipelineStage
from roles.models import Role, CRMResource, RolePermission
from roles.services import RoleService

User = get_user_model()


class UserReportingAPITestCase(TestCase):
    def setUp(self):
        # 1. Create Organizations
        self.org1 = Organization.objects.create(name="Organization One", is_active=True)
        self.org2 = Organization.objects.create(name="Organization Two", is_active=True)

        # 2. Roles
        self.admin_role = RoleService.get_default_admin_role()
        
        self.manager_role, _ = Role.objects.get_or_create(
            name="Salesperson Manager",
            defaults={"description": "Manager Role"}
        )
        self.sales_role = RoleService.get_default_role("Salesperson")

        # Give Manager Role ALL permissions on leads and opportunities
        resource_lead, _ = CRMResource.objects.get_or_create(codename="leads", name="Leads")
        resource_opp, _ = CRMResource.objects.get_or_create(codename="opportunities", name="Opportunities")
        RolePermission.objects.get_or_create(role=self.manager_role, resource=resource_lead, action="VIEW", defaults={"scope": "ALL"})
        RolePermission.objects.get_or_create(role=self.manager_role, resource=resource_opp, action="VIEW", defaults={"scope": "ALL"})

        # Give Salesperson Role OWN permissions on leads and opportunities
        RolePermission.objects.get_or_create(role=self.sales_role, resource=resource_lead, action="VIEW", defaults={"scope": "OWN"})
        RolePermission.objects.get_or_create(role=self.sales_role, resource=resource_opp, action="VIEW", defaults={"scope": "OWN"})

        # 3. Create Users in Org 1
        self.admin1 = User.objects.create_user(
            username="admin1@org1.com",
            email="admin1@org1.com",
            password="Password123!",
            first_name="Admin",
            last_name="One",
            is_active=True
        )
        UserProfile.objects.filter(user=self.admin1).update(user_type='ADMIN', role=self.admin_role, organization=self.org1)

        self.manager1 = User.objects.create_user(
            username="manager1@org1.com",
            email="manager1@org1.com",
            password="Password123!",
            first_name="Manager",
            last_name="One",
            is_active=True
        )
        UserProfile.objects.filter(user=self.manager1).update(user_type='USER', role=self.manager_role, organization=self.org1)

        self.salesperson1 = User.objects.create_user(
            username="sales1@org1.com",
            email="sales1@org1.com",
            password="Password123!",
            first_name="Shahreen",
            last_name="Sales",
            is_active=True
        )
        UserProfile.objects.filter(user=self.salesperson1).update(user_type='USER', role=self.sales_role, organization=self.org1)

        # 4. Create Users in Org 2 (Cross-Tenant)
        self.admin2 = User.objects.create_user(
            username="admin2@org2.com",
            email="admin2@org2.com",
            password="Password123!",
            first_name="Admin",
            last_name="Two",
            is_active=True
        )
        UserProfile.objects.filter(user=self.admin2).update(user_type='ADMIN', role=self.admin_role, organization=self.org2)

        self.salesperson2 = User.objects.create_user(
            username="sales2@org2.com",
            email="sales2@org2.com",
            password="Password123!",
            first_name="Foreign",
            last_name="Sales",
            is_active=True
        )
        UserProfile.objects.filter(user=self.salesperson2).update(user_type='USER', role=self.sales_role, organization=self.org2)

        # 5. Pipeline Stages for Org 1
        self.pipeline1 = Pipeline.objects.create(name="Standard Pipeline Org 1", organization=self.org1, is_default=True)
        self.stage_new = PipelineStage.objects.create(pipeline=self.pipeline1, name="New", stage_type="CONVERSION", entity_type="LEAD", order=1)
        self.stage_proposal = PipelineStage.objects.create(pipeline=self.pipeline1, name="Proposal", stage_type="NORMAL_OPPORTUNITY", entity_type="OPPORTUNITY", order=2)
        self.stage_won = PipelineStage.objects.create(pipeline=self.pipeline1, name="Won", stage_type="WON", entity_type="OPPORTUNITY", order=3)
        self.stage_lost = PipelineStage.objects.create(pipeline=self.pipeline1, name="Lost", stage_type="LOST", entity_type="OPPORTUNITY", order=4)

        # 6. Pipeline Stages for Org 2
        self.pipeline2 = Pipeline.objects.create(name="Pipeline Org 2", organization=self.org2, is_default=True)
        self.stage_org2 = PipelineStage.objects.create(pipeline=self.pipeline2, name="Org 2 Stage", stage_type="CONVERSION", entity_type="LEAD", order=1)

        # 7. Create Leads and Opportunities in Org 1 for Salesperson 1
        self.lead1 = Lead.objects.create(
            organization=self.org1,
            full_name="Lead One",
            company_name="Company A",
            status="NEW",
            pipeline=self.pipeline1,
            pipeline_stage=self.stage_new,
            assigned_salesperson=self.salesperson1
        )
        self.lead2 = Lead.objects.create(
            organization=self.org1,
            full_name="Lead Two (Converted)",
            company_name="Company B",
            status="CONVERTED",
            is_converted=True,
            pipeline=self.pipeline1,
            assigned_salesperson=self.salesperson1
        )

        from companies.models import Company
        self.comp1 = Company.objects.create(name="Company A", organization=self.org1)

        self.opp_won = Opportunity.objects.create(
            organization=self.org1,
            name="Won Deal 1",
            company=self.comp1,
            source_lead=self.lead1,
            primary_contact_id=1,
            assigned_salesperson=self.salesperson1,
            amount=Decimal("50000.00"),
            expected_close_date="2026-12-31",
            stage="CLOSED_WON",
            pipeline=self.pipeline1,
            pipeline_stage=self.stage_won
        )

        self.opp_active = Opportunity.objects.create(
            organization=self.org1,
            name="Active Deal 1",
            company=self.comp1,
            source_lead=self.lead1,
            primary_contact_id=1,
            assigned_salesperson=self.salesperson1,
            amount=Decimal("30000.00"),
            expected_close_date="2026-12-31",
            stage="PROPOSAL",
            pipeline=self.pipeline1,
            pipeline_stage=self.stage_proposal
        )

        # 8. Create Records in Org 2 for Salesperson 2
        self.lead_org2 = Lead.objects.create(
            organization=self.org2,
            full_name="Foreign Lead Org 2",
            company_name="Foreign Corp",
            status="NEW",
            pipeline=self.pipeline2,
            pipeline_stage=self.stage_org2,
            assigned_salesperson=self.salesperson2
        )

        self.url = reverse('dashboard:user-performance-report')

    def test_admin_can_access_report(self):
        """1. Admin can access User Reporting endpoint."""
        self.client.login(username="admin1@org1.com", password="Password123!")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data['success'])
        self.assertIn('summary', json_data['data'])
        self.assertIn('users', json_data['data'])

    def test_sales_manager_denied_access(self):
        """2. Sales Manager is denied access (403 Forbidden)."""
        self.client.login(username="manager1@org1.com", password="Password123!")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_salesperson_denied_access(self):
        """3. Normal Salesperson is denied access (403 Forbidden)."""
        self.client.login(username="sales1@org1.com", password="Password123!")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_tenant_isolation_org1(self):
        """4 & 5. Admin and Manager see ONLY users and records from their organization."""
        self.client.login(username="admin1@org1.com", password="Password123!")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        users = response.json()['data']['users']
        user_ids = [u['user_id'] for u in users]
        
        # Org 1 users must be present
        self.assertIn(self.admin1.id, user_ids)
        self.assertIn(self.manager1.id, user_ids)
        self.assertIn(self.salesperson1.id, user_ids)

        # Org 2 users MUST NOT be present
        self.assertNotIn(self.admin2.id, user_ids)
        self.assertNotIn(self.salesperson2.id, user_ids)

    def test_cross_tenant_records_never_appear(self):
        """6. Cross-tenant records never spill into Org 1 summary totals."""
        self.client.login(username="admin1@org1.com", password="Password123!")
        response = self.client.get(self.url)
        summary = response.json()['data']['summary']

        self.assertEqual(summary['total_users'], 3)
        self.assertEqual(summary['total_leads'], 2) # Only 2 leads in Org 1, not Org 2's lead
        self.assertEqual(summary['total_opportunities'], 2)
        self.assertEqual(summary['total_won_deals'], 1)
        self.assertEqual(float(summary['total_won_revenue']), 50000.0)

    def test_correct_salesperson_aggregations(self):
        """7, 8, 9, 10. Correct lead stages, won/lost counts, and opportunity totals per salesperson."""
        self.client.login(username="admin1@org1.com", password="Password123!")
        response = self.client.get(self.url)
        users = response.json()['data']['users']

        sales1_data = next(u for u in users if u['user_id'] == self.salesperson1.id)
        self.assertEqual(sales1_data['total_leads'], 2)
        self.assertEqual(sales1_data['new_leads'], 1)
        self.assertEqual(sales1_data['converted_leads'], 1)
        self.assertEqual(sales1_data['total_opportunities'], 2)
        self.assertEqual(sales1_data['won_opportunities'], 1)
        self.assertEqual(float(sales1_data['won_revenue']), 50000.0)
        self.assertEqual(float(sales1_data['pipeline_value']), 30000.0)
        self.assertEqual(sales1_data['win_rate'], 100.0)
