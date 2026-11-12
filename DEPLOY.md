# Deploy

## API: Google Cloud Run

One-time setup:

```bash
brew install --cask google-cloud-sdk
gcloud auth login
gcloud projects create brand-my-label-api        # or reuse a project
gcloud config set project brand-my-label-api
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

Deploy (builds the Dockerfile with Cloud Build):

```bash
gcloud run deploy brand-my-label \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --memory 512Mi --cpu 1 \
  --concurrency 8 --max-instances 3 --timeout 60 \
  --set-env-vars "ALLOWED_ORIGINS=https://YOUR-DOMAIN,POSTHOG_PROJECT_TOKEN=phc_xxx,POSTHOG_HOST=https://eu.i.posthog.com"
```

- `--max-instances 3` caps the bill if someone hammers the API. Together with
  the per-IP rate limit and the size limits, worst-case cost stays at a few euros.
- Set a budget alert in Cloud Billing (for example €5/month).
- `europe-west1` keeps label data in the EU (GDPR).
- The command prints the service URL. Put it in `docs/config.js` as `API_URL`.

## Site: GitHub Pages

1. Push the repo to GitHub.
2. Settings → Pages → Source: *Deploy from a branch*, branch `main`, folder `/docs`.
3. Custom domain: add it in Settings → Pages (this creates `docs/CNAME`), then
   add a `CNAME` DNS record pointing to `<user>.github.io`.
4. Add the final site origin to the API's `ALLOWED_ORIGINS`.

## Analytics: PostHog

Use a dedicated PostHog project (EU). The project token is public by design:
- `docs/config.js` → `POSTHOG_PROJECT_TOKEN` (browser events)
- Cloud Run env `POSTHOG_PROJECT_TOKEN` (server events)

Events:

| Event | Where | Properties |
|---|---|---|
| `$pageview` | site | — |
| `label_selected` | site | input_type, size_kb |
| `logo_selected` | site | mime, size_kb |
| `stamp_requested` | site | to_a4 |
| `stamp_succeeded` / `stamp_failed` | site | placement_mode, carrier / error_code |
| `branded_label_downloaded`, `branded_label_printed`, `donate_clicked` | site | — |
| `label_stamped` | API | input_type, placement_mode, logo_placed, carrier, normalized_a4, page_count, input_kb, duration_ms |
| `label_stamp_failed` | API | error_code, input_type |

The browser sends `X-POSTHOG-DISTINCT-ID` / `X-POSTHOG-SESSION-ID`, so site and
API events join up in the same session. Persistence is in memory only (no
cookies), so every visit counts as a new anonymous user.
