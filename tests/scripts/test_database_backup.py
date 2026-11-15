"""Standalone tests: python3 -m unittest discover -s tests/scripts -p test_database_backup.py."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "database_backup", Path(__file__).resolve().parents[2] / "scripts/backup_database.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "backups"
        self.old_umask = os.umask(0o077)
        self.addCleanup(os.umask, self.old_umask)

    def fake_dump(self, args, **kwargs):
        kwargs["stdout"].write(b"PGDMP fixture")
        return subprocess.CompletedProcess(args, 0)

    def make_backup(self):
        with patch.object(backup, "run", side_effect=self.fake_dump), patch.object(
                backup, "verify_restore", return_value={"restored_tables": 42}):
            return backup.backup(self.directory, "source-db", 2)

    def test_success_is_private_checksummed_and_verified(self):
        path = self.make_backup()
        backup.check_checksum(path)
        backup.status(self.directory, 36)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        metadata = json.loads(path.with_suffix(".dump.json").read_text())
        self.assertTrue(metadata["restore_verified"])
        self.assertEqual(metadata["restored_tables"], 42)
        self.assertFalse(list(self.directory.glob("*.partial")))

    def test_dump_failure_does_not_publish_or_prune(self):
        old = self.make_backup()
        with patch.object(backup, "run", side_effect=subprocess.CalledProcessError(1, "pg_dump")):
            with self.assertRaises(subprocess.CalledProcessError):
                backup.backup(self.directory, "source-db", 2)
        self.assertEqual(list(self.directory.glob("*.dump")), [old])
        self.assertFalse(list(self.directory.glob("*.partial")))

    def test_restore_failure_keeps_all_previous_backups(self):
        old = [self.make_backup(), self.make_backup()]
        with patch.object(backup, "run", side_effect=self.fake_dump), patch.object(
                backup, "verify_restore", side_effect=ValueError("broken archive")):
            with self.assertRaisesRegex(ValueError, "broken"):
                backup.backup(self.directory, "source-db", 2)
        self.assertEqual(set(self.directory.glob("*.dump")), set(old))
        self.assertFalse(list(self.directory.glob("*.partial")))

    def test_retention_only_deletes_completed_tool_archives(self):
        first = self.make_backup()
        unrelated = self.directory / "manual.dump"
        unrelated.write_bytes(b"keep")
        incomplete = self.directory / "llt-db-20250101T000000Z-aaaaaaaaaaaa.dump"
        incomplete.write_bytes(b"keep incomplete")
        second, third = self.make_backup(), self.make_backup()
        self.assertFalse(first.exists())
        self.assertFalse(first.with_suffix(".dump.sha256").exists())
        for path in (second, third, unrelated, incomplete):
            self.assertTrue(path.exists())

    def test_corruption_is_detected(self):
        path = self.make_backup()
        path.write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "checksum"):
            backup.check_checksum(path)
        with self.assertRaisesRegex(ValueError, "checksum"):
            backup.status(self.directory, 36)

    def test_stale_backup_is_an_error(self):
        path = self.make_backup()
        metadata_path = path.with_suffix(".dump.json")
        metadata = json.loads(metadata_path.read_text())
        metadata["created_at"] = "2020-01-01T00:00:00+00:00"
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "stale"):
            backup.status(self.directory, 36)

    def test_concurrent_backup_is_rejected(self):
        with backup.lock_directory(self.directory):
            with self.assertRaisesRegex(RuntimeError, "already running"):
                with backup.lock_directory(self.directory):
                    self.fail("Second backup acquired lock")

    def test_cannot_keep_only_one_copy(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            backup.backup(self.directory, "source-db", 1)

    def test_restore_failure_cleans_only_its_isolated_container(self):
        archive = Path(self.temp.name) / "fixture.dump"
        archive.write_bytes(b"data")
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if args[1] == "inspect":
                output = "sha256:" + "a" * 64
            elif args[1] == "create":
                self.assertIn("none", args)
                self.assertNotIn("-p", args)
                output = "disposable-container-id"
            elif args[-1] == "/proc/1/comm":
                output = "postgres"
            elif "pg_restore" in args:
                raise subprocess.CalledProcessError(1, args)
            else:
                output = ""
            return subprocess.CompletedProcess(args, 0, stdout=output)

        with patch.object(backup, "run", side_effect=fake_run), patch.object(
                backup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(subprocess.CalledProcessError):
                backup.verify_restore(archive, "source-db")
        self.assertEqual(calls[-1], ["docker", "rm", "-f", "-v", "disposable-container-id"])
        self.assertFalse(any("pg_restore" in call and "source-db" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
