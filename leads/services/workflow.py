from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from leads.models import Lead

class LeadWorkflowManager:
    """
    State machine / rules engine defining transition validators.
    Maintains zero database writing operations (pure rules validation).
    """

    @classmethod
    def validate_assign(cls, lead: Lead, salesperson):
        if lead.is_converted:
            raise ValidationError("Cannot assign a lead that is already converted.")
        if not salesperson.is_active:
            raise ValidationError("Cannot assign a lead to an inactive salesperson.")

    @classmethod
    def validate_convert(cls, lead: Lead):
        if lead.is_converted:
            raise ValidationError("Lead is already converted.")
        if lead.status == Lead.LeadStatus.LOST:
            raise ValidationError("Cannot convert a lost lead.")
        if not lead.assigned_salesperson:
            raise ValidationError("Assign the lead to a salesperson before converting it.")

    @classmethod
    def validate_mark_lost(cls, lead: Lead):
        if lead.is_converted:
            raise ValidationError("Cannot mark a converted lead as Lost.")

    @classmethod
    def validate_mark_contacted(cls, lead: Lead):
        if lead.is_converted:
            raise ValidationError("Cannot mark a converted lead as Contacted.")
        if lead.status == Lead.LeadStatus.LOST:
            raise ValidationError("Cannot mark a lost lead as Contacted.")


class LeadWorkflowService:
    """
    Orchestrator for lead state mutations.
    Validates state using LeadWorkflowManager before saving to the DB.
    """

    @staticmethod
    @transaction.atomic
    def assign_salesperson(lead: Lead, salesperson) -> Lead:
        LeadWorkflowManager.validate_assign(lead, salesperson)
        lead.assigned_salesperson = salesperson
        if lead.status == Lead.LeadStatus.NEW:
            lead.status = Lead.LeadStatus.ASSIGNED
        lead.save()
        return lead

    @staticmethod
    @transaction.atomic
    def convert_lead(lead: Lead) -> Lead:
        from contacts.models import Contact
        
        LeadWorkflowManager.validate_convert(lead)
        lead.status = Lead.LeadStatus.CONVERTED
        lead.is_converted = True
        lead.converted_at = timezone.now()
        lead.save()

        # Create corresponding Contact inside the same transaction
        Contact.objects.create(
            full_name=lead.full_name,
            company_name=lead.company_name,
            phone_number=lead.phone or '',
            email=lead.email,
            assigned_salesperson=lead.assigned_salesperson,
            notes=lead.notes
        )
        return lead

    @staticmethod
    @transaction.atomic
    def mark_lead_lost(lead: Lead, lost_reason: str, lost_notes: str) -> Lead:
        LeadWorkflowManager.validate_mark_lost(lead)
        lead.status = Lead.LeadStatus.LOST
        lead.lost_reason = lost_reason
        lead.lost_notes = lost_notes or ""
        lead.save()
        return lead

    @staticmethod
    @transaction.atomic
    def mark_contacted(lead: Lead) -> Lead:
        LeadWorkflowManager.validate_mark_contacted(lead)
        lead.status = Lead.LeadStatus.CONTACTED
        lead.save()
        return lead

