import logging

from odoo import _, fields, models
from odoo.exceptions import ValidationError

from . import gamma_api

_logger = logging.getLogger(__name__)

PROCESS_URL = '/payment/gamma_wallet/process'


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # The current store-credit request: the QR code the customer scans, valid for a short time.
    gamma_credit_request = fields.Text(readonly=True, copy=False)
    gamma_request_id = fields.Char(string="Gamma request", readonly=True, copy=False)
    gamma_expires_on = fields.Char(readonly=True, copy=False)
    gamma_credit_link = fields.Char(readonly=True, copy=False)
    gamma_credit_qr = fields.Text(readonly=True, copy=False)

    # ------------------------------------------------------------------ the checkout

    def _get_specific_rendering_values(self, processing_values):
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'gamma_wallet':
            return res
        return {'api_url': PROCESS_URL, 'reference': self.reference}

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'gamma_wallet' or len(tx) == 1:
            return tx
        reference = notification_data.get('reference')
        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'gamma_wallet')])
        if not tx:
            raise ValidationError(_("Gamma Wallet: no transaction found matching reference %s.", reference))
        return tx

    def _process_notification_data(self, notification_data):
        """ The customer placed the order: ask Gamma for a QR code and wait for the credits.

        Runs once per transaction. The route is public and the reference is guessable, so a second
        post (a replay, a double submit) must not replace the code the customer is about to scan. """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'gamma_wallet':
            return
        self._gamma_lock()
        if self.state != 'draft' or self.gamma_credit_request:
            return
        try:
            self._gamma_start_request()
        except gamma_api.GammaApiError as e:
            # The order page then offers a new code; the transaction stays pending.
            _logger.warning("Gamma Wallet: store-credit request for %s failed: %s", self.reference, e)
        self._set_pending()

    def _gamma_order(self):
        return self.sale_order_ids[:1]

    def _gamma_lock(self):
        """ Holds this transaction's row until the end of the request, so two requests for the same
        order (two tabs, a double click) run one after the other and the second sees what the first did. """
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    def _gamma_start_request(self):
        """ Asks Gamma for a new store-credit request for the whole order, and keeps it. """
        self.ensure_one()
        api = gamma_api.GammaApi.from_env(self.env)
        if not api:
            raise gamma_api.GammaApiError(401, '0392', 'IntegrationTokenMissing')
        order = self._gamma_order()
        # Store credits settle the whole order or nothing: never a down payment or a remainder.
        if not order or self.currency_id.compare_amounts(self.amount, order.amount_total) != 0:
            raise gamma_api.GammaApiError(400, None, 'NotTheWholeOrder')
        request = api.start_credit({
            'reference': gamma_api.reference(self.env, order.name),
            'total': self.currency_id.round(self.amount),
            'currencyCode': self.currency_id.name,
        })
        self.write({
            'gamma_credit_request': request['creditRequest'],
            'gamma_request_id': request['requestId'],
            'gamma_expires_on': request['expiresOn'],
            'gamma_credit_link': request['link'],
            'gamma_credit_qr': request.get('qrPngBase64') or '',
        })
        return request

    def _gamma_status(self):
        """ Paid (settled now or before), Waiting with the seconds left, or Expired. """
        self.ensure_one()
        if self.state == 'done':
            return {'status': 'Paid'}
        api = gamma_api.GammaApi.from_env(self.env)
        if not self.gamma_credit_request or not api:
            return {'status': 'Expired'}
        checked = api.check_credit(self.gamma_credit_request)
        if checked['status'] == 'Paid':
            self._gamma_mark_settled(checked)
            return {'status': 'Paid'}
        return {'status': checked['status'], 'secondsLeft': int(checked.get('secondsLeft') or 0)}

    def _gamma_mark_settled(self, checked):
        """ Records a settled request once: the payment is done and the order confirmed. """
        self._gamma_lock()
        if self.state == 'done':
            return
        self.write({'provider_reference': checked.get('requestId') or self.gamma_request_id, 'gamma_credit_qr': ''})
        self._set_done(state_message=_("Settled with the customer's store credits through Gamma Wallet."))
        self._post_process()

    # ------------------------------------------------------------------ rewards for captured payments

    def _post_process(self):
        """ A card payment that was only authorised at checkout earns its reward once it is captured
        (done), even though the order was confirmed earlier. Nothing happens twice: an order keeps
        one bill and one reward email. """
        res = super()._post_process()
        for tx in self.filtered(lambda t: t.state == 'done' and t.provider_code != 'gamma_wallet'):
            orders = tx.sale_order_ids.filtered(lambda o: o.state == 'sale' and o.website_id)
            try:
                orders._gamma_reward_after_confirm()
            except Exception:  # never let a reward problem block a payment
                _logger.exception("Gamma Wallet: reward after payment %s failed", tx.reference)
        return res
