import os
import sqlite3
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Create a safe database backup (SQLite hot backup, PostgreSQL pg_dump, or JSON dump) and prune old backups."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default=str(Path(settings.BASE_DIR) / "backups"),
            help="Directory where backup files will be saved (default: <BASE_DIR>/backups).",
        )
        parser.add_argument(
            "--format",
            choices=["auto", "sqlite", "pgdump", "json"],
            default="auto",
            help="Backup format: auto (native engine), sqlite, pgdump, or json.",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=14,
            help="Number of recent backup files to keep (older backups are pruned). Use 0 to disable pruning.",
        )

    def handle(self, *args, **options):
        out_dir = Path(options["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
        db_cfg = settings.DATABASES["default"]
        engine = db_cfg.get("ENGINE", "")
        fmt = options["format"]

        if fmt == "auto":
            if "sqlite3" in engine:
                fmt = "sqlite"
            elif "postgresql" in engine:
                fmt = "pgdump"
            else:
                fmt = "json"

        created_file = None

        if fmt == "sqlite":
            db_path = Path(str(db_cfg.get("NAME", "")))
            if not db_path.is_file():
                raise CommandError(f"SQLite database file not found at {db_path}. Use --format=json for in-memory DBs.")
            dest = out_dir / f"advance_billing_{stamp}.sqlite3"
            src_conn = sqlite3.connect(str(db_path))
            dst_conn = sqlite3.connect(str(dest))
            try:
                with dst_conn:
                    src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
            created_file = dest

        elif fmt == "pgdump":
            dest = out_dir / f"advance_billing_{stamp}.sql"
            env = os.environ.copy()
            if db_cfg.get("PASSWORD"):
                env["PGPASSWORD"] = str(db_cfg["PASSWORD"])
            cmd = [
                "pg_dump",
                "-h", str(db_cfg.get("HOST") or "127.0.0.1"),
                "-p", str(db_cfg.get("PORT") or "5432"),
                "-U", str(db_cfg.get("USER") or "postgres"),
                "-f", str(dest),
                str(db_cfg.get("NAME")),
            ]
            try:
                subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
            except FileNotFoundError as exc:
                raise CommandError("pg_dump binary not found on PATH. Install PostgreSQL client tools or use --format=json.") from exc
            except subprocess.CalledProcessError as exc:
                raise CommandError(f"pg_dump failed: {exc.stderr}") from exc
            created_file = dest

        else:  # json
            dest = out_dir / f"advance_billing_{stamp}.json"
            with open(dest, "w", encoding="utf-8") as fh:
                call_command("dumpdata", "auth.user", "accounts", "billing", indent=2, stdout=fh)
            created_file = dest

        self.stdout.write(self.style.SUCCESS(f"Backup created successfully: {created_file}"))

        keep = options["keep"]
        if keep > 0:
            backups = sorted(
                [p for p in out_dir.iterdir() if p.is_file() and p.name.startswith("advance_billing_")],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old_file in backups[keep:]:
                old_file.unlink(missing_ok=True)
                self.stdout.write(f"Pruned old backup: {old_file.name}")

