from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organization
from catalog.models.product import Product
from catalog.models.module import Module
from catalog.models.plan import PricingPlan, PlanModule
from billing.models import BillingCustomer, Subscription, SubscriptionItem, AddOn, SubscriptionAuditLog
from billing.services import (
    EntitlementService,
    CrmOpportunityProvisioningService,
    SubscriptionService,
)
from roles.models import Role, RolePermission, CRMResource

from billing.tests.helpers import setup_billing_test_permissions

User = get_user_model()


class CrmIntegrationBridgeTestCase(APITestCase):
    def setUp(self):
        # 1. Roles
        self.admin_role, _ = Role.objects.get_or_create(
            name='Administrator',
            defaults={'is_system': True, 'description': 'Admin'}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name='Manager',
            defaults={'is_system': True, 'description': 'Manager'}
        )

        setup_billing_test_permissions(admin_role=self.admin_role, manager_role=self.manager_role)

        # 3. Organizations
        self.org1 = Organization.objects.create(name="Acme Corp Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Beta Corp Org 2", is_active=True)

        # 4. Users
        self.user1 = User.objects.create_user(username='crm_user_org1', email='user1@org1.com', password='password123')
        self.user1.profile.organization = self.org1
        self.user1.profile.role = self.manager_role
        self.user1.profile.save()

        self.user2 = User.objects.create_user(username='crm_user_org2', email='user2@org2.com', password='password123')
        self.user2.profile.organization = self.org2
        self.user2.profile.role = self.manager_role
        self.user2.profile.save()

        # 5. Catalog Setup (Product, Modules, PricingPlan, PlanModules, AddOns)
        self.product = Product.objects.create(
            name="AdaptCRM Suite",
            slug="adaptcrm_suite",
            is_active=True
        )

        self.mod_leads = Module.objects.create(
            product=self.product,
            name="Lead Management",
            code="leads",
            is_active=True
        )
        self.mod_pipeline = Module.objects.create(
            product=self.product,
            name="Pipeline Management",
            code="pipeline",
            is_active=True
        )
        self.mod_users = Module.objects.create(
            product=self.product,
            name="User Seats",
            code="max_users",
            is_active=True
        )
        self.mod_storage = Module.objects.create(
            product=self.product,
            name="Storage",
            code="storage_gb",
            is_active=True
        )

        # Pricing Plan: Professional Plan ($99/mo)
        self.plan_pro = PricingPlan.objects.create(
            product=self.product,
            name="Professional",
            price=Decimal('99.00'),
            currency="USD",
            billing_cycle="monthly",
            is_active=True
        )

        # Plan Modules
        PlanModule.objects.create(plan=self.plan_pro, module=self.mod_leads, is_enabled=True, limit_value="500 leads")
        PlanModule.objects.create(plan=self.plan_pro, module=self.mod_pipeline, is_enabled=True, limit_value="unlimited")
        PlanModule.objects.create(plan=self.plan_pro, module=self.mod_users, is_enabled=True, limit_value="5")
        PlanModule.objects.create(plan=self.plan_pro, module=self.mod_storage, is_enabled=True, limit_value="10GB")

        # Add-ons
        self.addon_users = AddOn.objects.create(
            product=self.product,
            name="Additional User Seat",
            code="max_users",
            price=Decimal('15.00'),
            currency="USD",
            billing_cycle="monthly",
            unit_label="seat",
            is_active=True
        )
        self.addon_storage = AddOn.objects.create(
            product=self.product,
            name="Extra 10GB Storage",
            code="storage_gb",
            price=Decimal('10.00'),
            currency="USD",
            billing_cycle="monthly",
            unit_label="GB",
            is_active=True
        )

        # 6. Default Customer in Org 1
        self.customer1 = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number="CUST-90001",
            name="Acme Client Inc",
            email="client@acme.com",
            external_reference_id="crm_company_101",
            currency="USD"
        )

    # ==========================================
    # Task 1: EntitlementService Tests
    # ==========================================

    def test_entitlement_service_has_feature_active_subscription(self):
        """Active LIVE subscription within term grants access to included modules."""
        sub = Subscription.objects.create(
            subscription_number="SUB-90001",
            customer=self.customer1,
            status='LIVE',
            current_term_start=date.today() - timedelta(days=5),
            current_term_end=date.today() + timedelta(days=25),
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_pro,
            quantity=1,
            unit_price=self.plan_pro.price
        )

        self.assertTrue(EntitlementService.has_feature(self.org1.id, 'leads'))
        self.assertTrue(EntitlementService.has_feature(self.org1.id, 'pipeline'))
        self.assertFalse(EntitlementService.has_feature(self.org1.id, 'nonexistent_feature'))

    def test_entitlement_service_trial_and_non_renewing(self):
        """TRIAL and NON_RENEWING states within term grant access."""
        sub_trial = Subscription.objects.create(
            subscription_number="SUB-90002",
            customer=self.customer1,
            status='TRIAL',
            current_term_start=date.today() - timedelta(days=2),
            current_term_end=date.today() + timedelta(days=12),
        )
        SubscriptionItem.objects.create(
            subscription=sub_trial,
            item_type='PLAN',
            plan=self.plan_pro,
            quantity=1,
            unit_price=self.plan_pro.price
        )
        self.assertTrue(EntitlementService.has_feature(self.org1.id, 'leads'))

        # Switch to NON_RENEWING
        sub_trial.status = 'NON_RENEWING'
        sub_trial.save()
        self.assertTrue(EntitlementService.has_feature(self.org1.id, 'leads'))

    def test_entitlement_service_future_subscription_does_not_grant_features(self):
        """FUTURE subscriptions (current_term_start > today) MUST NOT grant features early."""
        sub_future = Subscription.objects.create(
            subscription_number="SUB-90003",
            customer=self.customer1,
            status='FUTURE',
            current_term_start=date.today() + timedelta(days=5),
            current_term_end=date.today() + timedelta(days=35),
        )
        SubscriptionItem.objects.create(
            subscription=sub_future,
            item_type='PLAN',
            plan=self.plan_pro,
            quantity=1,
            unit_price=self.plan_pro.price
        )

        self.assertFalse(EntitlementService.has_feature(self.org1.id, 'leads'))

    def test_entitlement_service_inactive_states_deny_features(self):
        """PAUSED, CANCELLED, UNPAID, and DRAFT deny access."""
        sub = Subscription.objects.create(
            subscription_number="SUB-90004",
            customer=self.customer1,
            status='PAUSED',
            current_term_start=date.today() - timedelta(days=10),
            current_term_end=date.today() + timedelta(days=20),
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_pro,
            quantity=1,
            unit_price=self.plan_pro.price
        )

        for inactive_status in ['PAUSED', 'CANCELLED', 'UNPAID', 'DRAFT']:
            sub.status = inactive_status
            sub.save()
            self.assertFalse(EntitlementService.has_feature(self.org1.id, 'leads'))

    def test_entitlement_service_limit_calculation_with_addons(self):
        """Limit calculation handles numeric aggregation with active AddOns."""
        sub = Subscription.objects.create(
            subscription_number="SUB-90005",
            customer=self.customer1,
            status='LIVE',
            current_term_start=date.today() - timedelta(days=5),
            current_term_end=date.today() + timedelta(days=25),
        )
        # Plan has 5 users
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_pro,
            quantity=1,
            unit_price=self.plan_pro.price
        )
        # Add-on provides 3 extra users
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='ADDON',
            addon=self.addon_users,
            quantity=3,
            unit_price=self.addon_users.price
        )

        limit_info = EntitlementService.get_limit(self.org1.id, 'max_users')
        self.assertTrue(limit_info['allowed'])
        self.assertEqual(limit_info['base_limit'], 5)
        self.assertEqual(limit_info['addon_quantity'], 3)
        self.assertEqual(limit_info['total_limit'], 8)

    def test_entitlement_service_unlimited_and_text_limits(self):
        """Handles unlimited and unit-bearing text limits correctly."""
        sub = Subscription.objects.create(
            subscription_number="SUB-90006",
            customer=self.customer1,
            status='LIVE',
            current_term_start=date.today() - timedelta(days=5),
            current_term_end=date.today() + timedelta(days=25),
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_pro,
            quantity=1,
            unit_price=self.plan_pro.price
        )

        # Unlimited limit: pipeline
        pipeline_limit = EntitlementService.get_limit(self.org1.id, 'pipeline')
        self.assertTrue(pipeline_limit['allowed'])
        self.assertTrue(pipeline_limit.get('is_unlimited'))

        # Unit-bearing limit: leads ("500 leads")
        leads_limit = EntitlementService.get_limit(self.org1.id, 'leads')
        self.assertTrue(leads_limit['allowed'])
        self.assertEqual(leads_limit.get('value'), "500 leads")

    def test_entitlement_tenant_isolation(self):
        """Org 1 active subscription does not give Org 2 access."""
        sub = Subscription.objects.create(
            subscription_number="SUB-90007",
            customer=self.customer1,
            status='LIVE',
            current_term_start=date.today() - timedelta(days=5),
            current_term_end=date.today() + timedelta(days=25),
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_pro,
            quantity=1,
            unit_price=self.plan_pro.price
        )

        self.assertTrue(EntitlementService.has_feature(self.org1.id, 'leads'))
        self.assertFalse(EntitlementService.has_feature(self.org2.id, 'leads'))

    # ==========================================
    # Task 2: Provisioning Service & Idempotency
    # ==========================================

    def test_provision_won_opportunity_creates_subscription_and_customer(self):
        """Provisioning a new WON opportunity creates customer and subscription cleanly."""
        payload = {
            "opportunity_id": 555,
            "company_id": 202,
            "company_name": "New Tech Corp",
            "contact_email": "billing@newtech.com",
            "plan_id": self.plan_pro.id,
            "add_ons": [
                {"addon_id": self.addon_users.id, "quantity": 2}
            ],
            "start_date": str(date.today())
        }

        result = CrmOpportunityProvisioningService.provision_won_opportunity(
            organization=self.org1,
            payload=payload,
            actor=self.user1
        )

        self.assertTrue(result['success'])
        self.assertFalse(result.get('idempotent', False))
        sub = result['subscription']
        self.assertEqual(sub.status, 'LIVE')
        self.assertEqual(sub.metadata.get('crm_opportunity_id'), 555)
        self.assertEqual(sub.items.count(), 2)

        # Audit log verified
        audit_log = SubscriptionAuditLog.objects.filter(subscription=sub, action='STATE_TRANSITION').first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.new_state, 'LIVE')

    def test_provision_won_opportunity_matches_existing_customer(self):
        """Provisioning matches existing BillingCustomer by external_reference_id."""
        payload = {
            "opportunity_id": 556,
            "company_id": 101,  # Matches self.customer1 ("crm_company_101")
            "company_name": "Acme Client Inc",
            "contact_email": "client@acme.com",
            "plan_id": self.plan_pro.id,
            "start_date": str(date.today())
        }

        result = CrmOpportunityProvisioningService.provision_won_opportunity(
            organization=self.org1,
            payload=payload,
            actor=self.user1
        )

        self.assertTrue(result['success'])
        sub = result['subscription']
        self.assertEqual(sub.customer_id, self.customer1.id)

    def test_provision_won_opportunity_concurrency_and_idempotency(self):
        """Repeated call with same opportunity_id returns idempotent response."""
        payload = {
            "opportunity_id": 777,
            "company_id": 303,
            "company_name": "Idempotent LLC",
            "contact_email": "info@idempotent.com",
            "plan_id": self.plan_pro.id,
            "start_date": str(date.today())
        }

        # First call
        res1 = CrmOpportunityProvisioningService.provision_won_opportunity(
            organization=self.org1,
            payload=payload,
            actor=self.user1
        )
        self.assertTrue(res1['success'])
        self.assertFalse(res1.get('idempotent', False))
        sub_id_1 = res1['subscription'].id

        # Second identical call
        res2 = CrmOpportunityProvisioningService.provision_won_opportunity(
            organization=self.org1,
            payload=payload,
            actor=self.user1
        )
        self.assertTrue(res2['success'])
        self.assertTrue(res2.get('idempotent', True))
        self.assertEqual(res2['subscription'].id, sub_id_1)

    # ==========================================
    # Task 3 & 4: REST API Endpoints
    # ==========================================

    def test_api_entitlements_check_feature_and_limit(self):
        """GET /api/v1/billing/entitlements/check/ handles queries accurately."""
        sub = Subscription.objects.create(
            subscription_number="SUB-90010",
            customer=self.customer1,
            status='LIVE',
            current_term_start=date.today() - timedelta(days=1),
            current_term_end=date.today() + timedelta(days=29),
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type='PLAN',
            plan=self.plan_pro,
            quantity=1,
            unit_price=self.plan_pro.price
        )

        self.client.force_authenticate(user=self.user1)

        # 1. Feature check
        resp1 = self.client.get('/api/v1/billing/entitlements/check/?feature=leads')
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertTrue(resp1.data['allowed'])

        # 2. Limit check
        resp2 = self.client.get('/api/v1/billing/entitlements/check/?limit=max_users')
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data['total_limit'], 5)

        # 3. Full summary
        resp3 = self.client.get('/api/v1/billing/entitlements/check/')
        self.assertEqual(resp3.status_code, status.HTTP_200_OK)
        self.assertTrue(resp3.data['has_active_subscription'])
        self.assertIn('leads', resp3.data['features'])

    def test_api_opportunity_won_provisioning_endpoint(self):
        """POST /api/v1/billing/integrations/crm/opportunity-won/ creates subscription."""
        self.client.force_authenticate(user=self.user1)

        payload = {
            "opportunity_id": 999,
            "company_id": 404,
            "company_name": "API Provisioned Co",
            "contact_email": "ops@apico.com",
            "plan_id": self.plan_pro.id,
            "add_ons": [
                {"addon_id": self.addon_users.id, "quantity": 1}
            ]
        }

        resp = self.client.post('/api/v1/billing/integrations/crm/opportunity-won/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['status'], 'LIVE')
        self.assertEqual(resp.data['opportunity_id'], 999)

        # Repeated POST -> 200 OK idempotent
        resp_repeat = self.client.post('/api/v1/billing/integrations/crm/opportunity-won/', payload, format='json')
        self.assertEqual(resp_repeat.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_repeat.data['idempotent'])

    def test_provision_won_opportunity_mismatched_billing_cycle_rejected(self):
        """Mismatched billing cycle is rejected with 400."""
        from rest_framework.exceptions import ValidationError as DRFValidationError
        payload = {
            "opportunity_id": 1111,
            "plan_id": self.plan_pro.id,
            "billing_cycle": "YEARLY",  # plan is monthly
        }
        with self.assertRaises(DRFValidationError):
            CrmOpportunityProvisioningService.provision_won_opportunity(
                organization=self.org1,
                payload=payload,
                actor=self.user1
            )

    def test_provision_won_opportunity_invalid_plan_rejected(self):
        """Non-existent plan_id is rejected."""
        from rest_framework.exceptions import ValidationError as DRFValidationError
        payload = {
            "opportunity_id": 1112,
            "plan_id": 99999,
        }
        with self.assertRaises(DRFValidationError):
            CrmOpportunityProvisioningService.provision_won_opportunity(
                organization=self.org1,
                payload=payload,
                actor=self.user1
            )

    def test_provision_won_opportunity_invalid_addon_rejected(self):
        """Non-existent addon_id is rejected."""
        from rest_framework.exceptions import ValidationError as DRFValidationError
        payload = {
            "opportunity_id": 1113,
            "plan_id": self.plan_pro.id,
            "add_ons": [{"addon_id": 99999, "quantity": 1}]
        }
        with self.assertRaises(DRFValidationError):
            CrmOpportunityProvisioningService.provision_won_opportunity(
                organization=self.org1,
                payload=payload,
                actor=self.user1
            )

    def test_api_entitlements_check_no_active_subscription(self):
        """Tenant with no active subscription gets 200 OK with allowed=False."""
        self.client.force_authenticate(user=self.user2)  # Org 2 has no subscriptions

        resp = self.client.get('/api/v1/billing/entitlements/check/?feature=leads')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['allowed'])

    def test_api_entitlements_check_unauthenticated_and_forbidden(self):
        """Unauthenticated requests are rejected with 401 or 403."""
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/v1/billing/entitlements/check/?feature=leads')
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_api_entitlements_check_method_not_allowed(self):
        """Mutating methods to /entitlements/check/ return 405 Method Not Allowed."""
        self.client.force_authenticate(user=self.user1)
        resp_post = self.client.post('/api/v1/billing/entitlements/check/', {})
        self.assertEqual(resp_post.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        resp_put = self.client.put('/api/v1/billing/entitlements/check/', {})
        self.assertEqual(resp_put.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        resp_delete = self.client.delete('/api/v1/billing/entitlements/check/')
        self.assertEqual(resp_delete.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_api_opportunity_won_unauthenticated_and_forbidden(self):
        """Unauthenticated requests cannot provision subscriptions (401 or 403)."""
        self.client.force_authenticate(user=None)
        payload = {
            "opportunity_id": 2222,
            "plan_id": self.plan_pro.id
        }
        resp = self.client.post('/api/v1/billing/integrations/crm/opportunity-won/', payload, format='json')
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_api_opportunity_won_response_schema_contract(self):
        """Verify the exact response schema expected by the frontend conversion handler."""
        self.client.force_authenticate(user=self.user1)
        payload = {
            "opportunity_id": 3333,
            "company_id": 555,
            "company_name": "Contract Test Co",
            "contact_email": "contract@test.com",
            "plan_id": self.plan_pro.id,
            "plan_quantity": 2,
            "start_date": "2026-09-14",
            "collection_method": "CHARGE_AUTOMATIC",
            "payment_terms_days": 0,
        }
        resp = self.client.post('/api/v1/billing/integrations/crm/opportunity-won/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.data
        self.assertIn('subscription_id', data)
        self.assertIn('subscription_number', data)
        self.assertIn('customer_id', data)
        self.assertIn('customer_number', data)
        self.assertIn('status', data)
        self.assertIn('opportunity_id', data)
        self.assertEqual(data['status'], 'LIVE')
        self.assertEqual(data['opportunity_id'], 3333)
        self.assertTrue(data['subscription_number'].startswith('SUB-'))
        self.assertTrue(data['customer_number'].startswith('CUST-'))

