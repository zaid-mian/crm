from rest_framework.views import exception_handler
from core.api.responses import api_error

def custom_exception_handler(exc, context):
    """
    Custom exception handler formatting standard DRF errors into our
    standardized error envelope:
    {
        "success": false,
        "message": "...",
        "errors": { ... }
    }
    """
    response = exception_handler(exc, context)
    
    if response is not None:
        errors = response.data
        message = "Validation failed." if response.status_code == 400 else str(exc)
        
        # Structure the error lists/details into a dict
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
