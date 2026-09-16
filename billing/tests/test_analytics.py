from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organization
from catalog.models.product import Product
from catalog.models.plan import PricingPlan
from billing.models import (
    BillingCustomer,
    Subscription,
    SubscriptionItem,
    AddOn,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    CreditNote,
    DebitNote,
    SubscriptionAuditLog,
    SubscriptionChangeLog,
)
from billing.services import (
    BillingAnalyticsService,
    SubscriptionService,
    SubscriptionItemService,
)
from roles.models import Role, RolePermission, CRMResource

from billing.tests.helpers import setup_billing_test_permissions

User = get_user_model()


class BillingAnalyticsTestCase(APITestCase):
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
        self.limited_role, _ = Role.objects.get_or_create(
            name='Salesperson',
            defaults={'is_system': False, 'description': 'Salesperson'}
        )
        self.no_access_role, _ = Role.objects.get_or_create(
            name='NoAccessRole',
            defaults={'is_system': False, 'description': 'No Access'}
        )

        resources = setup_billing_test_permissions(admin_role=self.admin_role, manager_role=self.manager_role, sales_role=self.limited_role)
        for res in resources.values():
            RolePermission.objects.get_or_create(role=self.no_access_role, resource=res, action='VIEW', defaults={'scope': 'NONE'})

        # 3. Organizations
        self.org1 = Organization.objects.create(name="Analytics Corp 1", is_active=True)
        self.org2 = Organization.objects.create(name="Analytics Corp 2", is_active=True)

        # 4. Users
        self.user1 = User.objects.create_user(username='analytics_mgr_org1', email='mgr@org1.com', password='password123')
        self.user1.profile.organization = self.org1
        self.user1.profile.role = self.manager_role
        self.user1.profile.save()

        self.user1_sales = User.objects.create_user(username='analytics_sales_org1', email='sales@org1.com', password='password123')
        self.user1_sales.profile.organization = self.org1
        self.user1_sales.profile.role = self.limited_role
        self.user1_sales.profile.save()

        self.user_no_access = User.objects.create_user(username='no_access_user', email='noaccess@org1.com', password='password123')
        self.user_no_access.profile.organization = self.org1
        self.user_no_access.profile.role = self.no_access_role
        self.user_no_access.profile.save()

        self.user2 = User.objects.create_user(username='analytics_mgr_org2', email='mgr@org2.com', password='password123')
        self.user2.profile.organization = self.org2
        self.user2.profile.role = self.manager_role
        self.user2.profile.save()

        # 5. Catalog Products, Plans & AddOns
        self.product = Product.objects.create(name="AdaptCRM", slug="adaptcrm", is_active=True)
        self.plan_starter = PricingPlan.objects.create(
            product=self.product,
            name="Starter",
            price=Decimal('19.00'),
            currency="USD",
            billing_cycle="monthly",
            is_active=True
        )
        self.plan_pro_monthly = PricingPlan.objects.create(
            product=self.product,
            name="Professional Monthly",
            price=Decimal('100.00'),
            currency="USD",
            billing_cycle="monthly",
            is_active=True
        )
        self.plan_pro_yearly = PricingPlan.objects.create(
            product=self.product,
            name="Professional Yearly",
            price=Decimal('1200.00'),
            currency="USD",
            billing_cycle="yearly",
            is_active=True
        )

        self.addon_seats = AddOn.objects.create(
            product=self.product,
            name="Extra Seats",
            code="extra_seats",
            price=Decimal('15.00'),
            currency="USD",
            billing_cycle="monthly",
            unit_label="seat",
            is_active=True
        )

        # 6. Customers
        self.cust1 = BillingCustomer.objects.create(
            customer_number="CUST-00001",
            name="Customer One",
            email="c1@example.com",
            organization=self.org1,
            is_active=True,
            metadata={"created_by_id": self.user1.id}
        )
        self.cust2 = BillingCustomer.objects.create(
            customer_number="CUST-00002",
            name="Customer Two",
            email="c2@example.com",
            organization=self.org1,
            is_active=True,
            metadata={"created_by_id": self.user1_sales.id}
        )
        self.cust_org2 = BillingCustomer.objects.create(
            customer_number="CUST-00099",
            name="Org2 Customer",
            email="c99@example.com",
            organization=self.org2,
            is_active=True,
            metadata={"created_by_id": self.user2.id}
        )

        self.today = date.today()

    # --- Scenario A & B: Live MRR & ARR ---
    def test_calculate_live_mrr_and_arr_basic(self):
        """Scenario A & B: Basic Live MRR & ARR calculation."""
        # Sub 1: Monthly Pro ($100) + 3 Seats ($15 each) = $145.00 MRR, $1,740.00 ARR
        sub = Subscription.objects.create(
            subscription_number="SUB-00001",
            customer=self.cust1,
            status="LIVE",
            current_term_start=self.today - timedelta(days=10),
            current_term_end=self.today + timedelta(days=20),
            cached_mrr=Decimal('0.00'),
            cached_arr=Decimal('0.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('100.00'),
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=20)
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="ADDON",
            addon=self.addon_seats,
            quantity=3,
            unit_price=Decimal('15.00'),
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=20)
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

        mrr = BillingAnalyticsService.calculate_live_mrr(self.org1)
        arr = BillingAnalyticsService.calculate_live_arr(self.org1)

        self.assertEqual(mrr, Decimal('145.00'))
        self.assertEqual(arr, Decimal('1740.00'))
        self.assertIsInstance(mrr, Decimal)
        self.assertIsInstance(arr, Decimal)

    def test_yearly_plan_mrr_normalization(self):
        """Yearly plan ($1200/yr) contributes $100.00 to MRR and $1200.00 to ARR."""
        sub = Subscription.objects.create(
            subscription_number="SUB-00002",
            customer=self.cust1,
            status="LIVE",
            current_term_start=self.today - timedelta(days=10),
            current_term_end=self.today + timedelta(days=355),
            cached_mrr=Decimal('0.00'),
            cached_arr=Decimal('0.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_pro_yearly,
            quantity=1,
            unit_price=Decimal('1200.00'),
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=355)
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

        mrr = BillingAnalyticsService.calculate_live_mrr(self.org1)
        self.assertEqual(mrr, Decimal('100.00'))
        arr = BillingAnalyticsService.calculate_live_arr(self.org1)
        self.assertEqual(arr, Decimal('1200.00'))

    # --- Scenario C & D & E: Plan replacement, Addons, and Cancellation ---
    def test_plan_replacement_does_not_double_count_mrr(self):
        """Scenario C & M: Replaced expired plan items do not contribute to live MRR."""
        sub = Subscription.objects.create(
            subscription_number="SUB-00003",
            customer=self.cust1,
            status="LIVE",
            current_term_start=self.today - timedelta(days=15),
            current_term_end=self.today + timedelta(days=15),
            cached_mrr=Decimal('0.00'),
            cached_arr=Decimal('0.00'),
            metadata={"created_by_id": self.user1.id}
        )
        # Old replaced plan (ended 5 days ago)
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_starter,
            quantity=1,
            unit_price=Decimal('19.00'),
            start_date=self.today - timedelta(days=15),
            end_date=self.today - timedelta(days=5)
        )
        # New active plan (started 5 days ago)
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('100.00'),
            start_date=self.today - timedelta(days=5),
            end_date=self.today + timedelta(days=15)
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

        mrr = BillingAnalyticsService.calculate_live_mrr(self.org1)
        self.assertEqual(mrr, Decimal('100.00'))

    def test_item_date_boundaries_enforced(self):
        """Scenario F & G: Future items or past items outside active window do not count."""
        sub = Subscription.objects.create(
            subscription_number="SUB-00004",
            customer=self.cust1,
            status="LIVE",
            current_term_start=self.today - timedelta(days=5),
            current_term_end=self.today + timedelta(days=25),
            cached_mrr=Decimal('0.00'),
            cached_arr=Decimal('0.00'),
            metadata={"created_by_id": self.user1.id}
        )
        # Active Plan
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_starter,
            quantity=1,
            unit_price=Decimal('19.00'),
            start_date=self.today - timedelta(days=5),
            end_date=self.today + timedelta(days=25)
        )
        # Future Addon (starts in 10 days)
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="ADDON",
            addon=self.addon_seats,
            quantity=5,
            unit_price=Decimal('15.00'),
            start_date=self.today + timedelta(days=10),
            end_date=self.today + timedelta(days=25)
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

        mrr = BillingAnalyticsService.calculate_live_mrr(self.org1)
        self.assertEqual(mrr, Decimal('19.00'))

    def test_inactive_and_cancelled_subscriptions_excluded(self):
        """Scenario H & I: DRAFT, CANCELLED, UNPAID subscriptions do not contribute to live MRR."""
        # Cancelled Sub
        sub_cancelled = Subscription.objects.create(
            subscription_number="SUB-CAN-1",
            customer=self.cust1,
            status="CANCELLED",
            cancelled_at=timezone.now(),
            cached_mrr=Decimal('100.00'),
            cached_arr=Decimal('1200.00'),
            metadata={"created_by_id": self.user1.id}
        )
        # Draft Sub
        sub_draft = Subscription.objects.create(
            subscription_number="SUB-DFT-1",
            customer=self.cust1,
            status="DRAFT",
            cached_mrr=Decimal('50.00'),
            cached_arr=Decimal('600.00'),
            metadata={"created_by_id": self.user1.id}
        )
        # Unpaid Sub
        sub_unpaid = Subscription.objects.create(
            subscription_number="SUB-UNP-1",
            customer=self.cust1,
            status="UNPAID",
            cached_mrr=Decimal('75.00'),
            cached_arr=Decimal('900.00'),
            metadata={"created_by_id": self.user1.id}
        )

        mrr = BillingAnalyticsService.calculate_live_mrr(self.org1)
        self.assertEqual(mrr, Decimal('0.00'))
        self.assertEqual(BillingAnalyticsService.calculate_live_arr(self.org1), Decimal('0.00'))

    def test_paused_and_non_renewing_subscription_behavior(self):
        """Scenario J & K: Paused is 0 MRR; Non-renewing contributes MRR until term end."""
        # Paused sub
        sub_paused = Subscription.objects.create(
            subscription_number="SUB-PAUSE-1",
            customer=self.cust1,
            status="PAUSED",
            pause_date=self.today,
            cached_mrr=Decimal('100.00'),
            cached_arr=Decimal('1200.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub_paused,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('100.00')
        )
        # Non-renewing sub (active until term end)
        sub_nr = Subscription.objects.create(
            subscription_number="SUB-NR-1",
            customer=self.cust2,
            status="NON_RENEWING",
            current_term_start=self.today - timedelta(days=10),
            current_term_end=self.today + timedelta(days=20),
            cancel_at_period_end=True,
            cached_mrr=Decimal('19.00'),
            cached_arr=Decimal('228.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub_nr,
            item_type="PLAN",
            plan=self.plan_starter,
            quantity=1,
            unit_price=Decimal('19.00'),
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=20)
        )

        mrr = BillingAnalyticsService.calculate_live_mrr(self.org1)
        # Only NON_RENEWING contributes ($19.00), PAUSED contributes 0
        self.assertEqual(mrr, Decimal('19.00'))

    def test_historical_snapshot_pricing_stability(self):
        """Scenario L: Historical item price is preserved even if catalog changes."""
        sub = Subscription.objects.create(
            subscription_number="SUB-HIST-1",
            customer=self.cust1,
            status="LIVE",
            current_term_start=self.today - timedelta(days=5),
            current_term_end=self.today + timedelta(days=25),
            metadata={"created_by_id": self.user1.id}
        )
        # Locked historical grandfathered price $80 (while catalog plan is $100)
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('80.00'),
            start_date=self.today - timedelta(days=5),
            end_date=self.today + timedelta(days=25)
        )
        SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

        mrr = BillingAnalyticsService.calculate_live_mrr(self.org1)
        self.assertEqual(mrr, Decimal('80.00'))

    # --- Scenario O & P: Active Subscribers & Breakdown ---
    def test_active_subscribers_and_breakdown(self):
        """Scenario O & P: Accurate subscriber count and distributions by plan, status, and cycle."""
        # Sub 1: Live Pro Monthly ($100)
        sub1 = Subscription.objects.create(
            subscription_number="SUB-001",
            customer=self.cust1,
            status="LIVE",
            current_term_start=self.today - timedelta(days=5),
            current_term_end=self.today + timedelta(days=25),
            cached_mrr=Decimal('100.00'),
            cached_arr=Decimal('1200.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub1,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('100.00')
        )

        # Sub 2: Live Starter Monthly ($19) for Cust 2
        sub2 = Subscription.objects.create(
            subscription_number="SUB-002",
            customer=self.cust2,
            status="LIVE",
            current_term_start=self.today - timedelta(days=5),
            current_term_end=self.today + timedelta(days=25),
            cached_mrr=Decimal('19.00'),
            cached_arr=Decimal('228.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub2,
            item_type="PLAN",
            plan=self.plan_starter,
            quantity=1,
            unit_price=Decimal('19.00')
        )

        # Sub 3: Paused for Cust 1
        sub3 = Subscription.objects.create(
            subscription_number="SUB-003",
            customer=self.cust1,
            status="PAUSED",
            metadata={"created_by_id": self.user1.id}
        )

        overview = BillingAnalyticsService.get_analytics_overview(self.org1)
        self.assertEqual(overview['live_mrr'], '119.00')
        self.assertEqual(overview['live_arr'], '1428.00')
        self.assertEqual(overview['active_subscribers'], 2)
        self.assertEqual(overview['arpu'], '59.50')  # 119.00 / 2

        breakdown = overview['subscriber_breakdown']
        self.assertEqual(breakdown['by_status']['LIVE'], 2)
        self.assertEqual(breakdown['by_status']['PAUSED'], 1)
        self.assertEqual(breakdown['by_plan']['Starter'], 1)
        self.assertEqual(breakdown['by_plan']['Professional Monthly'], 1)
        self.assertEqual(breakdown['by_billing_cycle']['monthly'], 2)

    # --- Scenario Q, R, S: Churn & LTV ---
    def test_churn_and_ltv_calculation(self):
        """Scenario Q, R, S: Churn rate and LTV calculation with edge case safety."""
        # Live sub
        sub_live = Subscription.objects.create(
            subscription_number="SUB-LIVE-1",
            customer=self.cust1,
            status="LIVE",
            cached_mrr=Decimal('100.00'),
            cached_arr=Decimal('1200.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub_live,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('100.00')
        )
        # Cancelled sub in the last 10 days
        sub_canc = Subscription.objects.create(
            subscription_number="SUB-CANC-1",
            customer=self.cust2,
            status="CANCELLED",
            cancelled_at=timezone.now() - timedelta(days=10),
            cached_mrr=Decimal('100.00'),
            cached_arr=Decimal('1200.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionAuditLog.objects.create(
            subscription=sub_canc,
            action="STATE_TRANSITION",
            old_state="LIVE",
            new_state="CANCELLED",
            reason="Customer request",
            actor_id="1",
            actor_type="USER"
        )

        churn_data = BillingAnalyticsService.calculate_churn_metrics(self.org1, period_days=30)
        # 1 active now + 1 cancelled in period = 2 total subscribers at risk. 1 cancelled = 50% churn rate
        self.assertEqual(churn_data['cancelled_count'], 1)
        self.assertEqual(churn_data['subscriber_churn_rate_pct'], Decimal('50.00'))

        ltv_data = BillingAnalyticsService.calculate_ltv(self.org1, period_days=30)
        # ARPU = 100.00 / 1 = 100.00. Churn = 0.50 -> LTV = 100.00 / 0.50 = 200.00
        self.assertEqual(ltv_data['arpu'], Decimal('100.00'))
        self.assertEqual(ltv_data['ltv'], Decimal('200.00'))

    def test_zero_churn_edge_case(self):
        """Scenario S: Zero churn rate handles division by zero safely."""
        sub = Subscription.objects.create(
            subscription_number="SUB-LIVE-10",
            customer=self.cust1,
            status="LIVE",
            cached_mrr=Decimal('50.00'),
            cached_arr=Decimal('600.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_starter,
            quantity=1,
            unit_price=Decimal('50.00')
        )
        churn_data = BillingAnalyticsService.calculate_churn_metrics(self.org1, period_days=30)
        self.assertEqual(churn_data['subscriber_churn_rate_pct'], Decimal('0.00'))

        ltv_data = BillingAnalyticsService.calculate_ltv(self.org1, period_days=30)
        self.assertEqual(ltv_data['arpu'], Decimal('50.00'))
        self.assertIsNotNone(ltv_data['ltv'])  # Safe realized/baseline LTV

    # --- Scenario T through Y: MRR Movement ---
    def test_mrr_movement_monthly_buckets(self):
        """Scenario T through Y: Detailed MRR movement with expansion, contraction, churn, new MRR."""
        # Create a subscription with change logs
        sub = Subscription.objects.create(
            subscription_number="SUB-MOV-1",
            customer=self.cust1,
            status="LIVE",
            cached_mrr=Decimal('150.00'),
            cached_arr=Decimal('1800.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('150.00')
        )
        # Log New MRR
        SubscriptionAuditLog.objects.create(
            subscription=sub,
            action="SUBSCRIPTION_CREATED",
            new_state="LIVE",
            actor_id="1",
            actor_type="USER",
            metadata={"mrr": "100.00"}
        )
        # Log Expansion
        SubscriptionChangeLog.objects.create(
            subscription=sub,
            change_type="UPGRADE",
            proration_amount=Decimal('50.00'),
            effective_date=self.today,
            details={"mrr_delta": "50.00", "new_mrr": "150.00"}
        )

        movement = BillingAnalyticsService.get_mrr_movement(self.org1, months=3)
        self.assertIsInstance(movement, list)
        self.assertEqual(len(movement), 3)
        current_month_bucket = movement[-1]
        self.assertIn('period', current_month_bucket)
        self.assertIn('new_mrr', current_month_bucket)
        self.assertIn('expansion_mrr', current_month_bucket)
        self.assertIn('contraction_mrr', current_month_bucket)
        self.assertIn('churned_mrr', current_month_bucket)
        self.assertIn('net_mrr_growth', current_month_bucket)
        self.assertIn('ending_mrr', current_month_bucket)

    # --- Scenario Z & AC: Tenant Isolation ---
    def test_tenant_isolation_strict(self):
        """Scenario Z & AC: Org 1 cannot see Org 2 analytics data."""
        # Org 1 Sub ($100)
        sub1 = Subscription.objects.create(
            subscription_number="SUB-ORG1",
            customer=self.cust1,
            status="LIVE",
            cached_mrr=Decimal('100.00'),
            cached_arr=Decimal('1200.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub1,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('100.00')
        )
        # Org 2 Sub ($500)
        sub2 = Subscription.objects.create(
            subscription_number="SUB-ORG2",
            customer=self.cust_org2,
            status="LIVE",
            cached_mrr=Decimal('500.00'),
            cached_arr=Decimal('6000.00'),
            metadata={"created_by_id": self.user2.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub2,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=5,
            unit_price=Decimal('100.00')
        )

        mrr_org1 = BillingAnalyticsService.calculate_live_mrr(self.org1)
        mrr_org2 = BillingAnalyticsService.calculate_live_mrr(self.org2)

        self.assertEqual(mrr_org1, Decimal('100.00'))
        self.assertEqual(mrr_org2, Decimal('500.00'))

    # --- Scenario AA & AB: API Endpoints, RBAC Scoping, and Read-Only Enforcement ---
    def test_api_analytics_overview_authenticated_manager(self):
        """Scenario AA & AB: Manager receives 200 OK with full organization overview."""
        sub = Subscription.objects.create(
            subscription_number="SUB-API-1",
            customer=self.cust1,
            status="LIVE",
            cached_mrr=Decimal('19.00'),
            cached_arr=Decimal('228.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_starter,
            quantity=1,
            unit_price=Decimal('19.00')
        )

        self.client.force_authenticate(user=self.user1)
        resp = self.client.get('/api/v1/billing/analytics/overview/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['live_mrr'], '19.00')
        self.assertEqual(resp.data['live_arr'], '228.00')
        self.assertEqual(resp.data['active_subscribers'], 1)

    def test_api_analytics_mrr_movement_authenticated(self):
        """API returns deterministic ordered MRR movement list."""
        self.client.force_authenticate(user=self.user1)
        resp = self.client.get('/api/v1/billing/analytics/mrr-movement/?months=6')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsInstance(resp.data['results'], list)
        self.assertEqual(len(resp.data['results']), 6)

    def test_api_analytics_rbac_own_scope(self):
        """Salesperson with OWN scope only sees analytics for their created customers."""
        # Sub 1 created by user1 (Manager) ($100)
        sub1 = Subscription.objects.create(
            subscription_number="SUB-USER1",
            customer=self.cust1,
            status="LIVE",
            cached_mrr=Decimal('100.00'),
            cached_arr=Decimal('1200.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub1,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('100.00')
        )
        # Sub 2 created by user1_sales (Salesperson) ($19)
        sub2 = Subscription.objects.create(
            subscription_number="SUB-SALES",
            customer=self.cust2,
            status="LIVE",
            cached_mrr=Decimal('19.00'),
            cached_arr=Decimal('228.00'),
            metadata={"created_by_id": self.user1_sales.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub2,
            item_type="PLAN",
            plan=self.plan_starter,
            quantity=1,
            unit_price=Decimal('19.00')
        )

        self.client.force_authenticate(user=self.user1_sales)
        resp = self.client.get('/api/v1/billing/analytics/overview/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Salesperson only sees their own $19.00 MRR
        self.assertEqual(resp.data['live_mrr'], '19.00')
        self.assertEqual(resp.data['active_subscribers'], 1)

    def test_api_analytics_unauthenticated_and_no_access(self):
        """Unauthenticated or NONE scope returns 401 / 403."""
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/v1/billing/analytics/overview/')
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        self.client.force_authenticate(user=self.user_no_access)
        resp2 = self.client.get('/api/v1/billing/analytics/overview/')
        self.assertEqual(resp2.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_analytics_mutations_rejected_405(self):
        """Scenario AB: POST, PUT, DELETE to analytics endpoints return 405 Method Not Allowed."""
        self.client.force_authenticate(user=self.user1)
        self.assertEqual(self.client.post('/api/v1/billing/analytics/overview/', {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.put('/api/v1/billing/analytics/overview/', {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.delete('/api/v1/billing/analytics/overview/').status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.post('/api/v1/billing/analytics/mrr-movement/', {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_invoice_and_payment_financial_consistency(self):
        """Scenario AF: Cash payments and invoices are not confused with live subscription MRR."""
        # Customer has paid invoice of $500, but subscription has $100 MRR
        sub = Subscription.objects.create(
            subscription_number="SUB-FIN-1",
            customer=self.cust1,
            status="LIVE",
            cached_mrr=Decimal('100.00'),
            cached_arr=Decimal('1200.00'),
            metadata={"created_by_id": self.user1.id}
        )
        SubscriptionItem.objects.create(
            subscription=sub,
            item_type="PLAN",
            plan=self.plan_pro_monthly,
            quantity=1,
            unit_price=Decimal('100.00')
        )
        inv = Invoice.objects.create(
            invoice_number="INV-2026-00001",
            customer=self.cust1,
            subscription=sub,
            issue_date=self.today,
            due_date=self.today,
            total_amount=Decimal('500.00'),
            paid_amount=Decimal('500.00'),
            balance=Decimal('0.00'),
            status="PAID"
        )
        pay = Payment.objects.create(
            payment_number="PAY-00001",
            customer=self.cust1,
            payment_date=self.today,
            amount=Decimal('500.00'),
            status="SUCCEEDED"
        )
        PaymentAllocation.objects.create(
            payment=pay,
            invoice=inv,
            amount=Decimal('500.00')
        )

        overview = BillingAnalyticsService.get_analytics_overview(self.org1)
        self.assertEqual(overview['live_mrr'], '100.00')
        self.assertEqual(overview['live_arr'], '1200.00')
        self.assertEqual(overview['total_collected_revenue'], '500.00')

