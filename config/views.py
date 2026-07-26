from django.shortcuts import redirect
from django.views.generic import TemplateView


def home_redirect(request):
    return redirect('crm_payments')


class PaymentsBoardView(TemplateView):
    template_name = 'crm/payments.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['can_modify_payments'] = True
        return ctx
