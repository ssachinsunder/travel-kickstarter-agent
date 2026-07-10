terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.0.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable APIs
resource "google_project_service" "secretmanager" {
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "aiplatform" {
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

# Create Secret for API Key
resource "google_secret_manager_secret" "gemini_api_key" {
  depends_on = [google_project_service.secretmanager]
  secret_id  = "gemini-api-key"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}
