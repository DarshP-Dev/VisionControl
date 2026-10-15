"""Model setup checks without network access."""

from contextlib import redirect_stdout
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from . import download_model as setup


class ModelSetupTest(unittest.TestCase):
    def test_download_verification_and_existing_model_preservation(self):
        content = b"test bundle"
        response = MagicMock()
        response.__enter__.return_value.read.return_value = content
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(setup, "MODEL_SHA256", hashlib.sha256(content).hexdigest()), \
                patch.object(setup.urllib.request, "urlopen", return_value=response) as download, \
                redirect_stdout(io.StringIO()):
            destination = Path(directory) / "models" / "model.task"
            setup.download_model(destination)
            setup.download_model(destination)
            download.assert_called_once_with(setup.MODEL_URL, timeout=60)
            self.assertEqual(destination.read_bytes(), content)
            destination.write_bytes(b"corrupt file")
            with self.assertRaisesRegex(ValueError, "checksum"):
                setup.download_model(destination)
            self.assertEqual(destination.read_bytes(), b"corrupt file")

    def test_invalid_download_does_not_save_model(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"not a valid model"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(setup.urllib.request, "urlopen", return_value=response):
            destination = Path(directory) / "model.task"
            with self.assertRaisesRegex(ValueError, "checksum"):
                setup.download_model(destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
