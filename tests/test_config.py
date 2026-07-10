import os
import unittest
from unittest import mock
import pytest

# Adjust path to import src
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import Config

class TestConfig(unittest.TestCase):

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_raises_error(self):
        config = Config()
        with pytest.raises(ValueError) as excinfo:
            _ = config.gemini_api_key
        assert "GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set" in str(excinfo.value)

    @mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test_key_gemini"})
    def test_gemini_api_key_loaded(self):
        config = Config()
        assert config.gemini_api_key == "test_key_gemini"

    @mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test_key_google"}, clear=True)
    def test_google_api_key_loaded_fallback(self):
        config = Config()
        assert config.gemini_api_key == "test_key_google"

    @mock.patch.dict(os.environ, {"GOOGLE_GENAI_USE_VERTEXAI": "1"})
    def test_use_vertex_ai_true(self):
        config = Config()
        assert config.use_vertex_ai is True

    @mock.patch.dict(os.environ, {"GOOGLE_GENAI_USE_VERTEXAI": "true"})
    def test_use_vertex_ai_true_string(self):
        config = Config()
        assert config.use_vertex_ai is True

    @mock.patch.dict(os.environ, {"GOOGLE_GENAI_USE_VERTEXAI": "0"})
    def test_use_vertex_ai_false(self):
        config = Config()
        assert config.use_vertex_ai is False

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_use_vertex_ai_default_false(self):
        config = Config()
        assert config.use_vertex_ai is False

if __name__ == "__main__":
    unittest.main()
