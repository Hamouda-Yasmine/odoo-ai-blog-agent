import json
import logging
import time
import requests
from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiBlogProvider(models.Model):
    _name = 'ai.blog.provider'
    _description = 'AI Provider'
    _rec_name = 'name'
    _order = 'sequence, name'

    name = fields.Char(string='Provider Name', required=True)
    api_url = fields.Char(
        string='API URL',
        required=True,
        help='Full endpoint URL. Use {model} and {api_key} as placeholders if needed.\n'
             'e.g. https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
    )
    api_key = fields.Char(string='API Key')
    model = fields.Char(string='Model', help='Model identifier to use, e.g. gemini-2.0-flash, gpt-4o-mini')
    request_headers = fields.Text(
        string='Request Headers',
        help='JSON template. Use {api_key} as placeholder.\n'
             'e.g. {"Authorization": "Bearer {api_key}", "Content-Type": "application/json"}',
    )
    request_body_template = fields.Text(
        string='Request Body Template',
        help='JSON template. Use {prompt}, {model}, {max_tokens} as placeholders.\n'
             'e.g. {"model": "{model}", "messages": [{"role": "user", "content": "{prompt}"}], "max_tokens": {max_tokens}}',
    )
    response_path = fields.Char(
        string='Response Path',
        required=True,
        help='Dot-notation path to extract the text from the JSON response.\n'
             'e.g.  choices.0.message.content  (OpenAI / DeepSeek)\n'
             '      content.0.text             (Claude)\n'
             '      candidates.0.content.parts.0.text  (Gemini)',
    )
    supports_web_search = fields.Boolean(
        string='Supports Web Search',
        help='Enable if this provider has a built-in web search tool (e.g. Gemini Google Search).',
    )
    search_tool_payload = fields.Text(
        string='Search Tool Payload',
        help='JSON merged into the request body to activate web search.\n'
             'Gemini: {"tools": [{"google_search": {}}]}\n'
             'OpenAI Responses: {"tools": [{"type": "web_search_preview"}]}',
    )
    is_default = fields.Boolean(string='Default Provider')
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    def call(self, prompt, max_tokens=8192, search_payload=None):
        """Sends a prompt to the configured AI endpoint and returns the extracted text response.
        Retries up to 3 times on 5xx errors; raises immediately on 429."""
        self.ensure_one()

        # Build URL — substitute {model} and {api_key}
        url = self.api_url or ''
        url = url.replace('{model}', self.model or '')
        if self.api_key:
            url = url.replace('{api_key}', self.api_key)

        # Build headers
        headers = {'Content-Type': 'application/json'}
        if self.request_headers:
            headers_str = self.request_headers
            if self.api_key:
                headers_str = headers_str.replace('{api_key}', self.api_key)
            try:
                headers = json.loads(headers_str)
            except json.JSONDecodeError as e:
                raise UserError(_('Invalid headers JSON: %s') % str(e))

        # Build body — json.dumps escapes the prompt safely for JSON injection
        body = {}
        if self.request_body_template:
            body_str = self.request_body_template
            body_str = body_str.replace('{model}', self.model or '')
            body_str = body_str.replace('{max_tokens}', str(max_tokens))
            # [1:-1] strips surrounding quotes that json.dumps adds
            body_str = body_str.replace('{prompt}', json.dumps(prompt)[1:-1])
            try:
                body = json.loads(body_str)
            except json.JSONDecodeError as e:
                raise UserError(_('Invalid body template JSON: %s') % str(e))

        # Merge search tool payload when the provider's web search is activated
        if search_payload and isinstance(search_payload, dict):
            body.update(search_payload)

        last_error = None
        for attempt in range(3):
            try:
                response = requests.post(url, headers=headers, json=body, timeout=60)
                if response.status_code == 429:
                    raise UserError(_(
                        'API rate limit reached (429). Please wait a moment and try again.'
                    ))
                if response.status_code in (500, 502, 503, 504) and attempt < 2:
                    wait = 2 ** attempt  # 1s, 2s
                    _logger.warning('AI provider server error (%d), retrying in %ds', response.status_code, wait)
                    time.sleep(wait)
                    last_error = response
                    continue
                response.raise_for_status()
                last_error = None
                break
            except UserError:
                raise
            except requests.exceptions.RequestException as e:
                raise UserError(_('API request failed: %s') % str(e))
        if last_error is not None:
            raise UserError(_(
                'API server error %s after 3 attempts. Please try again in a moment.'
            ) % last_error.status_code)

        if not self.response_path:
            raise UserError(_('Response path is not configured.'))
        return self._extract_by_path(response.json(), self.response_path)

    def _extract_by_path(self, data, path):
        """Traverses a nested dict/list using a dot-notation path (e.g. 'choices.0.message.content')."""
        for part in path.split('.'):
            try:
                data = data[int(part)] if isinstance(data, list) else data[part]
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise UserError(_('Cannot extract response at "%s": %s') % (path, str(e)))
        return data

    def action_test_connection(self):
        """Sends a simple test prompt and displays the result as a toast notification."""
        self.ensure_one()
        try:
            result = self.call('Reply with OK')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': str(result),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Failed'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                },
            }
