"""The launch-time check for a newer release: version parsing and comparison, and the
request answered by a fake GitHub (no network in the tests)."""
import io
import json
import unittest

from app.utils import update_check


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_answering(payload):
    def opener(request, timeout):
        opener.request = request
        return FakeResponse(json.dumps(payload).encode('utf-8'))
    return opener


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(update_check.parse_version('v1.0'), (1,))
        self.assertEqual(update_check.parse_version('1.0.0'), (1,))
        self.assertEqual(update_check.parse_version('v1.3.0-beta.2'), (1, 3))
        self.assertEqual(update_check.parse_version('v1.0.2'), (1, 0, 2))
        self.assertIsNone(update_check.parse_version('latest'))

    def test_newer(self):
        self.assertTrue(update_check.is_newer('v1.0.1', '1.0'))
        self.assertTrue(update_check.is_newer('v1.1', '1.0'))
        self.assertFalse(update_check.is_newer('v1.0', '1.0'))
        self.assertFalse(update_check.is_newer('v1.0.0', '1.0'))
        self.assertFalse(update_check.is_newer('v0.9', '1.0'))


class RequestTests(unittest.TestCase):
    def test_a_newer_release_is_reported_with_its_page(self):
        opener = opener_answering({'tag_name': 'v1.1', 'html_url': 'https://github.com/x/y/releases/tag/v1.1'})
        self.assertEqual(update_check.newer_release('1.0', opener=opener), ('v1.1', 'https://github.com/x/y/releases/tag/v1.1'))
        self.assertEqual(opener.request.get_header('User-agent'), 'BasePilot/1.0')  # nothing else about the user
        self.assertEqual(opener.request.full_url, update_check.RELEASES_API)

    def test_the_same_version_is_no_news(self):
        self.assertIsNone(update_check.newer_release('1.0', opener=opener_answering({'tag_name': 'v1.0'})))

    def test_offline_is_no_news(self):
        def offline(request, timeout):
            raise OSError('no network')
        self.assertIsNone(update_check.newer_release('1.0', opener=offline))
        self.assertIsNone(update_check.newer_release('1.0', opener=opener_answering({'message': 'API rate limit exceeded'})))


if __name__ == '__main__':
    unittest.main()
