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
        from datetime import timedelta
        from contacts.models import Contact
        from opportunities.models import Opportunity
        from companies.models import Company
        
        LeadWorkflowManager.validate_convert(lead)

        # 1. Find Company by name__iexact
        c_name = lead.company_name.strip()
        company = Company.objects.filter(name__iexact=c_name).first()

        if company:
            # Merge blank Company fields only
            company_updated = False
            if not company.phone and lead.phone:
                company.phone = lead.phone
                company_updated = True
            if not company.email and lead.email:
                company.email = lead.email
                company_updated = True
            if not company.lead_source and lead.source:
                company.lead_source = lead.source
                company_updated = True
            if not company.description and lead.notes:
                company.description = lead.notes
                company_updated = True
            if company_updated:
                company.save()
        else:
            # Create Company
            company = Company.objects.create(
                name=c_name,
                phone=lead.phone or '',
                email=lead.email,
                lead_source=lead.source or '',
                description=lead.notes or '',
                assigned_salesperson=lead.assigned_salesperson
            )

        # 2. Find Contact by company + email__iexact or phone number fallback
        contact = None
        if lead.email:
            contact = Contact.objects.filter(
                company=company,
                email__iexact=lead.email,
                is_deleted=False
            ).first()
        elif lead.phone:
            contact = Contact.objects.filter(
                company=company,
                phone_number=lead.phone,
                is_deleted=False
            ).first()

        if contact:
            # Merge blank Contact fields only
            contact_updated = False
            if not contact.notes and lead.notes:
                contact.notes = lead.notes
                contact_updated = True
            if not contact.email and lead.email:
                contact.email = lead.email
                contact_updated = True
            if not contact.phone_number and lead.phone:
                contact.phone_number = lead.phone
                contact_updated = True
            if contact_updated:
                contact.save()
        else:
            # Create Contact
            contact = Contact.objects.create(
                full_name=lead.full_name,
                company=company,
                phone_number=lead.phone or '',
                email=lead.email,
                assigned_salesperson=lead.assigned_salesperson,
                notes=lead.notes
            )

        # 3. Create Opportunity
        opp = Opportunity.objects.create(
            name=f"{company.name} - Initial Opportunity",
            company=company,
            source_lead=lead,
            primary_contact=contact,
            assigned_salesperson=lead.assigned_salesperson,
            lead_source=lead.source,
            expected_close_date=timezone.now().date() + timedelta(days=30),
            description=lead.notes or ""
        )

        # 4. Link trace-back ForeignKeys on Lead
        lead.status = Lead.LeadStatus.CONVERTED
        lead.is_converted = True
        lead.converted_at = timezone.now()
        lead.converted_company = company
        lead.converted_contact = contact
        lead.converted_opportunity = opp
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

    @staticmethod
    @transaction.atomic
    def mark_contacted(lead: Lead) -> Lead:
        LeadWorkflowManager.validate_mark_contacted(lead)
        lead.status = Lead.LeadStatus.CONTACTED
        lead.save()
        return lead

