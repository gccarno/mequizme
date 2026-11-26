# One Sentry project per client. default_rules creates Sentry's standard
# "notify on new issue" alert for each.
locals {
  sentry_projects = {
    backend = { name = "mequizme-backend", platform = "python-fastapi" }
    web     = { name = "mequizme-web", platform = "javascript-react" }
    android = { name = "studydeck-android", platform = "android" }
  }
}

resource "sentry_project" "this" {
  for_each      = local.sentry_projects
  organization  = var.sentry_org
  teams         = [var.sentry_team]
  name          = each.value.name
  slug          = each.value.name
  platform      = each.value.platform
  default_rules = true
}

data "sentry_key" "this" {
  for_each     = sentry_project.this
  organization = var.sentry_org
  project      = each.value.slug
  first        = true
}
