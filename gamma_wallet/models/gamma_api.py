"""Gamma Wallet for Odoo — the calls to the Gamma Integration API.

Every call carries the shop's integration token (GWINT_…) and runs on the Odoo server, never in the
customer's browser. Gamma answers in an envelope {version, statusCode, message, result, error}; this
module returns `result` or raises GammaApiError.
"""

import hashlib
import json
import logging
import time

import requests

from odoo.tools import config

_logger = logging.getLogger(__name__)

# Can be overridden for testing with `gamma_wallet_api_url = https://…` in the Odoo configuration file.
DEFAULT_URL = 'https://integration.gamma-wallet.com'
VERSION = '18.0.1.1.0'

PARAM_TOKEN = 'gamma_wallet.token'
PARAM_REWARDS = 'gamma_wallet.rewards'
PARAM_REWARD_EMAIL = 'gamma_wallet.reward_email'
PARAM_CONNECTION = 'gamma_wallet.connection'
# When the module was installed: orders placed before it never earn a reward.
PARAM_INSTALLED_ON = 'gamma_wallet.installed_on'

# How long a connection check is trusted before Gamma is asked again.
STALE_SECONDS = 3600


class GammaApiError(Exception):
    """Gamma refused the call, or could not be reached (status 0)."""

    def __init__(self, status, identifier=None, error_name=None):
        self.status = int(status)
        self.identifier = identifier
        self.error_name = error_name
        super().__init__('Gamma answered HTTP %d: %s%s' % (
            self.status, error_name or 'no details', ' (%s)' % identifier if identifier else ''))

    def is_retryable(self):
        """Worth trying again later: Gamma unreachable, busy or failing."""
        return self.status == 0 or self.status == 429 or self.status >= 500


def base_url():
    return (config.get('gamma_wallet_api_url') or DEFAULT_URL).rstrip('/')


class GammaApi:

    def __init__(self, token):
        self.token = token

    @classmethod
    def from_env(cls, env):
        """The API for the saved token, or None when the shop is not connected."""
        token = (env['ir.config_parameter'].sudo().get_param(PARAM_TOKEN) or '').strip()
        return cls(token) if token else None

    def connection(self, timeout=20):
        """Who the token belongs to: business, currency, whether customers can claim, token expiry."""
        return self._send('GET', '/api/Connection/Me', timeout=timeout)

    def create_bill(self, bill):
        """Declares a paid order. Safe to repeat with the same reference: Gamma returns the same bill."""
        return self._send('POST', '/api/Bill/Create', bill)

    def get_bill(self, bill_id):
        return self._send('GET', '/api/Bill/Get/%s' % requests.utils.quote(bill_id, safe=''))

    def start_credit(self, order):
        """A new store-credit request for the whole order."""
        return self._send('POST', '/api/Credit/Start', order)

    def check_credit(self, credit_request):
        """Waiting, Paid or Expired, with the seconds left."""
        return self._send('POST', '/api/Credit/Check', {'creditRequest': credit_request})

    def _send(self, method, path, body=None, timeout=20):
        headers = {
            'Authorization': 'Bearer %s' % self.token,
            'Accept': 'application/json',
            'User-Agent': 'gamma-wallet-odoo/%s' % VERSION,
        }
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            # Python writes 0.8 as 0.8; amounts are rounded to cents before they get here.
            data = json.dumps(body)
        try:
            response = requests.request(method, base_url() + path, headers=headers, data=data, timeout=timeout)
        except requests.RequestException as e:
            raise GammaApiError(0, None, 'Gamma could not be reached: %s' % e) from e
        try:
            envelope = response.json()
        except ValueError:
            envelope = {}
        if 200 <= response.status_code < 300 and isinstance(envelope.get('result'), dict):
            return envelope['result']
        error = envelope.get('error') if isinstance(envelope.get('error'), dict) else {}
        raise GammaApiError(response.status_code, error.get('identifier'), error.get('message'))


def explain(env, error):
    """A sentence the shop owner can act on, in their language."""
    _ = env._
    texts = {
        '0388': _("Gamma does not recognise this token. Copy it again from Gamma Business → Integrations."),
        '0389': _("This token was disabled or replaced. Create a new one in Gamma Business → Integrations."),
        '0390': _("This token has expired. Create a new one in Gamma Business → Integrations."),
        '0393': _("The business this token belongs to is not available in Gamma."),
    }
    if error.identifier in texts:
        return texts[error.identifier]
    if error.status == 0:
        return _("Gamma could not be reached. Check that this server can make outgoing HTTPS connections.")
    if error.status == 429:
        return _("Too many requests to Gamma. Try again in a minute.")
    return str(error)


def install_tag(env):
    """Eight characters that tell this database apart from any other one using the same Gamma business
    (a staging copy, a second shop). Odoo gives a duplicated database a new uuid, so a copy gets its
    own tag; reinstalling the module in the same database keeps it."""
    uuid = env['ir.config_parameter'].sudo().get_param('database.uuid') or env.cr.dbname
    return hashlib.sha256(uuid.encode()).hexdigest()[:8]


def reference(env, order_name):
    """The order's reference at Gamma: unique across databases, the same every time for one order."""
    return 'OD-%s-%s' % (install_tag(env), order_name)


def installed_on(env):
    """When the module was installed, as a datetime, or None when unknown."""
    from odoo import fields  # noqa: local import keeps this module importable without the ORM
    value = env['ir.config_parameter'].sudo().get_param(PARAM_INSTALLED_ON)
    return fields.Datetime.to_datetime(value) if value else None


# A reward page asks every 5 seconds; Gamma is asked at most this often per order and server process.
STATUS_CACHE_SECONDS = 20
_status_cache = {}


def cached_status(key):
    hit = _status_cache.get(key)
    return hit[1] if hit and hit[0] > time.time() - STATUS_CACHE_SECONDS else None


def remember_status(key, status):
    if len(_status_cache) > 5000:
        _status_cache.clear()
    _status_cache[key] = (time.time(), status)


def masked(token):
    """"GWINT_Ab12Cd3…x9Yz": enough to recognise a token, never enough to use it."""
    return token[:13] + '…' + token[-4:] if len(token) > 17 else '…'


# ---------------------------------------------------------------------- the connection, cached

def get_connection(env):
    """What Gamma said the last time the connection was checked, or None."""
    raw = env['ir.config_parameter'].sudo().get_param(PARAM_CONNECTION)
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        value = None
    return value if isinstance(value, dict) else None


def check_connection(env, timeout=20):
    """Asks Gamma who the token belongs to, and keeps the answer."""
    params = env['ir.config_parameter'].sudo()
    api = GammaApi.from_env(env)
    if not api:
        params.set_param(PARAM_CONNECTION, '')
        return None
    try:
        connection = api.connection(timeout=timeout)
        connection['checkedOn'] = int(time.time())
    except GammaApiError as e:
        connection = {'error': explain(env, e), 'checkedOn': int(time.time())}
        # Gamma briefly out of reach: keep what it said last time, so the shop keeps working.
        previous = get_connection(env)
        if e.is_retryable() and previous and 'canClaim' in previous:
            connection['canClaim'] = previous['canClaim']
            if previous.get('currencyCode'):
                connection['currencyCode'] = previous['currencyCode']
    params.set_param(PARAM_CONNECTION, json.dumps(connection))
    return connection


def refresh_if_stale(env, timeout=5):
    """Asks Gamma again when the last answer is over an hour old."""
    if not GammaApi.from_env(env):
        return
    connection = get_connection(env)
    if not connection or int(connection.get('checkedOn') or 0) < time.time() - STALE_SECONDS:
        check_connection(env, timeout=timeout)


def reward_service_active(env):
    """True while the business's active Gamma service is a Reward service: the only kind whose
    rewards customers can collect. The module does nothing for customers otherwise.

    Uses the last connection check: the hourly cron keeps it fresh, so a checkout never waits for
    Gamma. Only when there has never been a check is Gamma asked here."""
    if not GammaApi.from_env(env):
        return False
    if not get_connection(env):
        check_connection(env, timeout=3)
    connection = get_connection(env) or {}
    return bool(connection.get('canClaim'))


def currency_matches(env, currency_code):
    """True when the currency is the business's, or when that cannot be known yet."""
    business = (get_connection(env) or {}).get('currencyCode')
    return not business or business.upper() == (currency_code or '').upper()


def flag(env, param):
    """An on/off setting. Odoo removes a boolean setting when it is switched off, so a missing one is
    off; the install hook switches the defaults on."""
    return env['ir.config_parameter'].sudo().get_param(param) in ('True', 'true', '1')
