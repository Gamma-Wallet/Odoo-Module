from odoo import api, fields, models

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
    def _get_compatible_providers(self, *args, currency_id=None, **kwargs):
        """ "Use Store Credits with Gamma" is offered only when it can work for this order: the shop is
        connected, the business has a Reward service, the currency matches and there is a total. """
        providers = super()._get_compatible_providers(*args, currency_id=currency_id, **kwargs)
        gamma = providers.filtered(lambda p: p.code == 'gamma_wallet')
        if not gamma:
            return providers
        currency = self.env['res.currency'].browse(currency_id).exists() if currency_id else self.env.company.currency_id
        amount = kwargs.get('amount', args[2] if len(args) > 2 else None)
        usable = (
            gamma_api.reward_service_active(self.env)
            and gamma_api.currency_matches(self.env, currency.name)
            and (amount is None or amount > 0)
        )
        return providers if usable else providers - gamma

    def _gamma_is_pay_later(self):
        self.ensure_one()
        return self.code in PAY_LATER_CODES
