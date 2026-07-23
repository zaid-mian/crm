from django.test import TestCase
from django.contrib.auth import get_user_model
from companies.models import Company
from companies.services.query import CompanyQueryService

User = get_user_model()

class CompanyQueryServiceTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pwd')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'pwd', is_staff=True)
        self.sales_a = User.objects.create_user('sales_a', 'sales_a@example.com', 'pwd')
        self.sales_b = User.objects.create_user('sales_b', 'sales_b@example.com', 'pwd')

        self.company_a = Company.objects.create(
            name="Company A",
            assigned_salesperson=self.sales_a
        )
        self.company_b = Company.objects.create(
            name="Company B",
            assigned_salesperson=self.sales_b
        )
        self.company_unassigned = Company.objects.create(
            name="Company Unassigned"
        )

    def test_visible_companies_for_admin_and_manager(self):
        """Admin and manager can see all company records."""
        admin_companies = CompanyQueryService.get_visible_companies(self.admin)
        self.assertEqual(admin_companies.count(), 3)

        manager_companies = CompanyQueryService.get_visible_companies(self.manager)
        self.assertEqual(manager_companies.count(), 3)

    def test_visible_companies_for_salesperson(self):
        """Salesperson can see only their assigned company records."""
        sales_a_companies = CompanyQueryService.get_visible_companies(self.sales_a)
        self.assertEqual(sales_a_companies.count(), 1)
        self.assertEqual(sales_a_companies.first(), self.company_a)

        sales_b_companies = CompanyQueryService.get_visible_companies(self.sales_b)
        self.assertEqual(sales_b_companies.count(), 1)
        self.assertEqual(sales_b_companies.first(), self.company_b)
