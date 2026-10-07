"""18.0.1.1.0: orders placed before the module was installed earn no reward. Installs from before
this version have no install date yet, so the upgrade moment is used: older orders keep the rewards
they already have, and no new ones are created for them. The reward email also learns to go out in
the customer's language."""

from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    params = env['ir.config_parameter'].sudo()
    if not params.get_param('gamma_wallet.installed_on'):
        params.set_param('gamma_wallet.installed_on', fields.Datetime.to_string(fields.Datetime.now()))
    # The reward email goes out in the customer's language (the template is not updated by itself).
    template = env.ref('gamma_wallet.mail_template_gamma_reward', raise_if_not_found=False)
    if template and not template.lang:
        template.lang = '{{ object.partner_id.lang }}'
