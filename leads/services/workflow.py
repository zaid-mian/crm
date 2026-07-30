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
    def validate_custom_values(pipeline, custom_values):
        from pipeline.models import CustomForm
        if not pipeline:
            return
        try:
            custom_form = pipeline.custom_form
        except CustomForm.DoesNotExist:
            return
        
        if not custom_form.is_active:
            return

        fields = custom_form.fields.all()
        errors = {}
        for field in fields:
            val = custom_values.get(field.label)
            if field.required and (val is None or val == ''):
                errors[field.label] = "This field is required."
                continue
            
            if val is not None and val != '':
                if field.field_type == 'NUMBER':
                    try:
                        float(val)
                    except ValueError:
                        errors[field.label] = "Must be a valid number."
                elif field.field_type == 'DATE':
                    from datetime import datetime
                    try:
                        datetime.strptime(str(val), '%Y-%m-%d')
                    except ValueError:
                        errors[field.label] = "Must be a valid date in YYYY-MM-DD format."
                elif field.field_type == 'CHECKBOX':
                    if not isinstance(val, bool) and val not in ['true', 'false', '1', '0', 1, 0, True, False]:
                        errors[field.label] = "Must be a boolean value."
                elif field.field_type == 'DROPDOWN':
                    if field.options and val not in field.options:
                        errors[field.label] = f"Must be one of the options: {', '.join(field.options)}."
        if errors:
            raise ValidationError(errors)

    @staticmethod
    @transaction.atomic
    def convert_lead(lead: Lead, opp_data=None, custom_values=None, user=None, change_source='API') -> Lead:
        from datetime import timedelta
        from contacts.models import Contact
        from opportunities.models import Opportunity
        from companies.models import Company
        
        LeadWorkflowManager.validate_convert(lead)

        custom_values = custom_values or {}
        LeadWorkflowService.validate_custom_values(lead.pipeline, custom_values)

        old_stage = lead.pipeline_stage
        old_pipeline = lead.pipeline

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
            if not company.assigned_salesperson and lead.assigned_salesperson:
                company.assigned_salesperson = lead.assigned_salesperson
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
            if not contact.assigned_salesperson and lead.assigned_salesperson:
                contact.assigned_salesperson = lead.assigned_salesperson
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

        opp_data = opp_data or {}
        deal_name = opp_data.get('name')
        if not deal_name:
            deal_name = f"{company.name} - Initial Opportunity"

        amount = opp_data.get('amount', 0.00)
        expected_close_date = opp_data.get('expected_close_date')
        if not expected_close_date:
            expected_close_date = timezone.now().date() + timedelta(days=30)

        opp_description = opp_data.get('description')
        if opp_description is None:
            opp_description = lead.notes or ""

        opp_priority = lead.priority or 'MEDIUM'

        # Find conversion stage of lead's pipeline
        conversion_stage = None
        if lead.pipeline:
            conversion_stage = lead.pipeline.stages.filter(stage_type='CONVERSION').first()

        # 3. Create Opportunity
        opp = Opportunity.objects.create(
            name=deal_name,
            company=company,
            source_lead=lead,
            primary_contact=contact,
            assigned_salesperson=lead.assigned_salesperson,
            lead_source=lead.source,
            amount=amount,
            expected_close_date=expected_close_date,
            description=opp_description,
            pipeline=lead.pipeline,
            pipeline_stage=conversion_stage,
            priority=opp_priority,
            custom_values=custom_values
        )

        # 4. Link trace-back ForeignKeys on Lead
        lead.status = Lead.LeadStatus.CONVERTED
        lead.is_converted = True
        lead.converted_at = timezone.now()
        lead.converted_company = company
        lead.converted_contact = contact
        lead.converted_opportunity = opp
        if conversion_stage:
            lead.pipeline_stage = conversion_stage
        lead.save()

        # 5. Create Audit Logs
        from pipeline.models import PipelineAuditLog
        PipelineAuditLog.objects.create(
            user=user,
            lead=lead,
            from_stage=old_stage,
            to_stage=conversion_stage,
            from_stage_name=old_stage.name if old_stage else 'None',
            to_stage_name=conversion_stage.name if conversion_stage else 'None',
            change_source=change_source
        )
        PipelineAuditLog.objects.create(
            user=user,
            opportunity=opp,
            from_stage=None,
            to_stage=conversion_stage,
            from_stage_name='None',
            to_stage_name=conversion_stage.name if conversion_stage else 'None',
            change_source=change_source
        )

        return lead

    @staticmethod
    @transaction.atomic
    def update_lead_stage(lead: Lead, target_stage, user=None, change_source='API') -> Lead:
        old_stage = lead.pipeline_stage
        old_pipeline = lead.pipeline

        # Rule 3: Pipeline switching must never silently convert Lead ↔ Opportunity
        if target_stage.entity_type == 'OPPORTUNITY' and target_stage.stage_type not in ['CONVERSION', 'LOST']:
            raise ValidationError("Leads can only be moved to Lead-compatible stages.")

        lead.pipeline_stage = target_stage
        lead.pipeline = target_stage.pipeline
        
        if target_stage.stage_type == 'NORMAL_LEAD':
            if target_stage.order == 0:
                lead.status = 'NEW'
            elif target_stage.order == 1:
                lead.status = 'CONTACTED'
            else:
                lead.status = 'FOLLOW_UP'
        elif target_stage.stage_type == 'LOST':
            lead.status = 'LOST'
        
        lead.save()

        if old_stage != target_stage or old_pipeline != target_stage.pipeline:
            from pipeline.models import PipelineAuditLog
            PipelineAuditLog.objects.create(
                user=user,
                lead=lead,
                from_stage=old_stage,
                to_stage=target_stage,
                from_stage_name=old_stage.name if old_stage else 'None',
                to_stage_name=target_stage.name,
                change_source=change_source
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

