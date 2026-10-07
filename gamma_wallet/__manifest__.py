{
    'name': 'Gamma Wallet',
    'version': '18.0.1.1.0',
    'category': 'Website/eCommerce',
    'summary': 'Rewards for paid orders and store credits at checkout, with the Gamma Wallet app.',
    'author': 'Gamma Wallet',
    'website': 'https://www.gamma-wallet.com/en',
    'support': 'developer@gamma-wallet.com',
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
    'images': [
        'static/description/banner.png',
        'static/description/screenshot-confirmation-reward.png',
        'static/description/screenshot-confirmation-credits.png',
        'static/description/screenshot-settings.png',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'license': 'LGPL-3',
}
