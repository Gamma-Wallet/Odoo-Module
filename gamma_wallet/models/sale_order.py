import logging
import time

from markupsafe import Markup

from odoo import SUPERUSER_ID, _, fields, models
from odoo.exceptions import UserError

from . import gamma_api

_logger = logging.getLogger(__name__)

# No more automatic attempts after this many failures; the shop can still send the reward by hand.
MAX_ATTEMPTS = 6


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    gamma_bill_id = fields.Char(string="Gamma bill", readonly=True, copy=False)
    gamma_code = fields.Char(readonly=True, copy=False)
    gamma_link = fields.Char(string="Reward link", readonly=True, copy=False)
    gamma_qr_url = fields.Char(readonly=True, copy=False)
    gamma_bill_status = fields.Char(string="Reward status", readonly=True, copy=False)
    gamma_claimed_on = fields.Char(readonly=True, copy=False)
    gamma_error = fields.Char(string="Gamma error", readonly=True, copy=False)
    gamma_attempts = fields.Integer(readonly=True, copy=False)
    gamma_emailed = fields.Boolean(string="Reward emailed", readonly=True, copy=False)
    gamma_summary = fields.Html(string="Gamma Wallet", compute='_compute_gamma_summary', sanitize=False)

    # ------------------------------------------------------------------ which orders earn a reward

    def _gamma_transaction(self):
        """ The transaction the order was paid (or is to be paid) with. """
        self.ensure_one()
        txs = self.transaction_ids.filtered(lambda t: t.state in ('done', 'authorized', 'pending'))
        return (txs or self.transaction_ids).sorted('id')[-1:] if (txs or self.transaction_ids) else txs

    def _gamma_provider(self):
        tx = self._gamma_transaction()
        return tx.provider_id if tx else self.env['payment.provider']

    def _gamma_settled_with_credits(self):
        return self._gamma_provider().code == 'gamma_wallet'

    def _gamma_may_earn(self):
        """ True when this order can ever earn a reward, now or once it is paid. """
        self.ensure_one()
        provider = self._gamma_provider()
        return (
            bool(self.website_id)
            and bool(provider)
            and provider.code != 'gamma_wallet'
            and provider.gamma_earns_reward
            and gamma_api.flag(self.env, gamma_api.PARAM_REWARDS)
            and gamma_api.reward_service_active(self.env)
        )

    def _gamma_qualifies(self):
        """ True when this order should have a reward QR code now: it is a shop order, rewards are
        on, the business has a Reward service, the payment provider earns one, the currencies match
        and the order is confirmed — for a paid-later order, that is when the shop confirms it once
        the money is in. Orders settled with store credits never earn one. """
        self.ensure_one()
        return (
            self.state == 'sale'
            and self.amount_total > 0
            and self._gamma_may_earn()
            and gamma_api.currency_matches(self.env, self.currency_id.name)
        )

    # ------------------------------------------------------------------ the Gamma bill

    def _gamma_ensure_bill(self):
        """ Declares the order to Gamma once. Returns True when the order has a bill afterwards.
        Safe to call any number of times: Gamma returns the same bill for the same reference. """
        self.ensure_one()
        order = self.sudo()
        if order.gamma_bill_id:
            return True
        if not order._gamma_qualifies() or order.gamma_attempts >= MAX_ATTEMPTS:
            return False
        api = gamma_api.GammaApi.from_env(self.env)
        if not api:
            return False
        try:
            bill = api.create_bill({
                'reference': order.name,
                'total': round(order.amount_total, order.currency_id.decimal_places),
                'currencyCode': order.currency_id.name,
                'issuedOn': fields.Datetime.now().isoformat() + 'Z',
                'platform': 'odoo',
                'pluginVersion': gamma_api.VERSION,
            })
        except gamma_api.GammaApiError as e:
            order.write({'gamma_error': gamma_api.explain(e)[:250], 'gamma_attempts': order.gamma_attempts + 1})
            _logger.warning("Gamma Wallet: bill for %s failed: %s", order.name, e)
            return False
        order.write({
            'gamma_bill_id': bill['billId'],
            'gamma_code': bill['code'],
            'gamma_link': bill['link'],
            'gamma_qr_url': bill['qrImageUrl'],
            'gamma_bill_status': bill['status'],
            'gamma_claimed_on': bill.get('claimedOn'),
            'gamma_error': False,
        })
        order.message_post(body=_("Sent to Gamma Wallet. The customer can collect the reward for this order with its QR code."))
        return True

    def _gamma_refresh_status(self):
        """ Asks Gamma whether the reward was collected. "Waiting" or "Claimed". """
        self.ensure_one()
        order = self.sudo()
        if order.gamma_bill_status == 'Claimed' or not order.gamma_bill_id:
            return order.gamma_bill_status or ''
        api = gamma_api.GammaApi.from_env(self.env)
        if not api:
            return order.gamma_bill_status or ''
        try:
            bill = api.get_bill(order.gamma_bill_id)
        except gamma_api.GammaApiError:
            return order.gamma_bill_status or ''
        if bill['status'] != order.gamma_bill_status:
            order.write({'gamma_bill_status': bill['status'], 'gamma_claimed_on': bill.get('claimedOn')})
            if bill['status'] == 'Claimed':
                order.message_post(body=_("The customer collected the Gamma Wallet reward."))
        return bill['status']

    def _gamma_send_reward_email(self):
        """ The reward email: the QR code, with a link that opens Gamma Wallet on a phone. """
        self.ensure_one()
        order = self.sudo()
        if not order._gamma_ensure_bill() or not order.partner_id.email:
            return False
        # Sent as the system (OdooBot), like Odoo's own order emails: the confirmation often runs for
        # the website's anonymous visitor, who has no sender address.
        template = self.env.ref('gamma_wallet.mail_template_gamma_reward').with_user(SUPERUSER_ID)
        template.send_mail(order.id, force_send=True)
        order.gamma_emailed = True
        order.message_post(body=_("The Gamma reward QR code was emailed to %s.", order.partner_id.email))
        return True

    def _gamma_reward_after_confirm(self):
        """ Once an order is confirmed it gets its reward, and the customer an email with it. """
        for order in self:
            if not order._gamma_ensure_bill() or order.gamma_emailed:
                continue
            # A paid-later customer has no confirmation page to see it on: the email always goes.
            if order._gamma_provider()._gamma_is_pay_later() or gamma_api.flag(self.env, gamma_api.PARAM_REWARD_EMAIL):
                order._gamma_send_reward_email()

    def _gamma_cron_retry(self):
        """ Every 10 minutes: confirmed shop orders whose reward failed (Gamma unreachable, busy…)
        are tried again, up to MAX_ATTEMPTS times, and the customer then gets the reward email. """
        orders = self.search([
            ('state', '=', 'sale'), ('website_id', '!=', False), ('gamma_bill_id', '=', False),
            ('gamma_error', '!=', False), ('gamma_attempts', '<', MAX_ATTEMPTS),
        ], limit=50)
        orders._gamma_reward_after_confirm()

    def action_confirm(self):
        res = super().action_confirm()
        try:
            self._gamma_reward_after_confirm()
        except Exception:  # never let a reward problem block the order
            _logger.exception("Gamma Wallet: reward after confirmation failed")
        return res

    def action_gamma_send_reward(self):
        """ The button on the order: create the reward if needed and email it to the customer. """
        for order in self:
            if not order._gamma_send_reward_email():
                raise UserError(order.gamma_error or _(
                    "The Gamma reward QR code could not be sent: the order is not eligible for a reward "
                    "yet, the customer has no email address, or Gamma could not be reached."))
        return True

    # ------------------------------------------------------------------ what the customer sees

    def gamma_portal_values(self):
        """ What the order confirmation and portal pages show for this order (read-only):
        kind = 'credit' (QR code to settle with store credits), 'credit_done', 'reward', 'note' or None. """
        self.ensure_one()
        order = self.sudo()
        token = order._portal_ensure_token()
        base = {'status_url': '/gamma_wallet/status/%d?access_token=%s' % (order.id, token),
                'new_code_url': '/gamma_wallet/new_code/%d?access_token=%s' % (order.id, token)}
        if order._gamma_settled_with_credits():
            tx = order._gamma_transaction()
            if tx.state == 'done':
                return dict(base, kind='credit_done')
            from ..controllers.main import _expires_at  # noqa: avoid a circular import at load
            seconds = max(0, _expires_at(tx.gamma_expires_on) - int(time.time())) if tx.gamma_expires_on else 0
            return dict(base, kind='credit', seconds=seconds, link=tx.gamma_credit_link or '',
                        qr='data:image/png;base64,%s' % tx.gamma_credit_qr if tx.gamma_credit_qr else '')
        if order.state == 'sale':
            order._gamma_ensure_bill()  # retries a failed one when the customer looks
        if order.gamma_bill_id:
            claimed = order.gamma_bill_status == 'Claimed'
            return dict(base, kind='reward', claimed=claimed, poll=not claimed,
                        qr=order.gamma_qr_url, link=order.gamma_link)
        if order.state != 'sale' and order._gamma_may_earn():
            note = (_("This order earns a Gamma Wallet reward. Once your payment is received, we will email you a QR code to collect it.")
                    if order._gamma_provider()._gamma_is_pay_later()
                    else _("As soon as your payment is confirmed, you will receive a QR code by email to collect your reward with Gamma Wallet."))
            return dict(base, kind='note', note=note)
        return dict(base, kind=None)

    # ------------------------------------------------------------------ the box on the order form

    def _compute_gamma_summary(self):
        for order in self:
            lines = []
            qr = ''
            if order._gamma_settled_with_credits():
                tx = order._gamma_transaction()
                lines.append(_("Settled with store credits through Gamma Wallet.") if tx.state == 'done'
                             else _("Waiting for the customer to settle it with store credits."))
                if tx.gamma_request_id:
                    lines.append(_("Request: %s", tx.gamma_request_id))
                lines.append(_("No reward is given for an order settled with store credits."))
            elif order.gamma_bill_id:
                lines.append(_("Reward collected") if order.gamma_bill_status == 'Claimed'
                             else _("Waiting for the customer to collect the reward"))
                lines.append(_("Bill: %s", order.gamma_bill_id))
                qr = order.gamma_qr_url
            elif order.gamma_error:
                lines.append(order.gamma_error)
            elif not order.website_id:
                lines.append(_("Not a shop order: Gamma Wallet rewards are given for orders from the website."))
            elif not gamma_api.reward_service_active(order.env):
                lines.append(_("No reward: your business has no Reward service active in Gamma."))
            elif not order._gamma_may_earn():
                lines.append(_("This order earns no reward (its payment method does not earn one)."))
            elif order._gamma_provider()._gamma_is_pay_later():
                lines.append(_("Paid later: when you confirm the order (the money is in), the reward QR code "
                               "is created and the customer receives it by email."))
            else:
                lines.append(_("Not sent to Gamma Wallet yet. It is sent when the order is confirmed."))
            html = ''.join('<p class="mb-1">%s</p>' % Markup.escape(line) for line in lines)
            if qr:
                html += '<p><img src="%s" width="140" height="140" alt=""/></p>' % Markup.escape(qr)
            order.gamma_summary = Markup(html)
