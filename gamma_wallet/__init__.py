from . import controllers
from . import models

from odoo import fields
from odoo.addons.payment import setup_provider, reset_payment_provider


def post_init_hook(env):
    setup_provider(env, 'gamma_wallet')
    params = env['ir.config_parameter'].sudo()
    params.set_param('gamma_wallet.rewards', 'True')
    params.set_param('gamma_wallet.reward_email', 'True')
    # Orders placed before the module was installed never earn a reward.
    if not params.get_param('gamma_wallet.installed_on'):
        params.set_param('gamma_wallet.installed_on', fields.Datetime.to_string(fields.Datetime.now()))
    # Paid-later providers (wire transfer, pay on site) earn no reward until the shop ticks them.
    env['payment.provider'].sudo().search([('code', 'in', ('custom', 'gamma_wallet'))]).gamma_earns_reward = False


def uninstall_hook(env):
    reset_payment_provider(env, 'gamma_wallet')
    # The token, the last connection check and the on/off settings: nothing of Gamma stays behind.
    env['ir.config_parameter'].sudo().search([('key', '=like', 'gamma_wallet.%')]).unlink()
