import requests
import logging
import json
from datetime import datetime, timedelta

from odoo import models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Timeout default per le chiamate HTTP
REQUEST_TIMEOUT = 30
# Margine prima della scadenza del token per forzare il rinnovo
TOKEN_REFRESH_MARGIN_MINUTES = 5
# Durata stimata del token (A-Cube non restituisce scadenza esplicita)
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

    # -------------------------------------------------------------------------
    # URL helpers
    # -------------------------------------------------------------------------

    def _acube_get_urls(self):
        """Restituisce il dizionario URL per l'ambiente configurato."""
        ICP = self.env['ir.config_parameter'].sudo()
        env = ICP.get_param('acube.environment', 'sandbox')
        if env == 'production':
            return PRODUCTION_URLS
        return SANDBOX_URLS

    # -------------------------------------------------------------------------
    # Autenticazione
    # -------------------------------------------------------------------------

    def _acube_login(self):
        """Esegue login con email/password e restituisce il token JWT.

        Salva token e scadenza stimata in ir.config_parameter.
        Solleva UserError se le credenziali non sono configurate o il login fallisce.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        urls = self._acube_get_urls()
        email = ICP.get_param('acube.email', '')
        password = ICP.get_param('acube.password', '')

        if not email or not password:
            raise UserError(_(
                "Credenziali A-Cube non configurate.\n"
                "Vai in Impostazioni → Contabilità → A-Cube Bridge "
                "e inserisci email e password."
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
            raise UserError(_(
                "Impossibile connettersi ad A-Cube.\n"
                "Verifica la connessione internet e che l'URL %s sia raggiungibile."
            ) % login_url)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                raise UserError(_(
                    "Credenziali A-Cube errate.\n"
                    "Verifica email e password nelle impostazioni."
                ))
            raise UserError(_(
                "Errore di autenticazione A-Cube: %s"
            ) % str(e))

        data = response.json()
        token = data.get('token', '')
        if not token:
            raise UserError(_("A-Cube ha risposto senza token. Risposta: %s") % json.dumps(data))

        # Salva token e scadenza stimata
        expiry = datetime.now() + timedelta(hours=TOKEN_ESTIMATED_LIFETIME_HOURS)
        ICP.set_param('acube.token', token)
        ICP.set_param('acube.token_expiry', expiry.isoformat())

        _logger.info("A-Cube: login riuscito, token scade (stimato) alle %s", expiry.isoformat())
        return token

    def _acube_get_token(self):
        """Restituisce un token JWT valido, effettuando login se necessario."""
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('acube.token', '')
        expiry_str = ICP.get_param('acube.token_expiry', '')

        if token and expiry_str:
            try:
                expiry = datetime.fromisoformat(expiry_str)
                margin = timedelta(minutes=TOKEN_REFRESH_MARGIN_MINUTES)
                if datetime.now() < (expiry - margin):
                    return token
            except (ValueError, TypeError):
                pass

        # Token assente, scaduto o invalido → login
        return self._acube_login()

    # -------------------------------------------------------------------------
    # Client HTTP generico
    # -------------------------------------------------------------------------

    def _acube_request(self, method, path, retry_on_401=True, **kwargs):
        """Esegue una chiamata HTTP autenticata verso le API A-Cube.

        Args:
            method: 'GET', 'POST', 'PUT', 'DELETE'
            path: percorso relativo (es. '/invoice-extract') o URL assoluto
            retry_on_401: se True, in caso di 401 rinnova il token e riprova
            **kwargs: passati direttamente a requests.request()
                      (json, data, files, headers, params, timeout, ecc.)

        Returns:
            requests.Response

        Raises:
            UserError: per errori di connessione o autenticazione
            requests.HTTPError: per errori HTTP diversi da 401
        """
        urls = self._acube_get_urls()
        token = self._acube_get_token()

        # URL completo
        if path.startswith('http'):
            url = path
        else:
            url = f"{urls['api']}{path}"

        # Headers con token
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f'Bearer {token}'
        kwargs['headers'] = headers
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)

        _logger.debug("A-Cube %s %s", method.upper(), url)

        try:
            response = requests.request(method.upper(), url, **kwargs)
        except requests.exceptions.ConnectionError:
            raise UserError(_(
                "Impossibile connettersi ad A-Cube (%s).\n"
                "Verifica la connessione internet."
            ) % url)
        except requests.exceptions.Timeout:
            raise UserError(_(
                "Timeout nella chiamata ad A-Cube (%s).\n"
                "Il server potrebbe essere sovraccarico, riprova tra qualche minuto."
            ) % url)

        # Token scaduto → rinnova e riprova (una sola volta)
        if response.status_code == 401 and retry_on_401:
            _logger.info("A-Cube: token rifiutato (401), rinnovo in corso...")
            self._acube_login()
            return self._acube_request(method, path, retry_on_401=False, **kwargs)

        # Log errori
        if not response.ok:
            _logger.error(
                "A-Cube errore %s %s → HTTP %s: %s",
                method.upper(), url, response.status_code,
                response.text[:500]
            )

        response.raise_for_status()
        return response
