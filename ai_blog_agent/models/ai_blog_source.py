import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import requests
from odoo import models, fields


class AiBlogSource(models.Model):
    _name = 'ai.blog.source'
    _description = 'AI Blog News Source'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Source Name', required=True)
    source_type = fields.Selection([
        ('rss', 'RSS Feed'),
        ('rest_api', 'REST API'),
    ], string='Type', required=True, default='rss')
    url = fields.Char(
        string='URL',
        required=True,
        help='Use {keyword} and {language} as placeholders.\n'
             'e.g. https://news.google.com/rss/search?q={keyword}&hl={language}',
    )
    api_key = fields.Char(string='API Key')
    request_headers = fields.Text(
        string='Request Headers',
        help='JSON template for REST API. Use {api_key} as placeholder.\n'
             'e.g. {"Authorization": "Bearer {api_key}"}',
    )
    response_path = fields.Char(
        string='Articles Path',
        help='Dot-notation path to the articles list in the JSON response.\n'
             'e.g. "articles" for NewsAPI',
    )
    title_path = fields.Char(
        string='Title Path',
        help='Dot-notation path to the title within each article.\n'
             'e.g. "title"',
    )
    source_name_path = fields.Char(
        string='Source Name Path',
        help='Dot-notation path to the source name within each article.\n'
             'e.g. "source.name" for NewsAPI',
    )
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')

    def fetch_articles(self, keywords, language):
        """Dispatches article fetching to the appropriate method based on source type."""
        self.ensure_one()
        articles = []
        if self.source_type == 'rss':
            for keyword in keywords:
                try:
                    articles.extend(self._fetch_rss(keyword, language))
                except Exception:
                    pass
        elif self.source_type == 'rest_api':
            try:
                articles.extend(self._fetch_rest_api(keywords, language))
            except Exception:
                pass
        return articles

    def _fetch_rss(self, keyword, language):
        """Fetches and parses an RSS feed, returning article title/source pairs."""
        url = self.url
        url = url.replace('{keyword}', urllib.parse.quote(keyword))
        url = url.replace('{language}', language or 'en')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        articles = []
        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            source = (item.findtext('source') or self.name).strip()
            if title:
                articles.append({'title': title, 'source': source})
        return articles

    def _fetch_rest_api(self, keywords, language):
        """Calls a REST API with all domain keywords and extracts articles via configured paths."""
        keyword_str = ' '.join(keywords)
        url = self.url
        url = url.replace('{keyword}', urllib.parse.quote(keyword_str))
        url = url.replace('{language}', language or 'en')
        if self.api_key:
            url = url.replace('{api_key}', self.api_key)

        headers = {}
        if self.request_headers:
            headers_str = self.request_headers
            if self.api_key:
                headers_str = headers_str.replace('{api_key}', self.api_key)
            try:
                headers = json.loads(headers_str)
            except json.JSONDecodeError:
                pass

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        articles_list = self._extract_by_path(data, self.response_path) if self.response_path else data
        articles = []
        for article in (articles_list or []):
            title = self._extract_by_path(article, self.title_path) if self.title_path else ''
            source = self._extract_by_path(article, self.source_name_path) if self.source_name_path else self.name
            if title:
                articles.append({'title': str(title), 'source': str(source or self.name)})
        return articles

    def _extract_by_path(self, data, path):
        """Traverses a nested dict/list using a dot-notation path."""
        for part in path.split('.'):
            try:
                data = data[int(part)] if isinstance(data, list) else data[part]
            except (KeyError, IndexError, TypeError, ValueError):
                return None
        return data
