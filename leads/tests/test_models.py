from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from leads.models import Lead

User = get_user_model()

class LeadModelTestCase(TestCase):
    def setUp(self):
        # Create a salesperson for model tests
        self.salesperson = User.objects.create_user(
            username='salesperson',
            email='sales@example.com',
            password='password123'
        )

    def test_lead_code_format(self):
        """Verify dynamic property lead_code returns correctly based on id."""
        lead = Lead.objects.create(
            full_name="John Doe",
            phone="+1234567890",
            email="john@example.com",
            company_name="Acme Corp"
        )
        self.assertEqual(lead.lead_code, f"LD-{lead.id:06d}")

    def test_lead_code_none_if_unsaved(self):
        """Verify lead_code is None if the instance is not saved in the database."""
        lead = Lead(
            full_name="Jane Doe",
            phone="+1234567891",
            company_name="Acme Corp"
        )
        self.assertNull = self.assertIsNone(lead.lead_code)

    def test_string_representation(self):
        """Verify __str__() returns formatted representation."""
        lead = Lead.objects.create(
            full_name="John Doe",
            phone="+1234567890",
            email="john@example.com",
            company_name="Acme Corp"
        )
        self.assertEqual(str(lead), f"{lead.lead_code} - John Doe")

    def test_clean_validation_lost_requires_reason(self):
        """Verify that status=LOST requires lost_reason."""
        lead = Lead(
            full_name="John Doe",
            phone="+1234567890",
            company_name="Acme Corp",
            status=Lead.LeadStatus.LOST
        )
        with self.assertRaises(ValidationError) as ctx:
            lead.full_clean()
        self.assertIn('lost_reason', ctx.exception.error_dict)

    def test_clean_validation_lost_succeeds_with_reason(self):
        """Verify clean validation succeeds when lost lead has reason."""
        lead = Lead(
            full_name="John Doe",
            phone="+1234567890",
            company_name="Acme Corp",
            status=Lead.LeadStatus.LOST,
            lost_reason=Lead.LostReason.BUDGET_TOO_HIGH
        )
        # Should not raise validation error
        lead.full_clean()

    def test_clean_validation_non_lost_cannot_have_lost_details(self):
        """Verify that lost reason or notes are rejected if status is not LOST."""
        lead = Lead(
            full_name="John Doe",
            phone="+1234567890",
            company_name="Acme Corp",
            status=Lead.LeadStatus.NEW,
            lost_reason=Lead.LostReason.NOT_INTERESTED
        )
        with self.assertRaises(ValidationError):
            lead.full_clean()

        lead_with_notes = Lead(
            full_name="John Doe",
            phone="+1234567890",
            company_name="Acme Corp",
            status=Lead.LeadStatus.NEW,
            lost_notes="Some lost notes here."
        )
        with self.assertRaises(ValidationError):
            lead_with_notes.full_clean()

    def test_pipeline_matching_stage_validation(self):
        """Verify that lead full_clean/save raises ValidationError if pipeline doesn't match stage's pipeline."""
        from pipeline.models import Pipeline, PipelineStage
        pipeline1 = Pipeline.objects.create(name="Pipeline 1")
        pipeline2 = Pipeline.objects.create(name="Pipeline 2")
        stage1 = PipelineStage.objects.create(
            pipeline=pipeline1,
            name="Stage 1",
            entity_type='LEAD',
            order=0,
            stage_type='NORMAL_LEAD'
        )
        
        lead = Lead(
            full_name="Mismatched Lead",
            phone="+12345",
            company_name="Acme Inc",
            pipeline=pipeline2,
            pipeline_stage=stage1
        )
        
        with self.assertRaises(ValidationError):
            lead.full_clean()
            
        with self.assertRaises(ValidationError):
            lead.save()
