"""Error paths log the error itself: the decompiled ``except`` blocks logged ``None`` instead."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.config import Config
from app.services.vision import VisionService

FRAME = np.zeros((120, 160, 3), np.uint8)


class TemplateReaderErrorTests(unittest.TestCase):
    def test_a_failing_read_logs_its_error_and_reports_a_miss(self):
        reads = (('find_template', lambda: VisionService.find_template(FRAME, 'build.png'), (None, None)),
                 ('find_template_with_confidence', lambda: VisionService.find_template_with_confidence(FRAME, 'build.png'), (None, None, 0)))
        for (name, read, miss) in reads:
            with self.subTest(name):
                with patch('app.services.vision.get_template_path', side_effect=RuntimeError('disk gone')), \
                        self.assertLogs('VisionService', 'ERROR') as logs:
                    self.assertEqual(read(), miss)
                self.assertIn(f'Error in {name}: disk gone', logs.output[0])

    def test_a_failing_multi_match_logs_its_error(self):
        with patch('app.services.vision.get_template_path', side_effect=RuntimeError('disk gone')), \
                self.assertLogs('VisionService', 'ERROR') as logs:
            self.assertIsNone(VisionService._find_template_matches(FRAME, 'build.png', 0.8))
        self.assertIn('Error in _find_template_matches (build.png): disk gone', logs.output[0])


class ConfigLoadErrorTests(unittest.TestCase):
    def load_from(self, path):
        config = Config()
        with patch('app.config.get_resource_path', return_value=path), self.assertLogs('Config', 'ERROR') as logs:
            with self.assertRaises(Exception) as raised:
                config.load_config()
        return raised.exception, logs.output

    def test_a_missing_data_json_is_logged_once_and_raised(self):
        with tempfile.TemporaryDirectory() as d:
            (error, output) = self.load_from(Path(d) / 'data.json')
        self.assertIsInstance(error, FileNotFoundError)
        self.assertEqual(len(output), 1)
        self.assertIn('data.json not found for aspect', output[0])

    def test_an_invalid_data_json_is_logged_and_raised(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'data.json'
            path.write_text('{"left": [1, 2', encoding='utf-8')
            (error, output) = self.load_from(path)
        self.assertIsInstance(error, json.JSONDecodeError)
        self.assertEqual(len(output), 1)
        self.assertIn('data.json is invalid JSON', output[0])

    def test_any_other_error_is_logged_with_its_message_and_raised(self):
        config = Config()
        with patch('app.config.get_resource_path', side_effect=PermissionError('locked')), \
                self.assertLogs('Config', 'ERROR') as logs, self.assertRaises(PermissionError):
            config.load_config()
        self.assertEqual(logs.output, ['ERROR:Config:Error loading config: locked'])


if __name__ == '__main__':
    unittest.main()
