from rest_framework.views import exception_handler
from contacts.utils.responses import api_error

def custom_exception_handler(exc, context):
    """
    Custom exception handler formatting standard DRF errors into standardized error envelope.
    """
    response = exception_handler(exc, context)

    if response is not None:
        errors = response.data
        message = "Validation failed." if response.status_code == 400 else str(exc)

        if isinstance(errors, list):
            errors = {"detail": errors}
        elif not isinstance(errors, dict):
            errors = {"detail": [str(errors)]}

        response.data = {
            "success": False,
            "message": message,
            "errors": errors
        }

    return response
