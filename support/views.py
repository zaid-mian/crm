from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from django.utils import timezone
from django.db.models import Q
from django.contrib.auth import get_user_model
from core.api.responses import api_success, api_error
from .models import ContactMessage, Ticket, TicketReply
from .serializers import (
    ContactMessageSerializer, TicketReplySerializer, 
    TicketSerializer, TicketDetailSerializer, TicketStatusSerializer
)
from .permissions import IsSupportStaff

User = get_user_model()

class PublicContactAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return api_success(
                data=serializer.data,
                message="Your contact message has been submitted successfully.",
                status_code=status.HTTP_201_CREATED
            )
        return api_error(message="Contact form validation failed.", errors=serializer.errors)


class TicketListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        is_staff = IsSupportStaff().has_permission(request, self)
        
        # Base filter: exclude soft deleted tickets
        queryset = Ticket.objects.filter(is_deleted=False)
        
        if not is_staff:
            # Customers only see their own tickets
            queryset = queryset.filter(user=request.user)
        
        # Filtering queries
        category = request.query_params.get('category')
        ticket_status = request.query_params.get('status')
        priority = request.query_params.get('priority')
        assigned_to = request.query_params.get('assigned_to')

        if category:
            queryset = queryset.filter(category=category)
        if ticket_status:
            queryset = queryset.filter(status=ticket_status)
        if priority:
            queryset = queryset.filter(priority=priority)
        if assigned_to:
            queryset = queryset.filter(assigned_to__email=assigned_to)

        serializer = TicketSerializer(queryset, many=True)
        return api_success(data=serializer.data, message="Tickets retrieved successfully")

    def post(self, request):
        serializer = TicketSerializer(data=request.data)
        if serializer.is_valid():
            # Resolve organization from owner profile for multi-tenancy scoping
            org = None
            try:
                profile = request.user.ownerprofile
                org = profile.organization
            except Exception:
                pass

            ticket = serializer.save(
                user=request.user,
                organization=org,
                status='open'
            )
            return api_success(
                data=TicketSerializer(ticket).data,
                message="Ticket created successfully.",
                status_code=status.HTTP_201_CREATED
            )
        return api_error(message="Ticket verification failed.", errors=serializer.errors)


class TicketDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_ticket(self, request, ticket_number):
        is_staff = IsSupportStaff().has_permission(request, self)
        queryset = Ticket.objects.filter(ticket_number=ticket_number, is_deleted=False)
        
        if not is_staff:
            queryset = queryset.filter(user=request.user)
            
        ticket = queryset.first()
        return ticket

    def get(self, request, ticket_number):
        ticket = self.get_ticket(request, ticket_number)
        if not ticket:
            return api_error("Ticket not found.", status_code=status.HTTP_404_NOT_FOUND)
            
        serializer = TicketDetailSerializer(ticket)
        return api_success(data=serializer.data, message="Ticket details retrieved")

    def delete(self, request, ticket_number):
        # Soft delete action (only support staff/managers can delete)
        is_staff = IsSupportStaff().has_permission(request, self)
        if not is_staff:
            return api_error("Access denied.", status_code=status.HTTP_403_FORBIDDEN)
            
        ticket = Ticket.objects.filter(ticket_number=ticket_number, is_deleted=False).first()
        if not ticket:
            return api_error("Ticket not found.", status_code=status.HTTP_404_NOT_FOUND)
            
        ticket.soft_delete()
        return api_success(message="Ticket soft deleted successfully.")


class TicketReplyAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, ticket_number):
        is_staff = IsSupportStaff().has_permission(request, self)
        queryset = Ticket.objects.filter(ticket_number=ticket_number, is_deleted=False)
        if not is_staff:
            queryset = queryset.filter(user=request.user)
            
        ticket = queryset.first()
        if not ticket:
            return api_error("Ticket not found.", status_code=status.HTTP_404_NOT_FOUND)

        message = request.data.get('message')
        if not message:
            return api_error("Message body is required.", status_code=status.HTTP_400_BAD_REQUEST)

        # Reopen ticket if a customer replies to a resolved/closed ticket
        if not is_staff and ticket.status in ['resolved', 'closed']:
            ticket.status = 'open'
            ticket.save()

        reply = TicketReply.objects.create(
            ticket=ticket,
            sender=request.user,
            message=message
        )
        
        # Prepare webhook/notifications hook here
        # (Future event system dispatcher could be hooked here)

        serializer = TicketReplySerializer(reply)
        return api_success(
            data=serializer.data,
            message="Reply submitted successfully.",
            status_code=status.HTTP_201_CREATED
        )


class TicketStatusAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, ticket_number):
        is_staff = IsSupportStaff().has_permission(request, self)
        queryset = Ticket.objects.filter(ticket_number=ticket_number, is_deleted=False)
        if not is_staff:
            queryset = queryset.filter(user=request.user)
            
        ticket = queryset.first()
        if not ticket:
            return api_error("Ticket not found.", status_code=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        valid_statuses = [s[0] for s in Ticket.STATUS_CHOICES]

        if new_status not in valid_statuses:
            return api_error(
                f"Invalid status value. Choose from: {', '.join(valid_statuses)}",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        # Access rule: Non-staff can only transition tickets to 'closed'
        if not is_staff and new_status != 'closed':
            return api_error(
                "Access denied. Customers can only close their own tickets.",
                status_code=status.HTTP_403_FORBIDDEN
            )

        ticket.status = new_status
        if new_status == 'closed':
            ticket.closed_by = request.user
            ticket.closed_at = timezone.now()

        ticket.save()
        return api_success(
            data={
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "closed_by": ticket.closed_by.email if ticket.closed_by else None,
                "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None
            },
            message="Ticket status updated successfully."
        )


class TicketAssignAPIView(APIView):
    permission_classes = [IsSupportStaff]

    def post(self, request, ticket_number):
        ticket = Ticket.objects.filter(ticket_number=ticket_number, is_deleted=False).first()
        if not ticket:
            return api_error("Ticket not found.", status_code=status.HTTP_404_NOT_FOUND)

        assignee_id = request.data.get('assigned_to')
        if not assignee_id:
            # Unassign ticket
            ticket.assigned_to = None
            ticket.save()
            return api_success(message="Ticket unassigned successfully.")

        try:
            assignee = User.objects.get(id=assignee_id)
        except User.DoesNotExist:
            return api_error("Assignee user not found.", status_code=status.HTTP_404_NOT_FOUND)

        ticket.assigned_to = assignee
        try:
            ticket.full_clean()
        except Exception as e:
            return api_error(
                message="Cannot assign ticket to this user.",
                errors=getattr(e, 'message_dict', str(e)),
                status_code=status.HTTP_400_BAD_REQUEST
            )

        ticket.save()
        return api_success(
            data={"ticket_number": ticket.ticket_number, "assigned_to": ticket.assigned_to.email},
            message="Ticket assigned successfully."
        )
