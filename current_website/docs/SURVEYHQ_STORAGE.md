# SurveyHQ durable media storage

SurveyHQ question images and official generated reports use Django's default file storage. The same backend also stores project-chat attachments and newsletter image assets. CSS and JavaScript remain deployment static files served by WhiteNoise.

## Supabase production setup

1. Create a private Supabase Storage bucket for the application media.
2. Enable the Supabase Storage S3 protocol and generate a server-only access key pair.
3. Add these environment variables to both Render services so Django can initialize consistently:

   ```text
   SUPABASE_STORAGE_ENABLED=true
   SUPABASE_S3_BUCKET=miranda-insights-media
   SUPABASE_S3_ENDPOINT_URL=https://<project-ref>.storage.supabase.co/storage/v1/s3
   SUPABASE_S3_REGION=<supabase-project-region>
   SUPABASE_S3_ACCESS_KEY_ID=<server-only-access-key>
   SUPABASE_S3_SECRET_ACCESS_KEY=<server-only-secret-key>
   SUPABASE_S3_QUERYSTRING_EXPIRE=604800
   ```

   Keep the access key and secret key only in Render environment variables. Do not expose them to the mobile app or browser.

4. Copy existing local uploads before switching traffic to the new backend:

   ```powershell
   python manage.py migrate_media_to_supabase --dry-run
   python manage.py migrate_media_to_supabase
   ```

   The command copies files and leaves the local originals untouched. It covers survey images, reports, project-chat attachments, and newsletter image assets.

5. After the bucket is reachable and the migration is complete, set:

   ```text
   SURVEYHQ_DURABLE_STORAGE_READY=true
   ```

   This flag is an application safety gate. It does not configure Supabase by itself.

6. Test a question-image upload, protected question-image download, report generation, report download, project attachment download, and newsletter image preview after deployment.

The default S3 URL lifetime is seven days because newsletter email bodies use storage URLs. Increase `SUPABASE_S3_QUERYSTRING_EXPIRE` if newsletters must display images for longer, or introduce a separate public newsletter-asset bucket. Survey images, reports, and project attachments should remain private and continue to be served through the app's authorization checks.

Supabase Storage does not provide S3 object versioning, so retain an independent backup/export process for important media.

## Local development

Leave `SUPABASE_STORAGE_ENABLED=false` to use the existing `MEDIA_ROOT` filesystem backend locally. Production must not use the ephemeral Render filesystem for durable uploads.
