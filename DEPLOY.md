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

Build locally and push (avoids Cloud Build), then deploy:

```bash
R=europe-west1-docker.pkg.dev/brand-my-label-api/bml/api
gcloud artifacts repositories create bml --repository-format=docker --location=europe-west1
gcloud auth configure-docker europe-west1-docker.pkg.dev
docker build --platform linux/amd64 -t $R:v2 . && docker push $R:v2

gcloud run deploy brand-my-label --image $R:v2 \
  --region europe-west1 --allow-unauthenticated \
  --memory 512Mi --cpu 1 --concurrency 8 \
  --min-instances 0 --max-instances 2 --timeout 60 --cpu-throttling \
  --set-env-vars "^;^ALLOWED_ORIGINS=https://labels.sim1.org,https://sim186.github.io;POSTHOG_PROJECT_TOKEN=phc_xxx;POSTHOG_HOST=https://eu.i.posthog.com"
```

- `^;^` switches gcloud's list separator to `;` so the comma-separated origins survive.
- Later releases: build/push a new tag, then `gcloud run deploy brand-my-label --image $R:<tag> --region europe-west1`.

### Keeping it free

- `--min-instances 0` + `--cpu-throttling`: billed only while a request runs; idle costs nothing.
- `--max-instances 2`, per-IP rate limit and upload caps bound the worst case.
- Artifact Registry cleanup policy keeps only the 2 newest images (free tier: 0.5 GB; one image is ~90 MB).
- Budget of 1 EUR on the project with email alerts at 1%, 50%, 100%.
  A budget **alerts**, it does not stop spending; the caps above are what limit cost.
- `europe-west1` keeps label data in the EU (GDPR).

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
