# APIs the apps depend on. disable_on_destroy=false so `terraform destroy` never
# switches off an API that other things in this project use.
locals {
  apis = [
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "firebase.googleapis.com",
    "firestore.googleapis.com",
    "firebaserules.googleapis.com",
    "identitytoolkit.googleapis.com",
    "securetoken.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_firebase_project" "default" {
  provider = google-beta
  project  = var.project_id

  depends_on = [google_project_service.apis]
}

# The mobile companion. Its package+SHA-1 can only be registered in one project, so remove it
# from StudyDeck's old project before applying (see README).
resource "google_firebase_android_app" "studydeck" {
  provider        = google-beta
  project         = var.project_id
  display_name    = "StudyDeck"
  package_name    = var.android_package_name
  sha1_hashes     = var.android_sha1_hashes
  deletion_policy = "DELETE"

  depends_on = [google_firebase_project.default]
}

# The local web app uses this only to sign in with Google; the backend then syncs over REST.
resource "google_firebase_web_app" "mequizme" {
  provider        = google-beta
  project         = var.project_id
  display_name    = "mequizme"
  deletion_policy = "DELETE"

  depends_on = [google_firebase_project.default]
}

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  # Guard against an accidental destroy wiping every user's synced progress.
  deletion_policy = "ABANDON"

  depends_on = [google_project_service.apis]
}

resource "google_firebaserules_ruleset" "firestore" {
  project = var.project_id

  source {
    files {
      name    = "firestore.rules"
      content = file("${path.module}/firestore.rules")
    }
  }

  depends_on = [google_firestore_database.default]
}

resource "google_firebaserules_release" "firestore" {
  project      = var.project_id
  name         = "cloud.firestore"
  ruleset_name = google_firebaserules_ruleset.firestore.name

  lifecycle {
    replace_triggered_by = [google_firebaserules_ruleset.firestore]
  }
}
