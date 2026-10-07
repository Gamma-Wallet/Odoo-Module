# gamma_wallet — developer notes

Odoo 18 module for Gamma Wallet. The shop owners' guide is the README one level up; this file is for whoever changes the code.

## Layout

| Path | What it does |
|---|---|
| `models/gamma_api.py` | Calls to the Gamma Integration API with the shop's `GWINT_` token (`requests`), the cached connection check (refreshed hourly by a cron), the Reward-service and currency checks, the install tag and order references, the short status cache. Settings live in `ir.config_parameter` (`gamma_wallet.*`) |
| `models/payment_provider.py` | Provider code `gamma_wallet`; `gamma_earns_reward` on every provider; the store-credits provider is hidden in `_get_compatible_providers` unless it can work |
| `models/payment_transaction.py` | Store credits: the checkout posts to `/payment/gamma_wallet/process`, the transaction goes pending with a Gamma credit request; `_gamma_status()` asks `Credit/Check` and on Paid calls `_set_done()` + `_post_process()`, which confirms the order |
| `models/sale_order.py` | Rewards: fields on the order, `action_confirm` override (bill + reward email), the retry and connection crons, the "send again" action, the back-office summary, and `_gamma_portal_values()` for the templates |
| `models/res_config_settings.py` | The Gamma Wallet section in Settings |
| `controllers/main.py` | The checkout route, and the status / new-code routes the customer's page polls (protected by the order's `access_token`) |
| `views/` | Checkout form, confirmation and portal boxes, settings, the order tab |
| `static/src/js/gamma_wallet.js` | Polling, countdown, new code (same as the WooCommerce and PrestaShop ones) |
| `static/src/js/post_processing.js` | Makes Odoo's payment status page treat a pending store-credit payment as final, so the customer lands on the confirmation page with the QR code (as `payment_custom` does for wire transfer) |
| `data/` | Payment method and provider, the reward email template, the crons, `neutralize.sql` (removes the token from a neutralized copy) |
| `migrations/` | Upgrade steps between versions |
| `static/description/` | The Apps store page (`index.html`), banner, screenshots and icon |
| `i18n/gamma_wallet.pot` | Translation template; regenerate with `--i18n-export` after changing texts |

## Rules it follows

- **Security:** every method a customer must not call is private (`_gamma_…`; Odoo refuses remote calls to those). `action_gamma_send_reward` checks write access on the order; `action_gamma_check_connection` on the settings. The public routes need the order's `access_token` (compared with `consteq`).
- **One live store-credit code per order:** the checkout post starts a request only for a draft transaction without one (the route is public and the reference guessable, so a replay must not replace the code); new-code and settlement lock the transaction row (`SELECT … FOR UPDATE`).
- **Whole order only:** the provider is offered only with a `sale_order_id` and an amount equal to the order total, and `_gamma_start_request` refuses anything else.
- **References:** `OD-<install tag>-<order name>`; the tag is derived from `database.uuid`, so a duplicated database gets its own and a reinstall keeps it.
- **No rewards for old orders:** only orders whose `date_order` is on or after `gamma_wallet.installed_on` (set at install; at upgrade from 18.0.1.0.0).
- **Paid means done:** a reward needs a done transaction (authorised or pending is not enough); `_post_process` gives it when a later capture completes the payment. Paid-later providers count as paid when the shop confirms the order.

- A reward is created when a **website** order is **confirmed** (`action_confirm`), for providers ticked in the settings, while the business has a Reward service (`canClaim`) and the currencies match. Orders settled with store credits never earn one. Online payments are confirmed by Odoo when the transaction is done; wire transfer and pay-on-site orders when the shop confirms them.
- The reward email (`mail_template_gamma_reward`) is queued once, as OdooBot (the confirmation often runs for the website's public user, who has no sender address), in the customer's language; `gamma_emailed` is set before it is queued. Pay-later orders always get it; for paid-at-checkout orders it follows the *Email the reward* setting. The module does not edit Odoo's own order email.
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

18.0.1.1.0 (security and store review), also in Docker against the live Integration API:

- a customer account calling the module over RPC: no access to other orders (the portal method is private, *send reward* and *check again* refuse);
- replaying the checkout post keeps the live code; partial amounts and payment links don't offer store credits, and a partial transaction is refused before Gamma is asked;
- the bill reference arrives at Gamma as `OD-<tag>-S000xx`; orders older than the install and orders with a pending payment get no reward;
- uninstall removes every `gamma_wallet.*` setting; `neutralize.sql` removes the token and connection; the upgrade from 18.0.1.0.0 sets the install date and the email language;
- the customer's page renders and polls with translated texts and no script errors; pylint-odoo shows only the OCA-author check (not applicable).

Not tested yet: Odoo 19 and 20, Odoo.sh, the Enterprise edition, multi-company and multi-website setups.
