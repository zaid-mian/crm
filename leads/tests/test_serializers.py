from django.test import TestCase
from django.contrib.auth import get_user_model
from leads.models import Lead
from leads.serializers import (
    LeadCreateSerializer,
    LeadUpdateSerializer,
    LeadListSerializer,
    LeadDetailSerializer,
)

User = get_user_model()

class LeadSerializerTestCase(TestCase):
    def setUp(self):
        self.salesperson = User.objects.create_user(
            username='salesperson',
            email='sales@example.com',
            password='password123'
        )

    def test_create_serializer_write_protections(self):
        """Verify that workflow-related fields cannot be written during creation."""
        data = {
            "full_name": "Test Lead",
            "phone": "+1234567890",
            "email": "test@example.com",
            "company_name": "Test Inc",
            "status": Lead.LeadStatus.LOST,  # Should be ignored/protected
            "assigned_salesperson": self.salesperson.id,  # Should be ignored/protected
            "is_converted": True  # Should be ignored/protected
        }
        serializer = LeadCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        lead = serializer.save()
        
        # Verify defaults are set instead of values supplied in data
        self.assertEqual(lead.status, Lead.LeadStatus.NEW)
        self.assertIsNone(lead.assigned_salesperson)
        self.assertFalse(lead.is_converted)

    def test_update_serializer_write_protections(self):
        """Verify that workflow-related fields cannot be updated using normal update serializer."""
        lead = Lead.objects.create(
            full_name="Original Name",
            phone="+1234567890",
            email="original@example.com",
            company_name="Original Inc",
            status=Lead.LeadStatus.NEW,
            is_converted=False
        )
        
        update_data = {
            "full_name": "Updated Name",
            "status": Lead.LeadStatus.CONVERTED,  # Should be ignored/protected
            "is_converted": True  # Should be ignored/protected
        }
        serializer = LeadUpdateSerializer(instance=lead, data=update_data, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated_lead = serializer.save()
        
        # Verify normal field is modified while workflow fields are untouched
        self.assertEqual(updated_lead.full_name, "Updated Name")
        self.assertEqual(updated_lead.status, Lead.LeadStatus.NEW)
        self.assertFalse(updated_lead.is_converted)

    def test_phone_duplicate_validation_active_leads(self):
        """Verify duplicate validation on phone fails for active leads but passes if converted."""
        Lead.objects.create(
            full_name="Active Lead",
            phone="+1234567890",
            company_name="Active Inc",
            is_converted=False
        )

        # Attempt to create duplicate active lead
        data = {
            "full_name": "Duplicate Lead",
            "phone": "+1234567890",
            "company_name": "Duplicate Inc"
        }
        serializer = LeadCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("phone", serializer.errors)

        # Mark first lead as converted
        Lead.objects.all().update(is_converted=True)

        # Now attempting to create should pass validation since active lead isn't duplicate
        serializer_second = LeadCreateSerializer(data=data)
        self.assertTrue(serializer_second.is_valid(), serializer_second.errors)

    def test_email_duplicate_validation_active_leads(self):
        """Verify duplicate validation on email fails for active leads but passes if converted."""
        Lead.objects.create(
            full_name="Active Lead",
            phone="+1234567890",
            email="duplicate@example.com",
            company_name="Active Inc",
            is_converted=False
        )

        data = {
            "full_name": "Duplicate Lead",
            "phone": "+9876543210",
            "email": "duplicate@example.com",
            "company_name": "Duplicate Inc"
        }
        serializer = LeadCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

        # Converted leads duplicate email check passes
        Lead.objects.all().update(is_converted=True)
        serializer_second = LeadCreateSerializer(data=data)
        self.assertTrue(serializer_second.is_valid(), serializer_second.errors)

    def test_detail_serializer_read_only_placeholder_fields(self):
        """Verify that detail serializer outputs empty list placeholders for activities/tasks."""
        lead = Lead.objects.create(
            full_name="John Detail",
            phone="+1234567890",
            company_name="Acme"
        )
        serializer = LeadDetailSerializer(instance=lead)
        self.assertEqual(serializer.data["activities"], [])
        self.assertEqual(serializer.data["tasks"], [])

    def test_email_or_phone_required_validation(self):
        """Verify that validation requires at least email or phone."""
        # 1. Success with only email
        data_email_only = {
            "full_name": "Email Only",
            "company_name": "Acme Inc",
            "email": "only_email@example.com"
        }
        serializer = LeadCreateSerializer(data=data_email_only)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # 2. Success with only phone
        data_phone_only = {
            "full_name": "Phone Only",
            "company_name": "Acme Inc",
            "phone": "+12345"
        }
        serializer2 = LeadCreateSerializer(data=data_phone_only)
        self.assertTrue(serializer2.is_valid(), serializer2.errors)

        # 3. Failure with neither
        data_neither = {
            "full_name": "Neither",
            "company_name": "Acme Inc"
        }
        serializer3 = LeadCreateSerializer(data=data_neither)
        self.assertFalse(serializer3.is_valid())
        self.assertIn("non_field_errors", serializer3.errors)

    def test_phone_duplicate_validation_ignores_blank(self):
        """Verify duplicate validation on phone ignores empty string value."""
        Lead.objects.create(
            full_name="Blank Phone Lead",
            phone="",
            email="blank_email1@example.com",
            company_name="Acme Inc",
            is_converted=False
        )

        data = {
            "full_name": "Another Blank Phone Lead",
            "phone": "",
            "email": "blank_email2@example.com",
            "company_name": "Acme Inc"
        }
        serializer = LeadCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
