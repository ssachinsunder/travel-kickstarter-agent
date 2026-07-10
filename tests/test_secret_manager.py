import os
import sys
import pytest
from unittest.mock import MagicMock
from src.secret_manager import get_secret

def test_get_secret_no_project(monkeypatch):
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    
    assert get_secret("my-secret") is None

def test_get_secret_not_installed(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    
    # To simulate not installed, we can force ImportError on import
    # Python's import system will raise ImportError if the value in sys.modules is None
    # or if we raise it in a custom finder.
    # Setting it to None in sys.modules is the standard way to block imports.
    # But wait, `from google.cloud import secretmanager` will first try to import `google.cloud`.
    # If `google` or `google.cloud` is not installed, it will fail anyway.
    # In this environment, `google` package might exist (due to google-genai or adk).
    # Indeed, `AttributeError: module 'google' has no attribute 'cloud'` suggests `google` exists but `google.cloud` does not.
    # So if we want to force failure, we can block `google.cloud.secretmanager`.
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", None)
    
    assert get_secret("gemini-api-key") is None

def test_get_secret_mock_installed_success(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.payload.data = b"secret-value-123"
    mock_client.access_secret_version.return_value = mock_response
    
    mock_module = MagicMock()
    mock_module.SecretManagerServiceClient.return_value = mock_client
    
    # We need to simulate:
    # from google.cloud import secretmanager
    # This means:
    # 1. sys.modules['google.cloud'] must exist
    # 2. sys.modules['google.cloud'].secretmanager must be our mock_module
    # OR
    # 1. sys.modules['google.cloud.secretmanager'] must exist and be our mock_module
    # and sys.modules['google.cloud'] must have attribute 'secretmanager' that is mock_module.
    
    # Let's create a mock google.cloud module
    mock_google_cloud = MagicMock()
    mock_google_cloud.secretmanager = mock_module
    
    monkeypatch.setitem(sys.modules, "google.cloud", mock_google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", mock_module)
    
    val = get_secret("gemini-api-key")
    assert val == "secret-value-123"
    
    mock_client.access_secret_version.assert_called_once_with(
        request={"name": "projects/test-project/secrets/gemini-api-key/versions/latest"}
    )

def test_get_secret_mock_installed_failure(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    
    mock_client = MagicMock()
    mock_client.access_secret_version.side_effect = Exception("API Error")
    
    mock_module = MagicMock()
    mock_module.SecretManagerServiceClient.return_value = mock_client
    
    mock_google_cloud = MagicMock()
    mock_google_cloud.secretmanager = mock_module
    
    monkeypatch.setitem(sys.modules, "google.cloud", mock_google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", mock_module)
    
    assert get_secret("gemini-api-key") is None
