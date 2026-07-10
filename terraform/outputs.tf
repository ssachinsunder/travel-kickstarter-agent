output "secret_id" {
  value       = google_secret_manager_secret.gemini_api_key.id
  description = "The ID of the created secret for Gemini API Key."
}
