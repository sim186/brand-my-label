// Public config for the static site. The PostHog project token is a public,
// write-only key (it is meant to ship in browser code). Leave it empty to
// disable analytics.
window.BML_CONFIG = {
  API_URL: "http://localhost:8091",          // Cloud Run URL in production
  POSTHOG_PROJECT_TOKEN: "",
  POSTHOG_HOST: "https://eu.i.posthog.com",
  DONATE_URL: "",                            // e.g. https://ko-fi.com/yourname
};
