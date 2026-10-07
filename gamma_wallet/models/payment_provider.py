from odoo import api, fields, models
from odoo.addons.payment import utils as payment_utils

from . import gamma_api

# Paid outside the shop, after the order is placed: wire transfer, pay on site.
PAY_LATER_CODES = ('custom',)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('gamma_wallet', "Gamma Wallet store credits")],
        ondelete={'gamma_wallet': 'set default'},
    )
    gamma_earns_reward = fields.Boolean(
        string="Earns a Gamma reward",
        help="Orders paid with this payment provider earn a Gamma Wallet reward once they are paid. "
             "Paid-later providers (wire transfer, pay on site) earn it when you confirm the order.",
        default=True,
    )

    @api.model_create_multi
    def create(self, values_list):
        providers = super().create(values_list)
        # Paid-later providers and the store credits themselves do not earn a reward by default.
        providers.filtered(lambda p: p.code in PAY_LATER_CODES + ('gamma_wallet',)).gamma_earns_reward = False
        return providers

    def _get_default_payment_method_codes(self):
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'gamma_wallet':
            return default_codes
        return {'gamma_wallet'}

    @api.model
    def _get_compatible_providers(self, *args, currency_id=None, sale_order_id=None, report=None, **kwargs):
        """ "Use Store Credits with Gamma" is offered only when it can work: for a sales order (the
        checkout or the order's page, not a generic payment link or an invoice), for its whole total
        (not a down payment or a remainder), while the shop is connected, the business has a Reward
        service and the currency matches. """
        providers = super()._get_compatible_providers(
            *args, currency_id=currency_id, sale_order_id=sale_order_id, report=report, **kwargs)
        gamma = providers.filtered(lambda p: p.code == 'gamma_wallet')
        if not gamma:
            return providers
        currency = self.env['res.currency'].browse(currency_id).exists() if currency_id else self.env.company.currency_id
        amount = kwargs.get('amount', args[2] if len(args) > 2 else None)
        order = self.env['sale.order'].sudo().browse(sale_order_id).exists() if sale_order_id else None
        reason = None
        if not order:
            reason = "Gamma Wallet: only for a sales order"
        elif amount is None or order.amount_total <= 0 or currency.compare_amounts(amount, order.amount_total) != 0:
            reason = "Gamma Wallet: store credits settle the whole order only"
        elif not gamma_api.reward_service_active(self.env):
            reason = "Gamma Wallet: not connected, or no Reward service active"
        elif not gamma_api.currency_matches(self.env, currency.name):
            reason = "Gamma Wallet: the currency is not the Gamma business's"
        if reason is None:
            return providers
        payment_utils.add_to_report(report, gamma, available=False, reason=reason)
        return providers - gamma

    def _gamma_is_pay_later(self):
        self.ensure_one()
        return self.code in PAY_LATER_CODES
