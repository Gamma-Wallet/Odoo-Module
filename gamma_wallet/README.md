# gamma_wallet — developer notes

Odoo 18 module for Gamma Wallet. The shop owners' guide is the README one level up; this file is for whoever changes the code.

## Layout

| Path | What it does |
|---|---|
| `models/gamma_api.py` | Calls to the Gamma Integration API with the shop's `GWINT_` token (`requests`), the cached connection check (refreshed hourly), the Reward-service and currency checks. Settings live in `ir.config_parameter` (`gamma_wallet.*`) |
| `models/payment_provider.py` | Provider code `gamma_wallet`; `gamma_earns_reward` on every provider; the store-credits provider is hidden in `_get_compatible_providers` unless it can work |
| `models/payment_transaction.py` | Store credits: the checkout posts to `/payment/gamma_wallet/process`, the transaction goes pending with a Gamma credit request; `_gamma_status()` asks `Credit/Check` and on Paid calls `_set_done()` + `_post_process()`, which confirms the order |
| `models/sale_order.py` | Rewards: fields on the order, `action_confirm` override (bill + reward email), the retry cron, the "send again" action, the back-office summary, and `gamma_portal_values()` for the templates |
| `models/res_config_settings.py` | The Gamma Wallet section in Settings |
| `controllers/main.py` | The checkout route, and the status / new-code routes the customer's page polls (protected by the order's `access_token`) |
| `views/` | Checkout form, confirmation and portal boxes, settings, the order tab |
| `static/src/js/gamma_wallet.js` | Polling, countdown, new code (same as the WooCommerce and PrestaShop ones) |
| `static/src/js/post_processing.js` | Makes Odoo's payment status page treat a pending store-credit payment as final, so the customer lands on the confirmation page with the QR code (as `payment_custom` does for wire transfer) |
| `data/` | Payment method and provider, the reward email template, the retry cron |

## Rules it follows

- A reward is created when a **website** order is **confirmed** (`action_confirm`), for providers ticked in the settings, while the business has a Reward service (`canClaim`) and the currencies match. Orders settled with store credits never earn one. Online payments are confirmed by Odoo when the transaction is done; wire transfer and pay-on-site orders when the shop confirms them.
- The reward email (`mail_template_gamma_reward`) is sent once, as OdooBot (the confirmation often runs for the website's public user, who has no sender address). Pay-later orders always get it; for paid-at-checkout orders it follows the *Email the reward* setting. The module does not edit Odoo's own order email.
- Failed bills are retried by the cron every 10 minutes, up to 6 attempts, and on each view of the customer's page; the order tab's button retries at once.
- Store credits settle the whole order; the transaction's `provider_reference` is Gamma's request id.
- On/off settings: Odoo removes a boolean `ir.config_parameter` when it is switched off, so a missing one means off; the install hook switches the defaults on.
- For testing against another Integration API, set `gamma_wallet_api_url = https://…` in the Odoo configuration file.

## Tested

Odoo 18.0 Community in Docker (`odoo:18.0` + PostgreSQL 16), demo data, a website selling in EUR, against the live Integration API, with a 0.80 EUR total:

- store credits: QR and countdown on the confirmation page; settled through the app's flow; transaction done with the request id and the order confirmed by Odoo;
- new code: refused while the old one is valid, a fresh one after expiry, wrong access token refused;
- rewards for an order paid with the Demo provider: QR on the confirmation page and the customer's order page, reward email with the QR;
- wire transfer: nothing when not ticked; when ticked, a note at checkout, then the reward and the email when the order is confirmed in the back office;
- a failed bill (bad token) recovered by the retry cron, and by the order tab's button;
- the settings section, saving it, and the module switching itself off without a Reward service.

Not tested yet: Odoo 19 and 20, Odoo.sh, the Enterprise edition, multi-company and multi-website setups.
