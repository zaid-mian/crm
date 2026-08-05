from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.core.exceptions import ValidationError
from catalog.models import Product, Module, PricingPlan, PlanModule, Service, ServiceFeature, Discount

class CatalogModelIntegrityTest(TestCase):
    def setUp(self):
        # Create base product and service
        self.product = Product.objects.create(
            name="Sales CRM",
            slug="sales-crm",
            description="CRM SaaS module"
        )
        self.service = Service.objects.create(
            name="Professional Setup",
            slug="professional-setup",
            short_description="Setup consult"
        )
        
        # Modules
        self.module_leads = Module.objects.create(
            product=self.product,
            name="Lead Management",
            code="lead_mgmt"
        )
        self.module_reports = Module.objects.create(
            product=self.product,
            name="Reports",
            code="reports"
        )

        # Base Pricing Plans
        self.plan_product = PricingPlan.objects.create(
            product=self.product,
            name="Starter Plan",
            price=20.00,
            billing_cycle="monthly"
        )
        self.plan_service = PricingPlan.objects.create(
            service=self.service,
            name="Consulting Plan",
            price=150.00,
            billing_cycle="one_time"
        )

    def test_plan_exclusivity(self):
        """A pricing plan must be linked to either a Product or a Service, not both or neither."""
        # Neither Product nor Service
        invalid_plan = PricingPlan(name="Orphan Plan", price=10.00, billing_cycle="monthly")
        with self.assertRaises(ValidationError):
            invalid_plan.full_clean()

        # Both Product and Service
        invalid_plan2 = PricingPlan(
            product=self.product,
            service=self.service,
            name="Double Link Plan",
            price=10.00,
            billing_cycle="monthly"
        )
        with self.assertRaises(ValidationError):
            invalid_plan2.full_clean()

    def test_pricing_plan_name_uniqueness(self):
        """Pricing plan name must be unique within product/service scope."""
        # Duplicate name under same Product
        duplicate_plan = PricingPlan(
            product=self.product,
            name="Starter Plan",
            price=30.00,
            billing_cycle="monthly"
        )
        with self.assertRaises(ValidationError):
            duplicate_plan.full_clean()

        # Same name but under Service (allowed)
        allowed_plan = PricingPlan(
            service=self.service,
            name="Starter Plan",
            price=30.00,
            billing_cycle="monthly"
        )
        # Should not raise validation error
        allowed_plan.full_clean()
        allowed_plan.save()

    def test_plan_module_cross_product_validation(self):
        """A plan module can only link a pricing plan and a module belonging to the same product."""
        # Second product
        product2 = Product.objects.create(name="HRM", slug="hrm")
        module_hrm = Module.objects.create(product=product2, name="Leave Tracker", code="leaves")

        # Starter Plan belongs to Sales CRM. Linking to HRM Module should fail.
        invalid_link = PlanModule(plan=self.plan_product, module=module_hrm)
        with self.assertRaises(ValidationError):
            invalid_link.full_clean()

    def test_discount_bounds_percentage(self):
        """Percentage discounts must be between 0 and 100."""
        invalid_discount = Discount(
            pricing_plan=self.plan_product,
            name="Invalid %",
            discount_type="percentage",
            value=120.00,
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount.full_clean()

        invalid_discount2 = Discount(
            pricing_plan=self.plan_product,
            name="Negative %",
            discount_type="percentage",
            value=-10.00,
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount2.full_clean()

    def test_discount_bounds_fixed(self):
        """Fixed discounts must be greater than 0 and not exceed plan price."""
        # Value > plan price
        invalid_discount = Discount(
            pricing_plan=self.plan_product,
            name="Over plan price",
            discount_type="fixed",
            value=30.00,  # plan price is 20.00
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount.full_clean()

        # Value <= 0
        invalid_discount2 = Discount(
            pricing_plan=self.plan_product,
            name="Negative Fixed",
            discount_type="fixed",
            value=-5.00,
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount2.full_clean()

    def test_discount_date_chronology(self):
        """Discount start date must be before end date."""
        now = timezone.now()
        invalid_discount = Discount(
            pricing_plan=self.plan_product,
            name="Time traveler",
            discount_type="percentage",
            value=10.00,
            start_date=now + timedelta(days=2),
            end_date=now,
            is_active=True
        )
        with self.assertRaises(ValidationError):
            invalid_discount.full_clean()

    def test_discount_overlap_constraint(self):
        """Only one active discount can overlap in a pricing plan."""
        now = timezone.now()
        # Active discount 1 (Starts now, ends in 5 days)
        Discount.objects.create(
            pricing_plan=self.plan_product,
            name="Summer Sale",
            discount_type="percentage",
            value=10.00,
            start_date=now,
            end_date=now + timedelta(days=5),
            is_active=True
        )

        # Overlapping active discount 2 (Starts in 2 days, ends in 7 days)
        overlapping_discount = Discount(
            pricing_plan=self.plan_product,
            name="Flash Sale",
            discount_type="percentage",
            value=15.00,
            start_date=now + timedelta(days=2),
            end_date=now + timedelta(days=7),
            is_active=True
        )
        with self.assertRaises(ValidationError):
            overlapping_discount.full_clean()

        # Non-overlapping active discount 3 (Starts in 6 days, ends in 10 days)
        valid_discount = Discount(
            pricing_plan=self.plan_product,
            name="Autumn Sale",
            discount_type="percentage",
            value=20.00,
            start_date=now + timedelta(days=6),
            end_date=now + timedelta(days=10),
            is_active=True
        )
        # Should clean successfully
        valid_discount.full_clean()
        valid_discount.save()


from django.urls import reverse

class CatalogAPITestCase(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Sales CRM",
            slug="sales-crm",
            description="Active CRM SaaS module",
            is_active=True
        )
        self.module = Module.objects.create(
            product=self.product,
            name="Lead Tracking",
            code="lead_tracking"
        )
        self.plan = PricingPlan.objects.create(
            product=self.product,
            name="Pro",
            price=29.99,
            billing_cycle="monthly",
            is_active=True
        )
        self.service = Service.objects.create(
            name="Implementation Setup",
            slug="implementation-setup",
            short_description="Full onboarding consulting",
            is_active=True
        )

    def test_product_list_api(self):
        url = reverse('catalog:api_product_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']), 1)
        self.assertEqual(data['data'][0]['name'], "Sales CRM")

    def test_product_detail_api(self):
        url = reverse('catalog:api_product_detail', kwargs={'slug': 'sales-crm'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['name'], "Sales CRM")
        self.assertEqual(len(data['data']['modules']), 1)
        self.assertEqual(len(data['data']['pricing_plans']), 1)

    def test_service_list_api(self):
        url = reverse('catalog:api_service_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']), 1)
        self.assertEqual(data['data'][0]['name'], "Implementation Setup")

    def test_service_detail_api(self):
        url = reverse('catalog:api_service_detail', kwargs={'slug': 'implementation-setup'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['name'], "Implementation Setup")


from django.contrib.auth import get_user_model
from catalog.models import Feedback

User = get_user_model()

class CustomerFeedbackTest(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username="cust@test.com", email="cust@test.com", password="password")
        self.product = Product.objects.create(name="Feedback Product", slug="feedback-product")
        self.service = Service.objects.create(name="Feedback Service", slug="feedback-service")

    def test_feedback_rating_boundaries(self):
        # Good rating
        f = Feedback(user=self.customer, product=self.product, rating=5, comment="Great")
        f.full_clean()  # Should pass
        
        # Rating too low
        f_low = Feedback(user=self.customer, product=self.product, rating=0, comment="Bad")
        with self.assertRaises(ValidationError):
            f_low.full_clean()

        # Rating too high
        f_high = Feedback(user=self.customer, product=self.product, rating=6, comment="Superb")
        with self.assertRaises(ValidationError):
            f_high.full_clean()

    def test_feedback_exclusivity(self):
        # Target both (should fail)
        f_both = Feedback(user=self.customer, product=self.product, service=self.service, rating=4, comment="Both")
        with self.assertRaises(ValidationError):
            f_both.full_clean()

        # Target neither (should fail)
        f_none = Feedback(user=self.customer, rating=4, comment="None")
        with self.assertRaises(ValidationError):
            f_none.full_clean()

    def test_feedback_uniqueness_constraints(self):
        Feedback.objects.create(user=self.customer, product=self.product, rating=4, comment="First")
        
        # Duplicate review for same product/user should fail unique constraint
        f_dup = Feedback(user=self.customer, product=self.product, rating=5, comment="Second")
        with self.assertRaises(ValidationError):
            f_dup.full_clean()


class CatalogFeedbackAPITest(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username="cust@test.com", email="cust@test.com", password="password")
        self.other_customer = User.objects.create_user(username="other@test.com", email="other@test.com", password="password")
        self.admin = User.objects.create_superuser(username="admin@test.com", email="admin@test.com", password="password")
        
        self.product = Product.objects.create(name="Feedback Product", slug="feedback-product", is_active=True)
        self.service = Service.objects.create(name="Feedback Service", slug="feedback-service", is_active=True)

    def test_feedback_api_upsert_flow(self):
        self.client.login(username="cust@test.com", password="password")
        url = reverse('catalog:api_product_feedback', kwargs={'slug': self.product.slug})
        
        # 1. Post a new review
        response = self.client.post(url, {"rating": 4, "comment": "Nice"}, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Feedback.objects.count(), 1)
        self.assertEqual(Feedback.objects.first().rating, 4)

        # 2. Post again as same user (should edit/update)
        response_edit = self.client.post(url, {"rating": 5, "comment": "Excellent"}, content_type='application/json')
        self.assertEqual(response_edit.status_code, 200)
        self.assertEqual(Feedback.objects.count(), 1)
        self.assertEqual(Feedback.objects.first().rating, 5)
        self.assertEqual(Feedback.objects.first().comment, "Excellent")

    def test_product_service_detail_api_feedback_keys(self):
        # Create reviews
        Feedback.objects.create(user=self.customer, product=self.product, rating=5, comment="Amazing")
        Feedback.objects.create(user=self.other_customer, product=self.product, rating=3, comment="Okay")

        url = reverse('catalog:api_product_detail', kwargs={'slug': self.product.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()['data']
        self.assertEqual(data['review_count'], 2)
        self.assertEqual(data['average_rating'], 4.0)
        self.assertEqual(len(data['reviews']), 2)
        self.assertEqual(data['reviews'][0]['rating'], 3) # descending order

    def test_global_feedback_access(self):
        # 1. Unauthenticated/Non-staff accesses global reviews queue (should fail)
        url = reverse('catalog:api_global_feedback')
        response_unauth = self.client.get(url)
        self.assertEqual(response_unauth.status_code, 403)

        self.client.login(username="cust@test.com", password="password")
        response_cust = self.client.get(url)
        self.assertEqual(response_cust.status_code, 403)
        self.client.logout()

        # 2. Staff user gets reviews list (should succeed)
        Feedback.objects.create(user=self.customer, product=self.product, rating=5, comment="Amazing")
        self.client.login(username="admin@test.com", password="password")
        response_admin = self.client.get(url)
        self.assertEqual(response_admin.status_code, 200)
        self.assertEqual(len(response_admin.json()['data']), 1)
        self.assertEqual(response_admin.json()['data'][0]['target_name'], "Feedback Product")


