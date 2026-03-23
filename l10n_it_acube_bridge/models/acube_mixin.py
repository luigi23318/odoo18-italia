import requests
import logging
import json
from datetime import datetime, timedelta

from odoo import models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
TOKEN_REFRESH_MARGIN_MINUTES = 5
TOKEN_ESTIMATED_LIFETIME_HOURS = 2

SANDBOX_URLS = {
    'common': 'https://common-sandbox.api.acubeapi.com',
    'api': 'https://api-sandbox.acubeapi.com',
    'ob': 'https://ob-sandbox.api.acubeapi.com',
}
PRODUCTION_URLS = {
    'common': 'https://common.api.acubeapi.com',
    'api': 'https://api.acubeapi.com',
    'ob': 'https://ob.api.acubeapi.com',
}


class AcubeMixin(models.AbstractModel):
    _name = 'acube.mixin'
    _description = 'A-Cube API - Client HTTP con autenticazione JWT'

    def _acube_get_urls(self):
        ICP = self.env['ir.config_parameter'].sudo()
        env = ICP.get_param('acube.environment', 'sandbox')
        if env == 'production':
            return PRODUCTION_URLS
        return SANDBOX_URLS

    def _acube_login(self):
        ICP = self.env['ir.config_parameter'].sudo()
        urls = self._acube_get_urls()
        email = ICP.get_param('acube.email', '')
        password = ICP.get_param('acube.password', '')

        if not email or not password:
            raise UserError(_(
                "Credenziali A-Cube non configurate.\n"
                "Vai in Impostazioni → Contabilità → A-Cube Bridge."
            ))

        login_url = f"{urls['common']}/login"
        _logger.info("A-Cube login: %s → %s", email, login_url)

        try:
            response = requests.post(
                login_url,
                json={"email": email, "password": password},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise UserError(_("Impossibile connettersi ad A-Cube. Verifica la connessione internet."))
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                raise UserError(_("Credenziali A-Cube errate. Verifica email e password."))
            raise UserError(_("Errore autenticazione A-Cube: %s") % str(e))

        data = response.json()
        token = data.get('token', '')
        if not token:
            raise UserError(_("A-Cube ha risposto senza token. Risposta: %s") % json.dumps(data))

        expiry = datetime.now() + timedelta(hours=TOKEN_ESTIMATED_LIFETIME_HOURS)
        ICP.set_param('acube.token', token)
        ICP.set_param('acube.token_expiry', expiry.isoformat())
        _logger.info("A-Cube: login riuscito, token scade alle %s", expiry.isoformat())
        return token

    def _acube_get_token(self):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('acube.token', '')
        expiry_str = ICP.get_param('acube.token_expiry', '')

        if token and expiry_str:
            try:
                expiry = datetime.fromisoformat(expiry_str)
                if datetime.now() < (expiry - timedelta(minutes=TOKEN_REFRESH_MARGIN_MINUTES)):
                    return token
            except (ValueError, TypeError):
                pass
        return self._acube_login()

    def _acube_request(self, method, path, retry_on_401=True, **kwargs):
        urls = self._acube_get_urls()
        token = self._acube_get_token()

        url = path if path.startswith('http') else f"{urls['api']}{path}"

        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f'Bearer {token}'
        kwargs['headers'] = headers
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)

        _logger.debug("A-Cube %s %s", method.upper(), url)

        try:
            response = requests.request(method.upper(), url, **kwargs)
        except requests.exceptions.ConnectionError:
            raise UserError(_("Impossibile connettersi ad A-Cube (%s).") % url)
        except requests.exceptions.Timeout:
            raise UserError(_("Timeout nella chiamata ad A-Cube (%s).") % url)

        if response.status_code == 401 and retry_on_401:
            _logger.info("A-Cube: token rifiutato (401), rinnovo...")
            self._acube_login()
            return self._acube_request(method, path, retry_on_401=False, **kwargs)

        if not response.ok:
            _logger.error("A-Cube errore %s %s → %s: %s", method, url, response.status_code, response.text[:500])

        response.raise_for_status()
        return response
