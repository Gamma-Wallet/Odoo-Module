from . import controllers
from . import models

from odoo.addons.payment import setup_provider, reset_payment_provider


def post_init_hook(env):
    setup_provider(env, 'gamma_wallet')
    params = env['ir.config_parameter'].sudo()
    params.set_param('gamma_wallet.rewards', 'True')
    params.set_param('gamma_wallet.reward_email', 'True')
    # Paid-later providers (wire transfer, pay on site) earn no reward until the shop ticks them.
    env['payment.provider'].sudo().search([('code', 'in', ('custom', 'gamma_wallet'))]).gamma_earns_reward = False


def uninstall_hook(env):
    reset_payment_provider(env, 'gamma_wallet')
