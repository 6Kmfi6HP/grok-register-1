#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


# grok_register_ttk.py: single config implementation, full state compatibility,
# and complete GUI batch counter reset.
path = "grok_register_ttk.py"
text = read(path)
old_config_impl = '''def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            config = validate_config_structure(loaded)
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(f"配置文件解析失败: {CONFIG_FILE}: {exc}") from exc
    else:
        config = validate_config_structure(DEFAULT_CONFIG.copy())
    return config


def save_config():
    global config
    config = validate_config_structure(config)
    config_dir = os.path.dirname(os.path.abspath(CONFIG_FILE))
    os.makedirs(config_dir, exist_ok=True)
    fd = None
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".config-", suffix=".json.tmp", dir=config_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            json.dump(config, f, indent=4, ensure_ascii=False)
            f.write("\\n")
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except Exception:
            pass
        os.replace(temp_path, CONFIG_FILE)
        temp_path = None
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except Exception:
            pass
    except Exception as exc:
        raise ConfigError(f"保存配置失败: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


'''
text = replace_once(text, old_config_impl, "", "duplicate config implementation")
old_setattr = '''        elif name in {"_cf_domain_index", "_cloudmail_domain_index"}:
            setattr(_mail_service, name, int(value))
            self.__dict__.pop(name, None)
            return
        super().__setattr__(name, value)
'''
new_setattr = '''        elif name in {"_cf_domain_index", "_cloudmail_domain_index"}:
            setattr(_mail_service, name, int(value))
            self.__dict__.pop(name, None)
            return
        elif name in {"browser", "page", "browser_proxy_bridge", "browser_started_with_proxy", "cf_clearance"}:
            setattr(_registration_browser, name, value)
            self.__dict__.pop(name, None)
            return
        super().__setattr__(name, value)
'''
text = replace_once(text, old_setattr, new_setattr, "compatibility state writes")
old_reset = '''        self.stop_requested = False
        self.success_count = 0
        self.fail_count = 0
        self.results = []
'''
new_reset = '''        self.stop_requested = False
        self._reset_batch_counters()
        self.results = []
'''
text = replace_once(text, old_reset, new_reset, "GUI counter reset call")
anchor = '''    def should_stop(self):
        return self.stop_requested or not self.is_running

    def start_registration(self):
'''
replacement = '''    def should_stop(self):
        return self.stop_requested or not self.is_running

    def _reset_batch_counters(self):
        self.success_count = 0
        self.fail_count = 0
        self.registered_unsaved_count = 0
        self.postprocess_warning_count = 0

    def start_registration(self):
'''
text = replace_once(text, anchor, replacement, "GUI reset helper")
write(path, text)


# Restore exact registration URL.
path = "registration_browser.py"
text = read(path)
text = replace_once(
    text,
    'SIGNUP_URL = "https://accounts.x.ai/sign-up"',
    'SIGNUP_URL = "https://accounts.x.ai/sign-up?redirect=grok-com"',
    "registration URL",
)
write(path, text)


# Python 3.9-compatible typing.
path = "cpa_export.py"
text = read(path)
text = replace_once(text, "from pathlib import Path\n", "from pathlib import Path\nfrom typing import Optional\n", "Optional import")
text = replace_once(text, "    hotload_dir: Path | None\n", "    hotload_dir: Optional[Path]\n", "Python 3.9 union")
write(path, text)


# Make browser options explicitly reusable by CPA without importing the main app.
path = "browser_runtime.py"
text = read(path)
old_options = '''def create_browser_options(browser_proxy=""):
    options = ChromiumOptions()
    options.auto_port()
    options.set_timeouts(base=1)
    apply_browser_proxy_option(options, browser_proxy)
    if _extension_path and os.path.exists(_extension_path):
        options.add_extension(_extension_path)
    return options
'''
new_options = '''def create_browser_options(browser_proxy="", extension_path=None):
    options = ChromiumOptions()
    options.auto_port()
    options.set_timeouts(base=1)
    apply_browser_proxy_option(options, browser_proxy)
    effective_extension = _extension_path if extension_path is None else str(extension_path or "")
    if effective_extension and os.path.exists(effective_extension):
        options.add_extension(effective_extension)
    return options
'''
text = replace_once(text, old_options, new_options, "browser options factory")
write(path, text)

path = "cpa_xai/browser_session.py"
text = read(path)
text = text.replace("import sys\n", "")
old_probe = '''    options = None
    package_root = Path(__file__).resolve().parents[1]
    try:
        register_file = package_root / "grok_register_ttk.py"
        if register_file.is_file():
            register_dir = str(package_root)
            if register_dir not in sys.path:
                sys.path.insert(0, register_dir)
            try:
                from grok_register_ttk import create_browser_options  # type: ignore

                options = create_browser_options()
                logger("using register create_browser_options (turnstilePatch)")
            except Exception as exc:  # noqa: BLE001
                logger("register browser options unavailable: %s" % exc)
                options = None
    except Exception as exc:  # noqa: BLE001
        logger("register options probe failed: %s" % exc)
        options = None
'''
new_probe = '''    options = None
    package_root = Path(__file__).resolve().parents[1]
    try:
        from browser_runtime import create_browser_options

        options = create_browser_options(
            extension_path=package_root / "turnstilePatch"
        )
        logger("using shared browser_runtime.create_browser_options")
    except Exception as exc:  # noqa: BLE001
        logger("shared browser options unavailable: %s" % exc)
        options = None
'''
text = replace_once(text, old_probe, new_probe, "CPA reverse import removal")
write(path, text)


# Tighten CPA hotload validation.
path = "app_config.py"
text = read(path)
text = replace_once(
    text,
    '    if cfg["cpa_copy_to_hotload"] and not cfg["cpa_hotload_dir"]:\n',
    '    if cfg["cpa_export_enabled"] and cfg["cpa_copy_to_hotload"] and not cfg["cpa_hotload_dir"]:\n',
    "CPA hotload validation",
)
write(path, text)


# Centralize mail body normalization and fix address filtering independent of logging.
path = "mail_service.py"
text = read(path)
insert_anchor = '''def _pick_list_payload(data):
'''
helper = '''def normalize_mail_body(*sources):
    """Return normalized text from provider payloads with string/list HTML support."""
    parts = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("text", "raw", "content", "intro", "body", "snippet"):
            value = source.get(key)
            values = value if isinstance(value, (list, tuple)) else [value]
            for item in values:
                if isinstance(item, str) and item.strip():
                    parts.append(item)
        html_value = source.get("html")
        html_items = html_value if isinstance(html_value, (list, tuple)) else [html_value]
        for item in html_items:
            if isinstance(item, str) and item.strip():
                parts.append(re.sub(r"<[^>]+>", " ", item))
    return "\\n".join(parts)


'''
text = replace_once(text, insert_anchor, helper + insert_anchor, "mail body normalizer")
old_filter = '''            if not address_matched and log_callback:
                log_callback(f"[Debug] 跳过疑似非目标邮件 id={msg_id} address={msg_addr} to={recipients}")
                continue
'''
new_filter = '''            if not address_matched:
                if log_callback:
                    log_callback(f"[Debug] 跳过疑似非目标邮件 id={msg_id} address={msg_addr} to={recipients}")
                continue
'''
text = replace_once(text, old_filter, new_filter, "Cloudflare target filtering")
old_cf_body = '''            parts = []
            # 先直接从列表项取内容，避免 detail 接口差异导致漏码
            for field in ("text", "raw", "content", "intro", "body", "snippet"):
                value = msg.get(field)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
            html_list = msg.get("html") or []
            if isinstance(html_list, str):
                html_list = [html_list]
            for h in html_list:
                parts.append(re.sub(r"<[^>]+>", " ", h))
            subject = str(msg.get("subject", "") or "")
            combined = "\\n".join(parts)
'''
new_cf_body = '''            # 先直接从列表项取内容，避免 detail 接口差异导致漏码
            subject = str(msg.get("subject", "") or "")
            combined = normalize_mail_body(msg)
'''
text = replace_once(text, old_cf_body, new_cf_body, "Cloudflare body normalization")
old_cf_detail = '''                for field in ("text", "raw", "content", "intro", "body", "snippet"):
                    value = detail.get(field)
                    if isinstance(value, str) and value.strip():
                        combined += "\\n" + value
                html_list2 = detail.get("html") or []
                if isinstance(html_list2, str):
                    html_list2 = [html_list2]
                for h in html_list2:
                    combined += "\\n" + re.sub(r"<[^>]+>", " ", h)
'''
new_cf_detail = '''                detail_body = normalize_mail_body(detail)
                if detail_body:
                    combined += "\\n" + detail_body
'''
text = replace_once(text, old_cf_detail, new_cf_detail, "Cloudflare detail normalization")
old_cloudmail_body = '''            parts = []
            code_value = str(msg.get("code", "") or "").strip()
            if code_value:
                parts.append(f"verification code: {code_value}")
            for field in ("text", "content", "html", "body", "snippet"):
                value = msg.get(field)
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if isinstance(item, str) and item.strip():
                        parts.append(re.sub(r"<[^>]+>", " ", item))
            subject = str(msg.get("subject", "") or "")
            combined = "\\n".join(parts)
'''
new_cloudmail_body = '''            code_value = str(msg.get("code", "") or "").strip()
            combined = normalize_mail_body(msg)
            if code_value:
                combined = f"verification code: {code_value}\\n{combined}"
            subject = str(msg.get("subject", "") or "")
'''
text = replace_once(text, old_cloudmail_body, new_cloudmail_body, "Cloud Mail body normalization")
old_duck_body = '''            parts = []
            text_body = detail.get("text") or ""
            if text_body:
                parts.append(text_body)
            html_list = detail.get("html") or []
            for h in html_list:
                parts.append(re.sub(r"<[^>]+>", " ", h))
            combined = "\\n".join(parts)
'''
text = replace_once(text, old_duck_body, '            combined = normalize_mail_body(detail)\n', "DuckMail body normalization")
old_yyds_body = '''            parts = []
            text_body = detail.get("text") or ""
            if text_body:
                parts.append(text_body)
            html_list = detail.get("html") or []
            for h in html_list:
                parts.append(re.sub(r"<[^>]+>", " ", h))
            combined = "\\n".join(parts)
'''
text = replace_once(text, old_yyds_body, '            combined = normalize_mail_body(detail)\n', "YYDS body normalization")
write(path, text)


# Ignore pending recovery artifacts.
path = ".gitignore"
text = read(path)
if "*.pending.jsonl\n" not in text:
    text += "\n*.pending.jsonl\n*.pending.jsonl.lock\n"
write(path, text)


# Remove duplicate/overlapping registration flow tests while retaining one test per semantic boundary.
path = "tests/test_registration_flow.py"
text = read(path)
duplicate_block = '''    def test_cleanup_failure_does_not_change_success_statistics(self):
        fake = FakeOps()
        ops = fake.operations()
        base_cleanup = ops.cleanup
        def cleanup(reason):
            if "已成功" in reason:
                raise RuntimeError("cleanup failed")
            base_cleanup(reason)
        ops.cleanup = cleanup
        batch = run_batch(2, self.callbacks(), lambda *args: None, ops, cleanup_interval=1)
        self.assertEqual((batch.success_count, batch.fail_count, batch.processed_count), (2, 0, 2))

    def test_cancel_during_next_account_wait_is_normal_cancellation(self):
        fake = FakeOps()
        ops = fake.operations()
        ops.sleep = lambda seconds: (_ for _ in ()).throw(Cancelled())
        batch = run_batch(2, self.callbacks(), lambda *args: None, ops)
        self.assertTrue(batch.cancelled)
        self.assertEqual(batch.processed_count, 1)

    def test_final_cleanup_does_not_mask_original_error(self):
        fake = FakeOps()
        ops = fake.operations()
        ops.start_browser = lambda: (_ for _ in ()).throw(ValueError("original"))
        ops.cleanup = lambda reason: (_ for _ in ()).throw(RuntimeError("cleanup"))
        with self.assertRaisesRegex(ValueError, "original"):
            run_batch(1, self.callbacks(), lambda *args: None, ops)

    def test_optional_postprocessing_exceptions_become_warning(self):
        fake = FakeOps()
        ops = fake.operations()
        ops.add_tokens = lambda sso, email: (_ for _ in ()).throw(RuntimeError("pool"))
        ops.export_cpa = lambda email, password, sso: (_ for _ in ()).throw(RuntimeError("cpa"))
        batch = run_batch(1, self.callbacks(), lambda *args: None, ops)
        self.assertEqual(batch.success_count, 1)
        self.assertEqual(batch.postprocess_warning_count, 1)

'''
text = replace_once(text, duplicate_block, "", "duplicate flow tests")
write(path, text)


# Focused regression tests for the post-modularization contract.
regression_tests = '''import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_config
import browser_runtime
import cpa_export
import grok_register_ttk as app
import mail_service
import registration_browser
from cpa_xai import browser_session


class PostModularizationRegressionTests(unittest.TestCase):
    def test_signup_url_preserves_redirect(self):
        self.assertEqual(
            registration_browser.SIGNUP_URL,
            "https://accounts.x.ai/sign-up?redirect=grok-com",
        )

    def test_config_identity_survives_load(self):
        original_path = app_config.CONFIG_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                config_path = Path(directory) / "config.json"
                payload = dict(app_config.DEFAULT_CONFIG)
                payload["register_count"] = 3
                config_path.write_text(json.dumps(payload), encoding="utf-8")
                app_config.CONFIG_FILE = str(config_path)
                loaded = app.load_config()
                self.assertIs(loaded, app_config.config)
                self.assertIs(app.config, app_config.config)
                self.assertEqual(app.config["register_count"], 3)
        finally:
            app_config.CONFIG_FILE = original_path

    def test_legacy_runtime_state_assignments_are_forwarded(self):
        sentinel = object()
        original = registration_browser.page
        try:
            app.page = sentinel
            self.assertIs(registration_browser.page, sentinel)
            self.assertIs(app.page, sentinel)
        finally:
            app.page = original

    def test_gui_reset_clears_all_batch_counters(self):
        gui = app.GrokRegisterGUI.__new__(app.GrokRegisterGUI)
        gui.success_count = 1
        gui.fail_count = 2
        gui.registered_unsaved_count = 3
        gui.postprocess_warning_count = 4
        gui._reset_batch_counters()
        self.assertEqual(
            (gui.success_count, gui.fail_count, gui.registered_unsaved_count, gui.postprocess_warning_count),
            (0, 0, 0, 0),
        )

    def test_cpa_hotload_requirement_only_applies_when_export_enabled(self):
        cfg = dict(app_config.DEFAULT_CONFIG)
        cfg["cpa_copy_to_hotload"] = True
        cfg["cpa_export_enabled"] = False
        self.assertTrue(app_config.validate_run_requirements(cfg)["cpa_copy_to_hotload"])
        cfg["cpa_export_enabled"] = True
        with self.assertRaises(app_config.ConfigError):
            app_config.validate_run_requirements(cfg)

    def test_mail_body_normalizes_string_and_list_html(self):
        text = mail_service.normalize_mail_body(
            {"text": "plain", "html": "<b>one</b>"},
            {"html": ["<i>two</i>"]},
        )
        self.assertIn("plain", text)
        self.assertIn("one", text)
        self.assertIn("two", text)

    def test_cloudflare_skips_non_target_mail_without_logger(self):
        message = {
            "id": "1",
            "to": [{"address": "other@example.com"}],
            "subject": "ABC-123 xAI",
            "text": "ABC-123",
        }
        with patch.object(mail_service, "get_cloudflare_api_base", return_value="https://mail.example"), \
             patch.object(mail_service, "cloudflare_get_messages", return_value=[message]), \
             patch.object(mail_service, "cloudflare_get_message_detail") as detail, \
             patch.object(mail_service, "raise_if_cancelled", return_value=None), \
             patch.object(mail_service, "sleep_with_cancel", return_value=None), \
             patch.object(mail_service.time, "time", side_effect=[0, 0, 2, 2]):
            with self.assertRaises(Exception):
                mail_service.cloudflare_get_oai_code(
                    "token", "target@example.com", timeout=1, poll_interval=0, log_callback=None
                )
        detail.assert_not_called()

    def test_cpa_browser_session_does_not_import_main_module(self):
        source = Path(browser_session.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from grok_register_ttk", source)
        self.assertIn("from browser_runtime import create_browser_options", source)

    def test_browser_options_accept_explicit_extension_path(self):
        self.assertIn("extension_path", browser_runtime.create_browser_options.__code__.co_varnames)

    def test_cpa_export_annotations_are_python39_compatible(self):
        annotation = cpa_export.CpaExportSettings.__annotations__["hotload_dir"]
        self.assertNotIsInstance(annotation, str)


if __name__ == "__main__":
    unittest.main()
'''
write("tests/test_post_modularization_regressions.py", regression_tests)

print("post-modularization fixes applied")
