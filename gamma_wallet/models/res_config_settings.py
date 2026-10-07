import time

from markupsafe import Markup

from odoo import _, api, fields, models

from . import gamma_api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gamma_token = fields.Char(
        string="Integration token", config_parameter=gamma_api.PARAM_TOKEN,
        help="Create it in Gamma Business → Integrations, as the business owner. It starts with GWINT_ and is shown only once.")
    gamma_rewards = fields.Boolean(
        string="Rewards for paid orders", config_parameter=gamma_api.PARAM_REWARDS,
        help="Give customers a QR code to collect their reward for each paid order.")
    gamma_reward_email = fields.Boolean(
        string="Email the reward", config_parameter=gamma_api.PARAM_REWARD_EMAIL,
        help="Email the customer the reward QR code when the order is confirmed.")
    # The settings form is a new record each time, so these are filled by defaults, not computes.
    gamma_reward_provider_ids = fields.Many2many(
        'payment.provider', string="Payment providers that earn a reward",
        default=lambda self: self._gamma_default_reward_providers(),
        domain="[('code', '!=', 'gamma_wallet'), ('state', '!=', 'disabled')]")
    gamma_status = fields.Html(
        string="Gamma Wallet status", sanitize=False, readonly=True,
        default=lambda self: self._gamma_status_html())

    @api.model
    def _gamma_default_reward_providers(self):
        return self.env['payment.provider'].sudo().search([
            ('code', '!=', 'gamma_wallet'), ('state', '!=', 'disabled'), ('gamma_earns_reward', '=', True)])

    @api.model
    def _gamma_status_html(self):
        token = (self.env['ir.config_parameter'].sudo().get_param(gamma_api.PARAM_TOKEN) or '').strip()
        if not token:
            return Markup('<span class="text-danger">%s</span>') % _("Not connected. Paste your integration token above and save.")
        connection = gamma_api.get_connection(self.env)
        if not connection:
            return Markup('%s') % _("Not checked yet. Save, or click Check again.")
        parts = []
        if connection.get('error') and not connection.get('businessName'):
            parts.append(Markup('<span class="text-danger">%s</span>') % connection['error'])
        else:
            if connection.get('error'):
                parts.append(Markup('<span class="text-warning">%s</span>') % connection['error'])
            parts.append(Markup('<span class="text-success">✓ %s</span>') % _("Connected"))
            parts.append(Markup('%s: <strong>%s</strong> · %s: <strong>%s</strong>') % (
                _("Business"), connection.get('businessName', ''), _("Currency"), connection.get('currencyCode', '')))
            parts.append(Markup('%s <code>%s</code>, %s') % (
                _("Token"), gamma_api.masked(token),
                _("%s day(s) left", (connection.get('token') or {}).get('daysLeft', '?'))))
            if not connection.get('canClaim'):
                parts.append(Markup('<span class="text-danger">%s</span>') % _(
                    "Gamma Wallet for Odoo works only with a Reward service. Your business has no Reward service "
                    "active in Gamma, so customers get no reward QR code and store credits are not offered at "
                    "checkout. Activate a Reward service in Gamma Business."))
            # The currency the shop sells in: its website's (pricelist) currency, else the company's.
            website = self.env['website'].sudo().search([('company_id', '=', self.env.company.id)], limit=1)
            company_currency = (website.currency_id or self.env.company.currency_id).name
            if not gamma_api.currency_matches(self.env, company_currency):
                parts.append(Markup('<span class="text-danger">%s</span>') % _(
                    "Your shop sells in %(shop)s but your Gamma business uses %(gamma)s. Orders cannot be sent to "
                    "Gamma until they match.", shop=company_currency, gamma=connection.get('currencyCode')))
        if connection.get('checkedOn'):
            parts.append(Markup('<span class="text-muted">%s %s</span>') % (
                _("Checked"), time.strftime('%Y-%m-%d %H:%M', time.localtime(int(connection['checkedOn'])))))
        return Markup('<br/>').join(parts)

    def set_values(self):
        res = super().set_values()
        # Ticked providers earn a reward; every other one (store credits aside) does not.
        all_providers = self.env['payment.provider'].sudo().search([('code', '!=', 'gamma_wallet'), ('state', '!=', 'disabled')])
        chosen = self.gamma_reward_provider_ids.sudo()
        (all_providers - chosen).gamma_earns_reward = False
        chosen.gamma_earns_reward = True
        gamma_api.check_connection(self.env)
        return res

    def action_gamma_check_connection(self):
        # Settings are for administrators only, also when called directly rather than from the page.
        self.check_access('write')
        gamma_api.check_connection(self.env)
        return {'type': 'ir.actions.client', 'tag': 'reload'}
