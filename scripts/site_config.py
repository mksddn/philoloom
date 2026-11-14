"""Single canonical base URL for GitHub Pages and a future custom domain."""
import os
from urllib.parse import urlsplit


DEFAULT_SITE_URL = 'https://mksddn.github.io/philoloom/'


def canonical_base(value=None):
    raw = DEFAULT_SITE_URL if value is None else value
    parsed = urlsplit(raw)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.port is not None or
            '//' in parsed.path or '/./' in parsed.path or '/../' in parsed.path or
            parsed.path.endswith('/..') or parsed.path.endswith('/.')):
        raise ValueError('Canonical URL must be an HTTPS origin with an optional clean path')
    return raw.rstrip('/') + '/'


def configured_site_url():
    return canonical_base(os.environ.get('PHILOLOOM_SITE_URL', DEFAULT_SITE_URL))


def custom_domain(site_url):
    parsed = urlsplit(site_url)
    if parsed.path != '/' or parsed.hostname.endswith('.github.io'):
        return None
    return parsed.hostname
