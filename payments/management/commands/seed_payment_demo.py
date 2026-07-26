from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from companies.models import Company
from contacts.models import Contact
from leads.models import Lead
from opportunities.models import Opportunity, OpportunityStage
from payments.models import Payment
from payments.services.invoice import PaymentInvoiceService
from payments.services.payment_workflow import PaymentWorkflowService


class Command(BaseCommand):
    help = 'Create demo users, groups, and sample payment records.'

    def handle(self, *args, **options):
        User = get_user_model()

        finance_group, _ = Group.objects.get_or_create(name='Finance')
        manager_group, _ = Group.objects.get_or_create(name='Sales Manager')

        users = [
            ('admin', 'admin123', True, True, []),
            ('finance_user', 'finance123', False, True, [finance_group]),
            ('sales_manager', 'manager123', False, False, [manager_group]),
            ('salesperson_1', 'sales123', False, False, []),
        ]

        salesperson = None
        for username, password, is_super, is_staff, groups in users:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'is_superuser': is_super, 'is_staff': is_staff},
            )
            user.set_password(password)
            user.is_superuser = is_super
            user.is_staff = is_staff
            user.save()

            user.groups.clear()
            for group in groups:
                user.groups.add(group)

            if username == 'salesperson_1':
                salesperson = user

            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{action} user {username} / {password}'))

        finance_user = User.objects.get(username='finance_user')
        self._seed_demo_payments(finance_user, salesperson)

        self.stdout.write(
            self.style.NOTICE(
                'Open http://127.0.0.1:8000/payments/ to use the payment board.'
            )
        )

    def _seed_demo_payments(self, finance_user, salesperson):
        lead, _ = Lead.objects.get_or_create(
            full_name='Demo Lead',
            phone='+10000000001',
            defaults={'email': 'demo@test.com'},
        )
        abc, _ = Company.objects.get_or_create(name='ABC Ltd', defaults={'website': 'https://abc.com'})
        xyz, _ = Company.objects.get_or_create(name='XYZ Ltd', defaults={'website': 'https://xyz.com'})
        contact_a, _ = Contact.objects.get_or_create(
            full_name='John Smith',
            phone_number='+10000000002',
            company=abc,
            defaults={'email': 'john@test.com'},
        )
        contact_x, _ = Contact.objects.get_or_create(
            full_name='Jane Doe',
            phone_number='+10000000003',
            company=xyz,
            defaults={'email': 'jane@test.com'},
        )

        opp1, _ = Opportunity.objects.get_or_create(
            name='CRM Project',
            company=abc,
            source_lead=lead,
            primary_contact=contact_a,
            defaults={
                'stage': OpportunityStage.CLOSED_WON,
                'amount': Decimal('15000'),
                'expected_close_date': date.today(),
                'assigned_salesperson': salesperson,
            },
        )
        opp1.stage = OpportunityStage.CLOSED_WON
        opp1.amount = Decimal('15000')
        if salesperson:
            opp1.assigned_salesperson = salesperson
        opp1.save()

        opp2, _ = Opportunity.objects.get_or_create(
            name='ERP Deal',
            company=xyz,
            source_lead=lead,
            primary_contact=contact_x,
            defaults={
                'stage': OpportunityStage.CLOSED_WON,
                'amount': Decimal('25000'),
                'expected_close_date': date.today(),
                'assigned_salesperson': salesperson,
            },
        )
        opp2.stage = OpportunityStage.CLOSED_WON
        opp2.amount = Decimal('25000')
        if salesperson:
            opp2.assigned_salesperson = salesperson
        opp2.save()

        p1 = PaymentInvoiceService.generate_from_opportunity(opp1, user=finance_user)
        if p1.paid_amount == 0:
            PaymentWorkflowService.add_transaction(
                p1,
                {
                    'amount': Decimal('5000'),
                    'payment_method': 'BANK_TRANSFER',
                    'transaction_reference': 'TXN12345',
                    'payment_date': date.today(),
                    'notes': 'Advance payment',
                },
                finance_user,
            )

        p2 = PaymentInvoiceService.generate_from_opportunity(opp2, user=finance_user)
        if p2.paid_amount == 0:
            PaymentWorkflowService.add_transaction(
                p2,
                {
                    'amount': Decimal('25000'),
                    'payment_method': 'CASH',
                    'transaction_reference': 'CASH-ERP',
                    'payment_date': date.today(),
                    'notes': 'Full payment',
                },
                finance_user,
            )

        self.stdout.write(self.style.SUCCESS(f'Demo payments ready ({Payment.objects.count()} records).'))