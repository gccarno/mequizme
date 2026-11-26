variable "project_id" {
  description = "GCP project for mequizme + StudyDeck (create it first with `gcloud projects create`)."
  type        = string
}

variable "region" {
  type    = string
  default = "us-east4"
}

variable "firestore_location" {
  description = "Firestore location. Immutable once the database exists."
  type        = string
  default     = "us-east4"
}

variable "android_package_name" {
  description = "The companion app is StudyDeck."
  type        = string
  default     = "com.studydeck.app"
}

variable "android_sha1_hashes" {
  description = "Debug/release signing certificate SHA-1s (needed for Google Sign-In). Find with `gradlew signingReport`."
  type        = list(string)
  default     = []
}

variable "sentry_org" {
  description = "Sentry organization slug."
  type        = string
}

variable "sentry_team" {
  description = "Sentry team slug that owns the projects."
  type        = string
}

variable "sentry_auth_token" {
  description = "Sentry API token. Set via TF_VAR_sentry_auth_token."
  type        = string
  sensitive   = true
}
