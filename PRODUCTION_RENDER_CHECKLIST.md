# Production Checklist

This document tracks what is already implemented in the repo and what still needs to happen before and after the first live Render deployment.

## Already Implemented

- Production-oriented Django settings in [current_website/landingpage/settings.py](current_website/landingpage/settings.py)
- `DATABASE_URL` support for managed Postgres in [current_website/landingpage/settings.py](current_website/landingpage/settings.py)
- Cache-backed rate limiting for login, 2FA, signup, password reset, username recovery, contact submissions, newsletter signup, and mobile push device registration in [current_website/landingpage/throttling.py](current_website/landingpage/throttling.py), [current_website/apps/accounts/views.py](current_website/apps/accounts/views.py), and [current_website/apps/news/views.py](current_website/apps/news/views.py)
- Health endpoint for uptime monitoring in [current_website/landingpage/health.py](current_website/landingpage/health.py) and [current_website/landingpage/urls.py](current_website/landingpage/urls.py)
- Internal operator email alerts for server-side failures through Django logging in [current_website/landingpage/settings.py](current_website/landingpage/settings.py)
- Optional Sentry integration for richer error monitoring when `SENTRY_DSN` is configured in [current_website/landingpage/settings.py](current_website/landingpage/settings.py)
- Database-backed outbound job queue, worker command, and token-protected newsletter scheduler endpoint in [current_website/apps/operations/services.py](current_website/apps/operations/services.py), [current_website/apps/operations/management/commands/process_outbound_jobs.py](current_website/apps/operations/management/commands/process_outbound_jobs.py), and [current_website/apps/news/views.py](current_website/apps/news/views.py)
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
- Outbound worker service through [render.yaml](render.yaml)

## What Is Left Before First Production Launch

1. Set the real Render environment variables.
Use your private production env source such as `.env.prod` and copy the live values into Render. This includes `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `NEWSLETTER_SCHEDULER_TOKEN`, SMTP credentials, Turnstile keys, admin alert addresses, and optionally `SENTRY_DSN`.

2. Deploy to Render and run the first production migration.
This repo now includes a Render pre-deploy command in [render.yaml](render.yaml) that runs `python manage.py migrate` during deployment.

3. Create the first production superuser.
This will be done after the app is live.

4. Set up uptime monitoring.
UptimeRobot is sufficient for the initial monitor. Point it at `/health/` instead of the homepage. A 5-minute interval is enough for the first deployment.

5. Decide whether to enable Sentry now.
This is optional. If you want richer observability than email alerts, create a free Sentry account at `sentry.io`, create a project, and add `SENTRY_DSN` plus the related Sentry env vars in Render.

6. Confirm the Render outbound worker service is created and healthy, then configure the UptimeRobot newsletter trigger described below. The worker must remain active while `OUTBOUND_DELIVERY_MODE=queue` because it delivers the queued email jobs.

7. Configure persistent media storage before relying on Client Portal attachments.
The current default storage writes chat attachments to `MEDIA_ROOT`, while [render.yaml](render.yaml) does not declare a persistent disk. Configure a Render persistent disk mounted at the deployed `MEDIA_ROOT` and verify that an authenticated attachment remains available after both a service restart and a deployment. Without this step, Render may remove an attachment before the intended seven-day chat-retention window ends.

8. Run the live production smoke test.
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
14. Upload a test project-chat attachment and confirm its protected download survives a service restart and deployment.

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

## UptimeRobot Newsletter Scheduler

The Render cron service is not required. UptimeRobot can call the protected scheduler endpoint on the same 5-minute interval.

1. Generate a long URL-safe token locally, for example:

   ```powershell
   $bytes = New-Object byte[] 32
   [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
   [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
   ```

2. Add the generated value as the `NEWSLETTER_SCHEDULER_TOKEN` environment variable on the Render web service. Do not commit the token to the repository.
3. Deploy or restart the web service so the environment variable is loaded.
4. In UptimeRobot, add an `HTTP(s)` monitor with this URL:
   `https://<your-live-domain>/newsletter/scheduler/?token=<your-token>`
5. Set the interval to 5 minutes and leave the expected status as `200`.
6. Confirm the monitor receives a JSON response with `"status": "ok"`.

Treat the monitor URL as a secret because its query string contains the scheduler token. The endpoint also accepts the token in the `X-Newsletter-Scheduler-Token` header if a UptimeRobot monitor configuration supports custom headers.

## Deferred For Later

These are valid later-phase items and are not required for the first launch based on the current plan.

1. Redis-backed shared throttling and cache.
The current local-memory cache is acceptable for a single web instance. Move to Redis when you scale horizontally.

2. Object storage, backups, and malware inspection beyond the initial persistent Render disk.
These become important if attachment volume, horizontal scaling, or retention requirements grow. They are not required for the current seven-day workflow once persistent media storage is verified.

## Recommendation

If launching now, the next concrete sequence is:

1. Enter the real env vars in Render.
2. Deploy.
3. Confirm Render picks up the `preDeployCommand` in [render.yaml](render.yaml) and runs migrations successfully.
4. Confirm the worker from [render.yaml](render.yaml) is running and verify the UptimeRobot newsletter scheduler monitor.
5. Configure and verify the persistent media disk.
6. Create the first superuser.
7. Set up UptimeRobot on `/health/` and `/newsletter/scheduler/` as described above.
8. Optionally enable Sentry.
9. Run the live smoke test.
