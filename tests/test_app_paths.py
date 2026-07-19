"""验证 portable app root：frozen 模式下可写路径绝不落在 _MEIPASS。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths
import app_config
import account_outputs
import cpa_export


class AppPathsTests(unittest.TestCase):
    def test_dev_root_is_source_tree(self):
        root = app_paths.get_app_root()
        self.assertTrue(os.path.isdir(root))
        self.assertTrue(
            os.path.isfile(os.path.join(root, "app_paths.py"))
            or os.path.isfile(os.path.join(root, "grok_register_ttk.py"))
        )
        self.assertEqual(
            os.path.normcase(app_paths.default_config_path()),
            os.path.normcase(os.path.join(root, "config.json")),
        )

    def test_frozen_paths_stay_outside_meipass(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe_dir = Path(tmp) / "install"
            meipass = Path(tmp) / "_MEIPASS_bundle"
            exe_dir.mkdir()
            meipass.mkdir()
            fake_exe = exe_dir / "grok-register.exe"
            fake_exe.write_text("", encoding="utf-8")

            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "_MEIPASS", str(meipass), create=True
            ), patch.object(sys, "executable", str(fake_exe)):
                app_root = app_paths.get_app_root()
                resource_root = app_paths.get_resource_root()
                config_path = app_paths.default_config_path()
                accounts_path = app_paths.default_accounts_path("20260101_000000")
                token_path = app_paths.default_token_path()
                cpa_dir = app_paths.default_cpa_auth_dir()
                mail_dir = app_paths.default_mail_credentials_dir()

            self.assertEqual(os.path.normcase(app_root), os.path.normcase(str(exe_dir)))
            self.assertEqual(os.path.normcase(resource_root), os.path.normcase(str(meipass)))
            self.assertTrue(config_path.startswith(str(exe_dir)))
            self.assertTrue(accounts_path.startswith(str(exe_dir)))
            self.assertTrue(token_path.startswith(str(exe_dir)))
            self.assertTrue(cpa_dir.startswith(str(exe_dir)))
            self.assertEqual(os.path.normcase(mail_dir), os.path.normcase(str(exe_dir)))

            meipass_norm = os.path.normcase(str(meipass))
            for path in (config_path, accounts_path, token_path, cpa_dir, mail_dir, app_root):
                self.assertFalse(
                    os.path.normcase(path).startswith(meipass_norm + os.sep)
                    or os.path.normcase(path) == meipass_norm,
                    msg=f"writable path leaked into _MEIPASS: {path}",
                )

    def test_token_default_uses_app_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe_dir = Path(tmp) / "app"
            meipass = Path(tmp) / "bundle"
            exe_dir.mkdir()
            meipass.mkdir()
            fake_exe = exe_dir / "grok-register"
            fake_exe.write_text("", encoding="utf-8")
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "_MEIPASS", str(meipass), create=True
            ), patch.object(sys, "executable", str(fake_exe)):
                # empty config dict -> default path
                old = account_outputs.config
                try:
                    account_outputs.config = {}
                    path = account_outputs.resolve_grok2api_local_token_file()
                finally:
                    account_outputs.config = old
            self.assertEqual(
                os.path.normcase(path),
                os.path.normcase(str(exe_dir / "token.json")),
            )
            self.assertNotIn("_MEIPASS", path)
            self.assertFalse(os.path.normcase(path).startswith(os.path.normcase(str(meipass))))

    def test_cpa_relative_auth_dir_resolves_under_app_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe_dir = Path(tmp) / "install"
            meipass = Path(tmp) / "_MEIPASS_bundle"
            exe_dir.mkdir()
            meipass.mkdir()
            fake_exe = exe_dir / "grok-register.exe"
            fake_exe.write_text("", encoding="utf-8")
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "_MEIPASS", str(meipass), create=True
            ), patch.object(sys, "executable", str(fake_exe)):
                settings = cpa_export.CpaExportSettings.from_config(
                    {"cpa_auth_dir": "./cpa_auths", "cpa_export_enabled": True}
                )
            self.assertEqual(
                os.path.normcase(str(settings.auth_dir)),
                os.path.normcase(str((exe_dir / "cpa_auths").resolve())),
            )
            self.assertFalse(
                os.path.normcase(str(settings.auth_dir)).startswith(
                    os.path.normcase(str(meipass))
                )
            )

    def test_ensure_user_data_layout_copies_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe_dir = Path(tmp) / "install"
            meipass = Path(tmp) / "bundle"
            exe_dir.mkdir()
            meipass.mkdir()
            (meipass / "config.example.json").write_text('{"email_provider":"duckmail"}\n', encoding="utf-8")
            fake_exe = exe_dir / "grok-register"
            fake_exe.write_text("", encoding="utf-8")
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "_MEIPASS", str(meipass), create=True
            ), patch.object(sys, "executable", str(fake_exe)):
                root = app_paths.ensure_user_data_layout(copy_example=True)
            self.assertEqual(os.path.normcase(root), os.path.normcase(str(exe_dir)))
            self.assertTrue((exe_dir / "config.example.json").is_file())
            # must not create real config.json automatically
            self.assertFalse((exe_dir / "config.json").exists())

    def test_config_file_constant_points_at_app_root_in_dev(self):
        # Module-level CONFIG_FILE is set at import; in dev it matches default_config_path
        # unless tests reassigned it.
        self.assertTrue(app_config.CONFIG_FILE.endswith("config.json"))


if __name__ == "__main__":
    unittest.main()
