import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def get_secret(secret_id: str) -> Optional[str]:
    """Fetches a secret from Google Cloud Secret Manager if configured.
    
    Requires GCP_PROJECT_ID or GOOGLE_CLOUD_PROJECT to be set in env.
    If the library is not installed or config is missing, returns None.
    """
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        logger.debug("GCP_PROJECT_ID / GOOGLE_CLOUD_PROJECT not set. Skipping Secret Manager.")
        return None
        
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        logger.info(f"Attempting to fetch secret {secret_id} from GCP project {project_id}...")
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except ImportError:
        logger.warning("google-cloud-secret-manager not installed. Cannot fetch secrets from GCP.")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch secret {secret_id} from Secret Manager: {e}")
        return None
