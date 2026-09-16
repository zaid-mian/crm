from io import BytesIO
from django.http import HttpResponse
from rest_framework.exceptions import ValidationError
from billing.models import Invoice


def generate_invoice_pdf(invoice: Invoice) -> HttpResponse:
    """
    Renders an Invoice as a PDF document using ReportLab canvas.
    If reportlab is not available, fails clearly with ValidationError rather than returning HTML.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        raise ValidationError({"detail": "ReportLab package is required for PDF generation but is not installed."})

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Margins & Typography
    margin = 54
    y = height - margin

    # Header
    c.setFont('Helvetica-Bold', 20)
    c.setFillColorRGB(0.06, 0.09, 0.16)  # #0f172a
    c.drawString(margin, y, "INVOICE")

    c.setFont('Helvetica-Bold', 12)
    c.setFillColorRGB(0.15, 0.39, 0.92)  # #2563eb
    c.drawRightString(width - margin, y, invoice.invoice_number)
    y -= 28

    # Divider line
    c.setStrokeColorRGB(0.89, 0.91, 0.94)
    c.setLineWidth(1)
    c.line(margin, y, width - margin, y)
    y -= 24

    # Billed To & Dates Summary (2 Columns)
    c.setFont('Helvetica-Bold', 10)
    c.setFillColorRGB(0.28, 0.33, 0.41)
    c.drawString(margin, y, "BILLED TO:")
    c.drawString(width / 2 + 20, y, "INVOICE DETAILS:")
    y -= 16

    c.setFont('Helvetica', 10)
    c.setFillColorRGB(0.06, 0.09, 0.16)

    customer = invoice.customer
    cust_lines = [
        customer.name,
        f"Customer #: {customer.customer_number}",
        customer.email or '',
        f"Tax ID: {customer.tax_id}" if customer.tax_id else '',
    ]
    cust_lines = [l for l in cust_lines if l]

    detail_lines = [
        f"Status: {invoice.get_status_display()}",
        f"Issue Date: {invoice.issue_date}",
        f"Due Date: {invoice.due_date}",
        f"Coverage Period: {invoice.billing_period_start or '—'} to {invoice.billing_period_end or '—'}",
        f"Subscription #: {invoice.subscription.subscription_number if invoice.subscription else 'N/A'}",
    ]

    max_lines = max(len(cust_lines), len(detail_lines))
    for i in range(max_lines):
        if i < len(cust_lines):
            c.drawString(margin, y, cust_lines[i])
        if i < len(detail_lines):
            c.drawString(width / 2 + 20, y, detail_lines[i])
        y -= 15

    y -= 15
    c.line(margin, y, width - margin, y)
    y -= 24

    # Itemized Table Header
    c.setFont('Helvetica-Bold', 9)
    c.setFillColorRGB(0.28, 0.33, 0.41)
    c.drawString(margin, y, "DESCRIPTION")
    c.drawRightString(margin + 280, y, "QTY")
    c.drawRightString(margin + 360, y, "UNIT PRICE")
    c.drawRightString(margin + 430, y, "DISCOUNT")
    c.drawRightString(width - margin, y, "TOTAL")
    y -= 12
    c.line(margin, y, width - margin, y)
    y -= 18

    # Table Rows
    c.setFont('Helvetica', 9)
    c.setFillColorRGB(0.06, 0.09, 0.16)

    lines = invoice.lines.all()
    for line in lines:
        if y < margin + 120:
            c.showPage()
            y = height - margin

        c.drawString(margin, y, line.description[:45])
        c.drawRightString(margin + 280, y, str(line.quantity))
        c.drawRightString(margin + 360, y, f"${line.unit_price}")
        c.drawRightString(margin + 430, y, f"-${line.discount_amount}" if line.discount_amount > 0 else "$0.00")
        c.drawRightString(width - margin, y, f"${line.total_amount}")
        y -= 18

    y -= 10
    c.line(margin, y, width - margin, y)
    y -= 20

    # Totals Summary Box
    totals_x = width - margin - 200
    c.setFont('Helvetica', 10)
    c.drawString(totals_x, y, "Subtotal:")
    c.drawRightString(width - margin, y, f"${invoice.subtotal}")
    y -= 16

    c.drawString(totals_x, y, "Discounts:")
    c.drawRightString(width - margin, y, f"-${invoice.discount_total}")
    y -= 16

    c.drawString(totals_x, y, "Tax Total:")
    c.drawRightString(width - margin, y, f"${invoice.tax_total}")
    y -= 16

    c.setFont('Helvetica-Bold', 12)
    c.setFillColorRGB(0.06, 0.09, 0.16)
    c.drawString(totals_x, y, "Total Amount:")
    c.drawRightString(width - margin, y, f"${invoice.total_amount}")
    y -= 18

    c.setFont('Helvetica-Bold', 10)
    c.setFillColorRGB(0.15, 0.39, 0.92)
    c.drawString(totals_x, y, "Balance Due:")
    c.drawRightString(width - margin, y, f"${invoice.balance} {invoice.customer.currency}")

    c.showPage()
    c.save()

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice-{invoice.invoice_number}.pdf"'
    return response
