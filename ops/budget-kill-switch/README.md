# Budget kill switch

When the project's monthly spend reaches the budget (1 EUR), the API on Cloud
Run is switched to **internal-only ingress**: the public can no longer call it,
so it stops costing. Nothing is deleted.

```
Cloud Billing budget ──► Pub/Sub topic `budget-alerts` ──► function `budget-kill-switch`
                                                             └─► Cloud Run `brand-my-label`: ingress = internal
```

Budget data arrives with a delay of a few hours, so spend can slightly exceed
the budget before the switch fires; max-instances and rate limits bound that.

## Turn the API back on

```bash
gcloud run services update brand-my-label --region europe-west1 --ingress all
```

## Deploy / redeploy

```bash
gcloud functions deploy budget-kill-switch --gen2 --region europe-west1 \
  --runtime python312 --source ops/budget-kill-switch --entry-point handle \
  --trigger-topic budget-alerts --service-account kill-switch@brand-my-label-api.iam.gserviceaccount.com \
  --max-instances 1 --memory 256Mi
```

## Test without spending

```bash
gcloud pubsub topics publish budget-alerts \
  --message '{"costAmount": 2, "budgetAmount": 1, "currencyCode": "EUR"}'
```
