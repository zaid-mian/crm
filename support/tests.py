from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.models import Organization, OwnerProfile
from roles.models import Role
from roles.services import RoleService
from leads.models import UserProfile
from .models import ContactMessage, Ticket, TicketReply

User = get_user_model()

class SupportAPITestCase(TestCase):
    def setUp(self):
        # 1. Setup platform admin/staff user
        self.staff_user = User.objects.create_superuser(
            username="staff@platform.com",
            email="staff@platform.com",
            password="staffpassword123"
        )
        
        # 2. Setup standard customer user and their platform organization
        self.customer_user = User.objects.create_user(
            username="customer@client.com",
            email="customer@client.com",
            password="customerpassword123"
        )
        self.org = Organization.objects.create(name="Customer Corp", is_active=True)
        self.owner_profile = OwnerProfile.objects.create(
            user=self.customer_user,
            organization=self.org,
            cnic="99999-8888888-7",
            phone_number="0300-1112223"
        )

        # 3. Setup another customer user (different organization)
        self.other_user = User.objects.create_user(
            username="other@client.com",
            email="other@client.com",
            password="otherpassword123"
        )
        self.other_org = Organization.objects.create(name="Other Corp", is_active=True)
        OwnerProfile.objects.create(
            user=self.other_user,
            organization=self.other_org,
            cnic="88888-7777777-6",
            phone_number="0300-4445556"
        )

        # 4. Setup support agent role and agent user
        self.agent_user = User.objects.create_user(
            username="agent@platform.com",
            email="agent@platform.com",
            password="agentpassword123"
        )
        # Update standard CRM Profile and map a Support Agent role (handling auto-creation signal safely)
        agent_role = RoleService.get_default_role("Support Agent")
        profile, _ = UserProfile.objects.get_or_create(user=self.agent_user)
        profile.user_type = "USER"
        profile.role = agent_role
        profile.save()

        # 5. Create a general user (non-staff, no support roles)
        self.normal_user = User.objects.create_user(
            username="normal@user.com",
            email="normal@user.com",
            password="normalpassword123"
        )

    def test_public_contact_submission(self):
        """Verify guest users can submit contact message forms."""
        url = reverse('support:api_contact')
        data = {
            "name": "Guest User",
            "email": "guest@visitor.com",
            "subject": "Pre-sales query",
            "message": "Hello, I am interested in your billing modules."
        }
        response = self.client.post(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        
        # Verify db writing
        self.assertEqual(ContactMessage.objects.count(), 1)
        msg = ContactMessage.objects.first()
        self.assertEqual(msg.name, "Guest User")
        self.assertEqual(msg.status, "unread")

    def test_ticket_creation_and_tenant_scoping(self):
        """Verify ticket creation generates numbers and stamps organization references."""
        self.client.login(username="customer@client.com", password="customerpassword123")
        url = reverse('support:api_tickets')
        data = {
            "subject": "Database latency",
            "category": "technical",
            "priority": "high",
            "message": "Queries are taking over 500ms to resolve."
        }
        response = self.client.post(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 201)

        # Verify Ticket details
        ticket = Ticket.objects.get(subject="Database latency")
        self.assertEqual(ticket.user, self.customer_user)
        self.assertEqual(ticket.organization, self.org) # Tenant scoping verified
        self.assertEqual(ticket.status, "open")
        self.assertTrue(ticket.ticket_number.startswith("TKT-"))
        self.assertEqual(response.json()['data']['ticket_number'], ticket.ticket_number)

    def test_ticket_list_scopes_and_filtering(self):
        """Verify list endpoint isolates customer tickets and permits full access for staff."""
        # 1. Create a ticket for customer
        t1 = Ticket.objects.create(
            user=self.customer_user,
            organization=self.org,
            subject="Latency",
            message="Slow latency",
            category="technical",
            priority="low"
        )
        # 2. Create a ticket for other user
        t2 = Ticket.objects.create(
            user=self.other_user,
            organization=self.other_org,
            subject="Billing info",
            message="Need invoice duplicate",
            category="billing",
            priority="medium"
        )

        tickets_url = reverse('support:api_tickets')

        # Scenario A: Customer lists tickets (should see only 1)
        self.client.login(username="customer@client.com", password="customerpassword123")
        response_cust = self.client.get(tickets_url)
        self.assertEqual(response_cust.status_code, 200)
        self.assertEqual(len(response_cust.json()['data']), 1)
        self.assertEqual(response_cust.json()['data'][0]['ticket_number'], t1.ticket_number)
        self.client.logout()

        # Scenario B: Support Agent lists tickets (should see all 2)
        self.client.login(username="agent@platform.com", password="agentpassword123")
        response_agent = self.client.get(tickets_url)
        self.assertEqual(response_agent.status_code, 200)
        self.assertEqual(len(response_agent.json()['data']), 2)

        # Test filters: by category
        response_filter = self.client.get(tickets_url, {"category": "billing"})
        self.assertEqual(response_filter.status_code, 200)
        self.assertEqual(len(response_filter.json()['data']), 1)
        self.assertEqual(response_filter.json()['data'][0]['ticket_number'], t2.ticket_number)

    def test_ticket_detail_access_control(self):
        """Verify ticket detail visibility is restricted to the owner and support staff."""
        ticket = Ticket.objects.create(
            user=self.customer_user,
            organization=self.org,
            subject="Technical error",
            message="Page 500"
        )

        detail_url = reverse('support:api_ticket_detail', kwargs={'ticket_number': ticket.ticket_number})

        # 1. Other customer gets ticket (should be blocked / 404)
        self.client.login(username="other@client.com", password="otherpassword123")
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 404)
        self.client.logout()

        # 2. Owner customer gets ticket (should succeed)
        self.client.login(username="customer@client.com", password="customerpassword123")
        response_owner = self.client.get(detail_url)
        self.assertEqual(response_owner.status_code, 200)
        self.assertEqual(response_owner.json()['data']['subject'], "Technical error")
        self.client.logout()

        # 3. Support agent gets ticket (should succeed)
        self.client.login(username="agent@platform.com", password="agentpassword123")
        response_agent = self.client.get(detail_url)
        self.assertEqual(response_agent.status_code, 200)

    def test_replies_thread_and_reopen_logic(self):
        """Verify ticket reply appending and auto-reopening logic for customer responses."""
        ticket = Ticket.objects.create(
            user=self.customer_user,
            organization=self.org,
            subject="Need reset",
            message="Pls reset",
            status="closed"
        )

        reply_url = reverse('support:api_ticket_reply', kwargs={'ticket_number': ticket.ticket_number})
        self.client.login(username="customer@client.com", password="customerpassword123")

        # Post reply (should trigger reopen since ticket was closed)
        reply_data = {"message": "Still not working, please assist."}
        response = self.client.post(reply_url, reply_data, content_type='application/json')
        self.assertEqual(response.status_code, 201)

        # Assert reopening
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "open")
        self.assertEqual(ticket.replies.count(), 1)
        self.assertEqual(ticket.replies.first().message, "Still not working, please assist.")

    def test_status_transitions_rules(self):
        """Verify customers are blocked from administrative status transitions."""
        ticket = Ticket.objects.create(
            user=self.customer_user,
            organization=self.org,
            subject="Slow speed",
            message="Too slow",
            status="open"
        )

        status_url = reverse('support:api_ticket_status', kwargs={'ticket_number': ticket.ticket_number})

        # 1. Customer attempts to transition status to 'in_progress' (should be blocked)
        self.client.login(username="customer@client.com", password="customerpassword123")
        response_in_prog = self.client.post(status_url, {"status": "in_progress"}, content_type='application/json')
        self.assertEqual(response_in_prog.status_code, 403)

        # 2. Customer transitions to 'closed' (should succeed)
        response_close = self.client.post(status_url, {"status": "closed"}, content_type='application/json')
        self.assertEqual(response_close.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "closed")
        self.assertEqual(ticket.closed_by, self.customer_user)
        self.assertIsNotNone(ticket.closed_at)
        self.client.logout()

        # 3. Staff user transitions ticket back to 'in_progress' (should succeed)
        self.client.login(username="staff@platform.com", password="staffpassword123")
        response_staff = self.client.post(status_url, {"status": "in_progress"}, content_type='application/json')
        self.assertEqual(response_staff.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")
        self.assertIsNone(ticket.closed_by)

    def test_ticket_assignment_validation(self):
        """Verify tickets can only be assigned to staff or support agents."""
        ticket = Ticket.objects.create(
            user=self.customer_user,
            organization=self.org,
            subject="Assignment test",
            message="Assign me"
        )
        assign_url = reverse('support:api_ticket_assign', kwargs={'ticket_number': ticket.ticket_number})

        self.client.login(username="staff@platform.com", password="staffpassword123")

        # 1. Attempt to assign to normal non-staff user without role (should fail)
        response_fail = self.client.post(assign_url, {"assigned_to": self.normal_user.id}, content_type='application/json')
        self.assertEqual(response_fail.status_code, 400)
        self.assertIn("only be assigned to staff members or support agents", str(response_fail.json().get('errors', '')))

        # 2. Attempt to assign to CRM support agent user (should succeed)
        response_agent = self.client.post(assign_url, {"assigned_to": self.agent_user.id}, content_type='application/json')
        self.assertEqual(response_agent.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.agent_user)

        # 3. Attempt to assign to staff user (should succeed)
        response_staff = self.client.post(assign_url, {"assigned_to": self.staff_user.id}, content_type='application/json')
        self.assertEqual(response_staff.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.staff_user)

    def test_soft_deletion(self):
        """Verify tickets soft delete and are hidden from list and detail views."""
        ticket = Ticket.objects.create(
            user=self.customer_user,
            organization=self.org,
            subject="Delete target",
            message="Delete me"
        )
        detail_url = reverse('support:api_ticket_detail', kwargs={'ticket_number': ticket.ticket_number})

        # 1. Customer attempts to delete (should be blocked)
        self.client.login(username="customer@client.com", password="customerpassword123")
        response_del_cust = self.client.delete(detail_url)
        self.assertEqual(response_del_cust.status_code, 403)
        self.client.logout()

        # 2. Staff user deletes ticket (should succeed)
        self.client.login(username="staff@platform.com", password="staffpassword123")
        response_del_staff = self.client.delete(detail_url)
        self.assertEqual(response_del_staff.status_code, 200)
        
        # Verify db status (soft deleted, not hard deleted)
        ticket.refresh_from_db()
        self.assertTrue(ticket.is_deleted)
        
        # Verify it is hidden from querysets and returns 404 in detail retrieval
        response_get = self.client.get(detail_url)
        self.assertEqual(response_get.status_code, 404)
