"""Validated canonical site origin and optional GitHub Pages custom domain."""
import os
import re
from urllib.parse import urlsplit

DEFAULT_SITE_URL = 'https://mksddn.github.io/philoloom/'


def site_settings(env=None):
    options = os.environ if env is None else env
    site = (options.get('PHILOLOOM_SITE_URL') or DEFAULT_SITE_URL).strip().rstrip('/') + '/'
    parsed = urlsplit(site)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or
            '//' in parsed.path or '\\' in site):
        raise ValueError('PHILOLOOM_SITE_URL must be a valid HTTPS origin/path')
    cname = (options.get('PHILOLOOM_CNAME') or '').strip().lower()
    if cname:
        if (not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}', cname)
                or parsed.hostname != cname or parsed.path != '/' or parsed.port):
            raise ValueError('PHILOLOOM_CNAME must match a root HTTPS canonical domain')
    return site, cname
