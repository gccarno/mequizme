# mequizme cloud (GCP + Firebase + Sentry)

One GCP project holds everything the web app and the StudyDeck Android companion share:

- **Firebase Auth** (Google sign-in). Both apps sign in as the same user, so they share a `uid`.
- **Firestore**: all data is under `users/{uid}/`. See `firestore.rules`.
- **Sentry**: three projects (`mequizme-backend`, `mequizme-web`, `studydeck-android`).

| Firestore path | Written by | |
|---|---|---|
| `packs/{packId}`, `packs/{packId}/items/{itemId}` | web | reviewed content, with `contentHash` |
| `reviews/{uuid}` | both | append-only review log, `syncedAt` = server time |
| `srs/{itemId}` | both | schedule. The newer `lastReviewedAt` wins |
| `attempts/{attemptId}` | both | submitted quizzes, create-only |
| `subjects/`, `decks/`, `cards/` | StudyDeck | StudyDeck's own decks |

## First-time setup

1. **Create the project** (Terraform doesn't create it, so it can't destroy it either):
   ```sh
   gcloud projects create <project-id>
   gcloud auth application-default login
   ```
2. **Move StudyDeck out of its old project.** An Android package + SHA-1 can be registered in only one project. In StudyDeck's repo:
   ```sh
   cd <studydeck>/infra && terraform destroy -target=google_firebase_android_app.studydeck
   ```
3. **Apply:**
   ```sh
   cd infra
   export TF_VAR_sentry_auth_token=...      # sentry.io → Settings → Auth Tokens
   terraform init
   terraform apply -var project_id=<project-id> -var sentry_org=<org> -var sentry_team=<team> \
     -var 'android_sha1_hashes=["<debug sha1>","<release sha1>"]'
   ```
   A gitignored `terraform.tfvars` saves retyping these.
4. **Turn on Google sign-in.** This is manual, as it was for StudyDeck: Firebase console → Authentication → Sign-in method → Google → Enable. `localhost` is an authorized domain by default.
5. **Write the env files:**
   ```sh
   python scripts/render_env.py      # frontend/.env.local, backend/.env
   terraform -chdir=infra output -raw google_services_json > <studydeck>/app/google-services.json
   ```
   Rebuild the frontend (`npm run build`) so the Firebase and Sentry config is baked in.
6. **StudyDeck:** put the printed DSN in `local.properties` as `sentry.dsn=...`. Then sign in and use **Sync to cloud** on each deck to upload it again. Your decks are stored on the phone, so nothing is lost.

## Notes
- State is local (`infra/terraform.tfstate`, gitignored). For a shared backend, see `versions.tf`.
- `google_firestore_database` uses `deletion_policy = ABANDON`, so `terraform destroy` never deletes anyone's progress.
