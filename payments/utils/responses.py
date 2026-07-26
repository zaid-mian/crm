from rest_framework.response import Response
from rest_framework import status

def api_success(data=None, message="Success", status_code=status.HTTP_200_OK):
    """Returns a standardized API success envelope."""
    return Response({
        "success": True,
        "message": message,
        "data": data if data is not None else {}
    }, status=status_code)

def api_error(message="An error occurred", errors=None, status_code=status.HTTP_400_BAD_REQUEST):
    """Returns a standardized API error envelope."""
    return Response({
        "success": False,
        "message": message,
        "errors": errors or {}
    }, status=status_code)
