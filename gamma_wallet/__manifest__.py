{
    'name': 'Gamma Wallet',
    'version': '18.0.1.0.0',
    'category': 'Website/Website',
    'summary': 'Rewards for paid orders and store credits at checkout, with the Gamma Wallet app.',
    'description': """
Customers earn a reward for every paid order and can settle an order with the store credits they
hold at the shop, by scanning a QR code with the Gamma Wallet app. Credits are a promise of value
at the business, not money, and Gamma never handles a payment.

Needs a Gamma Business account (https://business.gamma-wallet.com) with a Reward service active
and an integration token.
""",
    'author': 'Gamma Wallet',
    'website': 'https://www.gamma-wallet.com',
    'depends': ['website_sale', 'payment'],
    'data': [
        'views/payment_templates.xml',
        'views/website_templates.xml',
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',  # needs views/payment_templates.xml
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'gamma_wallet/static/src/css/gamma-wallet.css',
            'gamma_wallet/static/src/js/gamma_wallet.js',
            'gamma_wallet/static/src/js/post_processing.js',
        ],
    },
    'images': ['static/description/icon.png'],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
