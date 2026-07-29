from io import BytesIO

from django.http import HttpResponse
from django.template.loader import render_to_string

from payments.models import Payment, PaymentTransaction


def _payment_context(payment: Payment, transaction: PaymentTransaction | None = None) -> dict:
    opportunity = payment.opportunity
    contact = opportunity.primary_contact if opportunity else None
    return {
        'payment': payment,
        'transaction': transaction,
        'company_name': payment.company.name,
        'opportunity_name': opportunity.name if opportunity else '',
        'customer_name': contact.full_name if contact else '',
        'salesperson': payment.assigned_salesperson.get_username() if payment.assigned_salesperson else '',
    }


def render_invoice_pdf(payment: Payment) -> HttpResponse:
    html = render_to_string('payments/invoice.html', _payment_context(payment))
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 72
        c.setFont('Helvetica-Bold', 16)
        c.drawString(72, y, f'Invoice {payment.invoice_number}')
        y -= 24
        c.setFont('Helvetica', 11)
        lines = [
            f'Company: {payment.company.name}',
            f'Opportunity: {payment.opportunity.name}',
            f'Total Amount: {payment.total_amount} {payment.currency}',
            f'Paid Amount: {payment.paid_amount}',
            f'Balance: {payment.balance}',
            f'Status: {payment.get_status_display()}',
        ]
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
        c.save()
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{payment.invoice_number}.pdf"'
        return response
    except ImportError:
        response = HttpResponse(html, content_type='text/html')
        response['Content-Disposition'] = f'attachment; filename="{payment.invoice_number}.html"'
        return response


def render_receipt_pdf(payment: Payment, transaction: PaymentTransaction | None = None) -> HttpResponse:
    if transaction is None:
        transaction = payment.transactions.order_by('-payment_date', '-created_at').first()
    html = render_to_string('payments/receipt.html', _payment_context(payment, transaction))
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 72
        c.setFont('Helvetica-Bold', 16)
        c.drawString(72, y, 'Payment Receipt')
        y -= 24
        c.setFont('Helvetica', 11)
        amount = transaction.amount if transaction else payment.paid_amount
        lines = [
            f'Invoice: {payment.invoice_number}',
            f'Company: {payment.company.name}',
            f'Amount Received: {amount} {payment.currency}',
            f'Method: {transaction.get_payment_method_display() if transaction else "-"}',
            f'Reference: {transaction.transaction_reference if transaction else "-"}',
            f'Date: {transaction.payment_date if transaction else payment.payment_date}',
        ]
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
        c.save()
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="receipt-{payment.invoice_number}.pdf"'
        return response
    except ImportError:
        response = HttpResponse(html, content_type='text/html')
        response['Content-Disposition'] = f'attachment; filename="receipt-{payment.invoice_number}.html"'
        return response
