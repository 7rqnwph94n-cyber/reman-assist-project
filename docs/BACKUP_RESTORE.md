# Backup + Restore (Pilot, Postgres + Uploads)

## RPO / RTO (pilot target)
- RPO: 24 hours (daily backups)
- RTO: 2 hours (restore + verify)

## Required env
- `DATABASE_URL` (Postgres)
- `UPLOAD_FOLDER`

## Backup DB
```
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/reman \
  scripts/backup_pg.sh
```

## Quiesce/maintenance step (consistency)
Before backup, briefly stop the app or enable maintenance mode so DB + uploads stay consistent.

## Restore DB (fresh/empty target)
```
RESTORE_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/reman_restore \
  CONFIRM_RESTORE=1 \
  scripts/restore_pg.sh /path/to/backup.dump
```

## Backup uploads
```
UPLOAD_FOLDER=/path/to/uploads \
  scripts/backup_uploads.sh
```

## Restore uploads
```
UPLOAD_FOLDER=/path/to/uploads \
  CONFIRM_RESTORE=1 \
  scripts/restore_uploads.sh /path/to/uploads_backup.tgz
```

## Restore drill (pilot readiness)
1) Provision empty Postgres DB.
2) Restore DB from latest backup.
3) Restore uploads to clean folder.
4) Run `python -m flask --app app:create_app db upgrade`.
5) Run pilot smoke test.

## Notes
- Never restore over a live DB.
- Always verify uploads folder permissions after restore.
