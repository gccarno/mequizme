output "android_app_id" {
  value = google_firebase_android_app.studydeck.app_id
}

# Sensitive: contains API keys. Write to StudyDeck's app/google-services.json (gitignored):
#   terraform output -raw google_services_json > <studydeck>/app/google-services.json
data "google_firebase_android_app_config" "studydeck" {
  provider = google-beta
  project  = var.project_id
  app_id   = google_firebase_android_app.studydeck.app_id
}

output "google_services_json" {
  value     = base64decode(data.google_firebase_android_app_config.studydeck.config_file_contents)
  sensitive = true
}

data "google_firebase_web_app_config" "mequizme" {
  provider   = google-beta
  project    = var.project_id
  web_app_id = google_firebase_web_app.mequizme.app_id
}

# Firebase web config is not secret (it ships in every web page), but the API key is still
# sensitive-flagged so it doesn't print in plan output. scripts/render_env.py consumes this.
output "firebase_web_config" {
  value = {
    apiKey     = data.google_firebase_web_app_config.mequizme.api_key
    authDomain = data.google_firebase_web_app_config.mequizme.auth_domain
    projectId  = var.project_id
    appId      = google_firebase_web_app.mequizme.app_id
  }
  sensitive = true
}

output "sentry_dsns" {
  value = { for k, v in data.sentry_key.this : k => v.dsn["public"] }
}
