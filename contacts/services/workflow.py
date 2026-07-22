from django.db import transaction
from rest_framework.exceptions import ValidationError
from contacts.models import Contact

class ContactWorkflowManager:
    """
    State machine / rules engine defining contact validators.
    """
    @classmethod
    def validate_assign(cls, contact: Contact, salesperson):
        if not salesperson.is_active:
            raise ValidationError("Cannot assign a contact to an inactive salesperson.")


class ContactWorkflowService:
    """
    Orchestrator for contact state mutations.
    """
    @staticmethod
    @transaction.atomic
    def assign_salesperson(contact: Contact, salesperson) -> Contact:
        ContactWorkflowManager.validate_assign(contact, salesperson)
        contact.assigned_salesperson = salesperson
        contact.save(update_fields=['assigned_salesperson', 'updated_at'])
        return contact
