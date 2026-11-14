"""Domain migration must preserve canonical consistency and safe URL handling."""
import unittest

from scripts.site_config import DEFAULT_SITE_URL, site_settings


class SiteConfigTests(unittest.TestCase):
    def test_default_github_pages_path(self):
        self.assertEqual(site_settings({}), (DEFAULT_SITE_URL, ''))

    def test_custom_domain_requires_consistent_https_and_cname(self):
        settings = {'PHILOLOOM_SITE_URL': 'https://philo.example.org',
                    'PHILOLOOM_CNAME': 'philo.example.org'}
        self.assertEqual(site_settings(settings), ('https://philo.example.org/', 'philo.example.org'))
        for override in (
            {'PHILOLOOM_SITE_URL': 'http://philo.example.org'},
            {'PHILOLOOM_SITE_URL': 'javascript:alert(1)'},
            {'PHILOLOOM_SITE_URL': 'https://philo.example.org/a//b/'},
            {'PHILOLOOM_SITE_URL': 'https://wrong.example.org/', 'PHILOLOOM_CNAME': 'philo.example.org'},
            {'PHILOLOOM_SITE_URL': 'https://philo.example.org/subpath/',
             'PHILOLOOM_CNAME': 'philo.example.org'},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                site_settings(override)


if __name__ == '__main__':
    unittest.main()
