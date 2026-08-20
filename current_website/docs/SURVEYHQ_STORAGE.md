# SurveyHQ durable media storage

SurveyHQ question images and official generated reports use Django's configured storage backend. Local development may use `MEDIA_ROOT`, but production must not accept these durable records on an ephemeral filesystem.

Before enabling production writes:

1. Attach a Render persistent disk and mount it at the exact filesystem path configured as Django's `MEDIA_ROOT`.
2. Set `SURVEYHQ_DURABLE_STORAGE_READY=True` only after the mount is active and writable.
3. Generate a test question image and official report, restart the service, and deploy a new release. Verify both protected downloads still work and pass checksum verification after each operation.
4. Configure backups for the persistent disk and periodically test restoration. Database backups alone do not preserve image or report binaries.
5. Monitor capacity and failed writes. Do not place SurveyHQ media in the seven-day project-chat attachment area.

When `DEBUG=False` and the readiness flag is not enabled, Django emits `surveyhq.W001`, and SurveyHQ refuses new image uploads and report generation. Existing verified media remains readable through its protected endpoints.
