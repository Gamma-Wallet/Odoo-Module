"""Gamma Wallet for Odoo — the shop's own routes.

/payment/gamma_wallet/process   the checkout posts here when the customer chooses store credits
/gamma_wallet/status/<order>    asked every 5 seconds by the customer's page (never Gamma itself)
/gamma_wallet/new_code/<order>  a new store-credit QR code once the old one expired unused

The status routes are protected by the order's access token, like Odoo's own portal pages.
"""

import json
import logging
import time
from datetime import datetime

from odoo.http import Controller, request, route
from odoo.tools import consteq

from ..models import gamma_api
from ..models.payment_transaction import PROCESS_URL

_logger = logging.getLogger(__name__)


def _reply(data, status=200):
    return request.make_response(
        json.dumps(data), status=status,
        headers=[('Content-Type', 'application/json'), ('Cache-Control', 'no-store')])


def _order_from_request(order_id, access_token):
    order = request.env['sale.order'].sudo().browse(int(order_id)).exists()
    if not order or not access_token or not order.access_token or not consteq(order.access_token, access_token):
        return None
    return order


def _expires_at(value):
    """ Gamma's expiresOn ("2026-10-05T10:40:08Z" or with fractions) as a Unix time, or 0. """
    if not value:
        return 0
    text = value.rstrip('Z').split('.')[0]
    try:
        return int((datetime.fromisoformat(text) - datetime(1970, 1, 1)).total_seconds())
    except ValueError:
        return 0


class GammaWalletController(Controller):

    @route(PROCESS_URL, type='http', auth='public', methods=['POST'], csrf=False)
    def gamma_wallet_process(self, **post):
        request.env['payment.transaction'].sudo()._handle_notification_data('gamma_wallet', post)
        return request.redirect('/payment/status')

    @route('/gamma_wallet/status/<int:order_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def gamma_wallet_status(self, order_id, access_token=None, **kwargs):
        order = _order_from_request(order_id, access_token)
        if not order:
            return _reply({'error': 'not_found'}, 404)
        if order._gamma_settled_with_credits():
            tx = order._gamma_transaction()
            try:
                status = tx._gamma_status()
            except gamma_api.GammaApiError:
                return _reply({'kind': 'credit', 'status': 'Unknown'}, 503)
            if status['status'] == 'Paid':
                status['redirect'] = order.get_portal_url()
            return _reply(dict(kind='credit', **status))
        return _reply({'kind': 'reward', 'status': order._gamma_refresh_status()})

    @route('/gamma_wallet/new_code/<int:order_id>', type='http', auth='public', methods=['POST'], csrf=False)
    def gamma_wallet_new_code(self, order_id, access_token=None, **kwargs):
        order = _order_from_request(order_id, access_token)
        if not order or not order._gamma_settled_with_credits():
            return _reply({'error': 'not_found'}, 404)
        tx = order._gamma_transaction()
        # The customer may have settled the current code a moment ago, before the page asked.
        try:
            current = tx._gamma_status()
        except gamma_api.GammaApiError:
            return _reply({'error': 'unavailable'}, 503)
        if current['status'] == 'Paid':
            return _reply({'status': 'Paid', 'redirect': order.get_portal_url()})
        if tx.state != 'pending':
            return _reply({'error': 'not_payable'}, 409)
        # Never two live codes for one order, or the customer could settle it twice. Gamma still
        # accepts a code a few seconds past its time (clock differences), so wait those out too.
        expires = _expires_at(tx.gamma_expires_on)
        if expires and time.time() < expires + 15:
            return _reply({'error': 'still_valid'}, 409)
        try:
            started = tx._gamma_start_request()
        except gamma_api.GammaApiError as e:
            _logger.warning("Gamma Wallet: new store-credit code for %s failed: %s", order.name, e)
            return _reply({'error': 'unavailable'}, 503)
        return _reply({
            'status': 'Waiting',
            'secondsLeft': int(started.get('secondsLeft') or 0),
            'link': started['link'],
            'qr': 'data:image/png;base64,' + (started.get('qrPngBase64') or ''),
        })
