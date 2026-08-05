from django.dispatch import Signal

# Signal fired when a tenant registration request is approved and the organization is activated.
# Downstream modules (CRM, Support, etc.) listen to this to provision their respective workspace metadata.
# Arguments: user, organization
registration_approved = Signal()
