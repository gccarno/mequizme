terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    sentry = {
      source  = "jianyuan/sentry"
      version = "~> 0.14"
    }
  }

  # State is local (infra/terraform.tfstate, gitignored) until a state bucket exists.
  # To move to GCS, add: backend "gcs" { bucket = "<bucket>" prefix = "mequizme" }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# Token from https://sentry.io/settings/account/api/auth-tokens/ (scopes: project:write, team:read, org:read).
# Pass it as TF_VAR_sentry_auth_token so it never lands in a file.
provider "sentry" {
  token = var.sentry_auth_token
}
