import * as Sentry from "@sentry/react";

/** Error reporting, only when the build has VITE_SENTRY_DSN (scripts/render_env.py writes it). */
export function initSentry(): boolean {
  const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
  if (!dsn) return false;
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    // No user info or HTTP bodies: answers and the Firebase tokens posted to /api/cloud/session
    // stay local. Headers and query params keep Sentry's built-in token/key filtering.
    dataCollection: { userInfo: false, httpBodies: [] },
    // Answers are typed into this app; keep request payloads out of breadcrumbs.
    beforeBreadcrumb: (crumb) => {
      if (crumb.category === "fetch" || crumb.category === "xhr") {
        const { url, method, status_code } = crumb.data ?? {};
        crumb.data = { url, method, status_code };
      }
      return crumb;
    },
  });
  return true;
}

export { Sentry };
