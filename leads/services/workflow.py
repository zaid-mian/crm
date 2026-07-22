from django.db import transaction
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
        lead.save()
        return lead

    @staticmethod
    @transaction.atomic
    def convert_lead(lead: Lead) -> Lead:
        LeadWorkflowManager.validate_convert(lead)
        lead.status = Lead.LeadStatus.CONVERTED
        lead.is_converted = True
        lead.save()
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
