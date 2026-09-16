from datetime import date
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from accounts.models import Organization
from billing.models import BillingCustomer, Subscription, SubscriptionAuditLog
from billing.services import SubscriptionStateMachineService
from roles.models import Role, RolePermission, CRMResource

User = get_user_model()


from billing.tests.helpers import setup_billing_test_permissions


class SubscriptionStateMachineTestCase(APITestCase):
    def setUp(self):
        # 1. Setup Roles and permissions
        self.admin_role, _ = Role.objects.get_or_create(
            name='Administrator',
            defaults={'is_system': True, 'description': 'Admin'}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name='Salesperson',
            defaults={'is_system': True, 'description': 'Salesperson'}
        )

        setup_billing_test_permissions(admin_role=self.admin_role, sales_role=self.sales_role)

        # 3. Create Organizations
        self.org1 = Organization.objects.create(name="Acme Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Beta Org 2", is_active=True)

        # 4. Create Users for Org 1
        self.admin_user = User.objects.create_user(username='sm_admin', email='admin@org1.com', password='password123')
        self.admin_user.profile.organization = self.org1
        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.save()

        self.sales1 = User.objects.create_user(username='sm_sales1', email='sales1@org1.com', password='password123')
        self.sales1.profile.organization = self.org1
        self.sales1.profile.role = self.sales_role
        self.sales1.profile.save()

        self.sales2 = User.objects.create_user(username='sm_sales2', email='sales2@org1.com', password='password123')
        self.sales2.profile.organization = self.org1
        self.sales2.profile.role = self.sales_role
        self.sales2.profile.save()

        # Users for Org 2
        self.org2_user = User.objects.create_user(username='sm_org2_user', email='user@org2.com', password='password123')
        self.org2_user.profile.organization = self.org2
        self.org2_user.profile.role = self.admin_role
        self.org2_user.profile.save()

        # 5. Create Customers
        self.customer1 = BillingCustomer.objects.create(
            organization=self.org1,
            customer_number='CUST-00001',
            name='Acme Corp',
            email='billing@acme.com',
            currency='USD',
            metadata={'created_by_id': self.sales1.id}
        )

        self.customer2 = BillingCustomer.objects.create(
            organization=self.org2,
            customer_number='CUST-00002',
            name='Beta Corp',
            email='billing@beta.com',
            currency='USD',
            metadata={'created_by_id': self.org2_user.id}
        )

        # 6. Create Subscriptions
        self.sub_draft = Subscription.objects.create(
            subscription_number='SUB-00001',
            customer=self.customer1,
            status='DRAFT',
            currency='USD',
            current_term_start=date.today(),
            current_term_end=date.today(),
            metadata={'created_by_id': self.sales1.id}
        )

        self.sub_live = Subscription.objects.create(
            subscription_number='SUB-00002',
            customer=self.customer1,
            status='LIVE',
            currency='USD',
            current_term_start=date.today(),
            current_term_end=date.today(),
            metadata={'created_by_id': self.sales1.id}
        )

        self.sub_cancelled = Subscription.objects.create(
            subscription_number='SUB-00003',
            customer=self.customer1,
            status='CANCELLED',
            currency='USD',
            current_term_start=date.today(),
            current_term_end=date.today(),
            metadata={'created_by_id': self.sales1.id}
        )

        self.sub_org2 = Subscription.objects.create(
            subscription_number='SUB-00004',
            customer=self.customer2,
            status='LIVE',
            currency='USD',
            current_term_start=date.today(),
            current_term_end=date.today(),
            metadata={'created_by_id': self.org2_user.id}
        )

    # ----------------------------------------------------
    # Service Layer Unit Tests
    # ----------------------------------------------------
    def test_valid_state_transitions(self):
        """Test valid lifecycle transitions and metadata/audit updates."""
        # DRAFT -> LIVE
        sub = SubscriptionStateMachineService.transition(
            subscription=self.sub_draft,
            to_status='LIVE',
            user=self.admin_user
        )
        self.assertEqual(sub.status, 'LIVE')
        logs = SubscriptionAuditLog.objects.filter(subscription=sub)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().old_state, 'DRAFT')
        self.assertEqual(logs.first().new_state, 'LIVE')
        self.assertEqual(logs.first().actor_id, str(self.admin_user.id))
        self.assertEqual(logs.first().actor_type, 'USER')

        # LIVE -> PAUSED (requires reason)
        sub = SubscriptionStateMachineService.transition(
            subscription=self.sub_live,
            to_status='PAUSED',
            user=self.admin_user,
            reason='Customer requested temporary pause'
        )
        self.assertEqual(sub.status, 'PAUSED')
        self.assertEqual(sub.pause_date, date.today())
        self.assertEqual(SubscriptionAuditLog.objects.filter(subscription=sub).count(), 1)

        # PAUSED -> LIVE
        sub = SubscriptionStateMachineService.transition(
            subscription=sub,
            to_status='LIVE',
            user=self.admin_user
        )
        self.assertEqual(sub.status, 'LIVE')
        self.assertEqual(sub.resume_date, date.today())
        self.assertEqual(SubscriptionAuditLog.objects.filter(subscription=sub).count(), 2)

        # LIVE -> NON_RENEWING
        sub = SubscriptionStateMachineService.transition(
            subscription=sub,
            to_status='NON_RENEWING',
            user=self.admin_user
        )
        self.assertEqual(sub.status, 'NON_RENEWING')
        self.assertTrue(sub.cancel_at_period_end)

        # NON_RENEWING -> LIVE
        sub = SubscriptionStateMachineService.transition(
            subscription=sub,
            to_status='LIVE',
            user=self.admin_user
        )
        self.assertEqual(sub.status, 'LIVE')
        self.assertFalse(sub.cancel_at_period_end)

        # LIVE -> CANCELLED (requires reason)
        sub = SubscriptionStateMachineService.transition(
            subscription=sub,
            to_status='CANCELLED',
            user=self.admin_user,
            reason='Customer cancelled contract'
        )
        self.assertEqual(sub.status, 'CANCELLED')
        self.assertIsNotNone(sub.cancelled_at)

    def test_same_status_rejection_no_audit(self):
        """Reject same-status transitions with ValidationError and create ZERO audit logs."""
        initial_logs_count = SubscriptionAuditLog.objects.filter(subscription=self.sub_live).count()

        with self.assertRaises(ValidationError) as ctx:
            SubscriptionStateMachineService.transition(
                subscription=self.sub_live,
                to_status='LIVE',
                user=self.admin_user
            )

        self.assertIn('already in status', str(ctx.exception))
        final_logs_count = SubscriptionAuditLog.objects.filter(subscription=self.sub_live).count()
        self.assertEqual(initial_logs_count, final_logs_count)

    def test_invalid_prohibited_transition(self):
        """Prohibit invalid lifecycle jumps (e.g. DRAFT -> PAUSED)."""
        with self.assertRaises(ValidationError) as ctx:
            SubscriptionStateMachineService.transition(
                subscription=self.sub_draft,
                to_status='PAUSED',
                user=self.admin_user,
                reason='Invalid'
            )
        self.assertIn('prohibited', str(ctx.exception))

    def test_cancelled_is_terminal(self):
        """Verify CANCELLED state cannot transition to any other status."""
        with self.assertRaises(ValidationError) as ctx:
            SubscriptionStateMachineService.transition(
                subscription=self.sub_cancelled,
                to_status='LIVE',
                user=self.admin_user
            )
        self.assertIn('terminal state', str(ctx.exception))

    def test_reason_required_for_cancel_and_pause(self):
        """Verify reason is strictly required when transitioning to CANCELLED or PAUSED."""
        # Missing reason for CANCELLED
        with self.assertRaises(ValidationError) as ctx:
            SubscriptionStateMachineService.transition(
                subscription=self.sub_live,
                to_status='CANCELLED',
                user=self.admin_user,
                reason=''
            )
        self.assertIn('reason', ctx.exception.detail)

        # Missing reason for PAUSED
        with self.assertRaises(ValidationError) as ctx:
            SubscriptionStateMachineService.transition(
                subscription=self.sub_live,
                to_status='PAUSED',
                user=self.admin_user,
                reason='  '
            )
        self.assertIn('reason', ctx.exception.detail)

    def test_exactly_one_audit_record_per_successful_transition(self):
        """Verify exactly one audit log is created per valid transition."""
        self.assertEqual(SubscriptionAuditLog.objects.filter(subscription=self.sub_draft).count(), 0)
        SubscriptionStateMachineService.transition(
            subscription=self.sub_draft,
            to_status='LIVE',
            user=self.admin_user
        )
        self.assertEqual(SubscriptionAuditLog.objects.filter(subscription=self.sub_draft).count(), 1)

    # ----------------------------------------------------
    # API Endpoint Integration & Security Tests
    # ----------------------------------------------------
    def test_api_transition_success(self):
        """POST /api/v1/billing/subscriptions/<id>/transition/ executes transition."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-subscription-transition', kwargs={'pk': self.sub_live.id})

        response = self.client.post(url, {
            'to_status': 'PAUSED',
            'reason': 'Customer requested seasonal pause'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'PAUSED')

        self.sub_live.refresh_from_db()
        self.assertEqual(self.sub_live.status, 'PAUSED')

    def test_api_same_status_rejection_http_400(self):
        """POST same status returns HTTP 400 and creates no audit log."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-subscription-transition', kwargs={'pk': self.sub_live.id})

        response = self.client.post(url, {
            'to_status': 'LIVE'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(SubscriptionAuditLog.objects.filter(subscription=self.sub_live).count(), 0)

    def test_api_tenant_isolation(self):
        """User cannot transition subscription in another organization."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('billing-subscription-transition', kwargs={'pk': self.sub_org2.id})

        response = self.client.post(url, {
            'to_status': 'CANCELLED',
            'reason': 'Cross tenant attempt'
        }, format='json')

        self.assertIn(response.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))

    def test_api_rbac_ownership_scoping(self):
        """Salesperson with OWN scope cannot transition another user's subscription."""
        self.client.force_authenticate(user=self.sales2)
        url = reverse('billing-subscription-transition', kwargs={'pk': self.sub_live.id})

        response = self.client.post(url, {
            'to_status': 'CANCELLED',
            'reason': 'RBAC test'
        }, format='json')

        self.assertIn(response.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))
