"""Budget kill switch for the brand-my-label Cloud Run service.

Cloud Billing budgets publish a JSON message to Pub/Sub several times a day
with the month's spend. When costAmount reaches budgetAmount, this function
switches the Cloud Run service to internal-only ingress: public requests are
refused, so the API stops costing anything. Nothing is deleted.

Turn the API back on:
    gcloud run services update brand-my-label --region europe-west1 --ingress all
"""

import base64
import json
import logging
import os

import functions_framework
from google.cloud import run_v2

SERVICE = os.environ.get(
    "TARGET_SERVICE",
    "projects/brand-my-label-api/locations/europe-west1/services/brand-my-label")

log = logging.getLogger("kill-switch")
logging.basicConfig(level=logging.INFO)


def over_budget(msg: dict) -> bool:
    cost, budget = msg.get("costAmount"), msg.get("budgetAmount")
    return cost is not None and budget is not None and float(cost) >= float(budget)


@functions_framework.cloud_event
def handle(event):
    raw = base64.b64decode(event.data["message"]["data"]).decode()
    msg = json.loads(raw)
    log.info("budget update: cost=%s budget=%s %s", msg.get("costAmount"),
             msg.get("budgetAmount"), msg.get("currencyCode"))
    if not over_budget(msg):
        return

    client = run_v2.ServicesClient()
    svc = client.get_service(name=SERVICE)
    internal = run_v2.IngressTraffic.INGRESS_TRAFFIC_INTERNAL_ONLY
    if svc.ingress == internal:
        log.info("already internal-only, nothing to do")
        return
    svc.ingress = internal
    client.update_service(service=svc).result(timeout=300)
    log.warning("BUDGET REACHED: %s switched to internal-only ingress", SERVICE)
