from django.urls import path
from .views import (
    PublicContactAPIView, TicketListCreateAPIView, 
    TicketDetailAPIView, TicketReplyAPIView, 
    TicketStatusAPIView, TicketAssignAPIView
)

app_name = 'support'

urlpatterns = [
    path('contact/', PublicContactAPIView.as_view(), name='api_contact'),
    path('tickets/', TicketListCreateAPIView.as_view(), name='api_tickets'),
    path('tickets/<str:ticket_number>/', TicketDetailAPIView.as_view(), name='api_ticket_detail'),
    path('tickets/<str:ticket_number>/reply/', TicketReplyAPIView.as_view(), name='api_ticket_reply'),
    path('tickets/<str:ticket_number>/status/', TicketStatusAPIView.as_view(), name='api_ticket_status'),
    path('tickets/<str:ticket_number>/assign/', TicketAssignAPIView.as_view(), name='api_ticket_assign'),
]
