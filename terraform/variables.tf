variable "project_id" {
  type        = string
  description = "The GCP Project ID to provision resources in."
}

variable "region" {
  type        = string
  description = "The region for provisioning resources (especially user-managed secrets replication)."
  default     = "us-central1"
}
