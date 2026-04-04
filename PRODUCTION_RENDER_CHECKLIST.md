# Production Checklist

This document tracks what is already implemented in the repo and what still needs to happen before and after the first live Render deployment.

## Already Implemented

- Production-oriented Django settings in [current_website/landingpage/settings.py](current_website/landingpage/settings.py)
- `DATABASE_URL` support for managed Postgres in [current_website/landingpage/settings.py](current_website/landingpage/settings.py)
- Cache-backed rate limiting for login, 2FA, signup, password reset, username recovery, contact submissions, newsletter signup, and mobile push device registration in [current_website/landingpage/throttling.py](current_website/landingpage/throttling.py), [current_website/apps/accounts/views.py](current_website/apps/accounts/views.py), and [current_website/apps/news/views.py](current_website/apps/news/views.py)
- Health endpoint for uptime monitoring in [current_website/landingpage/health.py](current_website/landingpage/health.py) and [current_website/landingpage/urls.py](current_website/landingpage/urls.py)
- Internal operator email alerts for server-side failures through Django logging in [current_website/landingpage/settings.py](current_website/landingpage/settings.py)
- Optional Sentry integration for richer error monitoring when `SENTRY_DSN` is configured in [current_website/landingpage/settings.py](current_website/landingpage/settings.py)
- Database-backed outbound job queue, worker command, and newsletter scheduler support in [current_website/apps/operations/services.py](current_website/apps/operations/services.py), [current_website/apps/operations/management/commands/process_outbound_jobs.py](current_website/apps/operations/management/commands/process_outbound_jobs.py), and [render.yaml](render.yaml)
- Stricter upload validation and safer attachment download headers in [current_website/apps/clients/forms.py](current_website/apps/clients/forms.py) and [current_website/apps/clients/views.py](current_website/apps/clients/views.py)
- CI pipeline with Django checks, deploy checks, tests, CSS build, and mobile typecheck in [.github/workflows/ci.yml](.github/workflows/ci.yml)
- Smoke tests for health and throttled flows in [current_website/landingpage/tests.py](current_website/landingpage/tests.py), [current_website/apps/accounts/tests.py](current_website/apps/accounts/tests.py), and [current_website/apps/news/tests.py](current_website/apps/news/tests.py)

## What Render Will Cover

- Managed PostgreSQL provisioning and `DATABASE_URL`
- Runtime environment variable injection
- Gunicorn start command execution
- HTTPS termination and proxy forwarding
- Hosting and process restarts
- Pre-deploy migrations through [render.yaml](render.yaml)
- Outbound worker and newsletter scheduler services through [render.yaml](render.yaml)

## What Is Left Before First Production Launch

1. Set the real Render environment variables.
Use your private production env source such as `.env.prod` and copy the live values into Render. This includes `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`, SMTP credentials, Turnstile keys, admin alert addresses, and optionally `SENTRY_DSN`.

2. Deploy to Render and run the first production migration.
This repo now includes a Render pre-deploy command in [render.yaml](render.yaml) that runs `python manage.py migrate` during deployment.

3. Create the first production superuser.
This will be done after the app is live.

4. Set up uptime monitoring.
UptimeRobot is sufficient for the initial monitor. Point it at `/health/` instead of the homepage. A 5-minute interval is enough for the first deployment.

5. Decide whether to enable Sentry now.
This is optional. If you want richer observability than email alerts, create a free Sentry account at `sentry.io`, create a project, and add `SENTRY_DSN` plus the related Sentry env vars in Render.

6. Confirm the Render worker and newsletter scheduler services are created and healthy.

7. Run the live production smoke test.
After the site is live, manually verify the key flows listed below.

## Live Production Smoke Test

Run these checks on the live Render deployment:

1. Visit `/health/` and confirm it returns a healthy response.
2. Confirm the homepage, services page, and contact page load correctly.
3. Test signup.
4. Test login.
5. Test password reset.
6. Test username recovery.
7. Test contact form submission.
8. Test newsletter subscribe and unsubscribe.
9. Confirm Turnstile-protected forms work in the live domain.
10. Confirm the admin URL works and the production superuser can sign in.
11. Trigger one real project/client notification flow and confirm the worker delivers it.
12. Trigger one newsletter send and confirm the worker delivers it.
13. Confirm the mobile app points to the production site URL before any production mobile build is distributed.

## UptimeRobot Setup

UptimeRobot can handle the first uptime monitor and keep-awake check.

1. Create or sign in to your account at `https://uptimerobot.com/`.
2. Choose `Add New Monitor`.
3. Select `HTTP(s)` monitor type.
4. Use a monitor name such as `Miranda Insights Production`.
5. Set the URL to `https://<your-live-domain>/health/`.
6. Set the monitoring interval to 5 minutes.
7. Save the monitor.
8. Add your preferred alert contact method in UptimeRobot so downtime notifications actually reach you.

Pointing UptimeRobot at `/health/` is better than the homepage because it checks Django, the database connection, and the configured cache, not just whether the web server returns HTML.

## Deferred For Later

These are valid later-phase items and are not required for the first launch based on the current plan.

1. Redis-backed shared throttling and cache.
The current local-memory cache is acceptable for a single web instance. Move to Redis when you scale horizontally.

2. Persistent media/static storage strategy such as Supabase storage.
Planned for later.

## Recommendation

If launching now, the next concrete sequence is:

1. Enter the real env vars in Render.
2. Deploy.
3. Confirm Render picks up the `preDeployCommand` in [render.yaml](render.yaml) and runs migrations successfully.
4. Confirm the worker and cron services from [render.yaml](render.yaml) are running.
5. Create the first superuser.
6. Set up UptimeRobot on `/health/`.
7. Optionally enable Sentry.
8. Run the live smoke test.