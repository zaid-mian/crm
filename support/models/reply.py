from django.db import models
from django.conf import settings

class TicketReply(models.Model):
    ticket = models.ForeignKey(
        'Ticket',
        on_delete=models.CASCADE,
        related_name='replies'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='replies'
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        sender_label = "Staff" if self.sender.is_staff else "Customer"
        return f"Reply on {self.ticket.ticket_number} by {sender_label} ({self.sender.email})"
