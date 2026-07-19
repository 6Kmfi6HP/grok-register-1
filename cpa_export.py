"""在注册成功后可选生成 CPA xAI OIDC 凭证、复制到热加载目录，并上传到远端 CPA。"""
from dataclasses import dataclass
import importlib.util
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from app_paths import default_cpa_auth_dir, get_app_root, get_resource_root


def _writable_root() -> Path:
    """User-writable project root (next to exe when frozen)."""
    return Path(get_app_root())


def _bundle_root() -> Path:
    """Read-only resource root for bundled package code."""
    return Path(get_resource_root())


# Back-compat aliases for any external imports of these names.
_ROOT = _writable_root()
_DEFAULT_AUTH_DIR = Path(default_cpa_auth_dir())


@dataclass(frozen=True)
class CpaExportSettings:
    enabled: bool
    auth_dir: Path
    hotload_dir: Optional[Path]
    copy_to_hotload: bool
    proxy: str
    headless: bool
    mint_timeout: float
    request_timeout: float
    poll_timeout: float
    base_url: str
    force_standalone: bool
    cookie_inject: bool
    tools_dir: str
    auto_upload_remote: bool
    remote_base: str
    management_key: str

    @classmethod
    def from_config(cls, config):
        cfg = dict(config or {})
        root = _writable_root()
        auth_dir = Path(cfg.get("cpa_auth_dir") or default_cpa_auth_dir()).expanduser()
        if not auth_dir.is_absolute():
            auth_dir = (root / auth_dir).resolve()
        hotload_value = str(cfg.get("cpa_hotload_dir") or "").strip()
        hotload_dir = Path(hotload_value).expanduser() if hotload_value else None
        if hotload_dir is not None and not hotload_dir.is_absolute():
            hotload_dir = (root / hotload_dir).resolve()
        management_key = str(
            cfg.get("cpa_management_key") or cfg.get("cpa_api_key") or ""
        ).strip()
        return cls(
            enabled=bool(cfg.get("cpa_export_enabled", True)),
            auth_dir=auth_dir,
            hotload_dir=hotload_dir,
            copy_to_hotload=bool(cfg.get("cpa_copy_to_hotload", False)),
            proxy=str(cfg.get("cpa_proxy") or cfg.get("proxy") or "").strip(),
            headless=bool(cfg.get("cpa_headless", False)),
            mint_timeout=float(cfg.get("cpa_mint_timeout_sec") or 300),
            request_timeout=float(cfg.get("cpa_oidc_request_timeout_sec") or 15),
            poll_timeout=float(cfg.get("cpa_oidc_poll_timeout_sec") or 15),
            base_url=str(cfg.get("cpa_base_url") or "https://cli-chat-proxy.grok.com/v1").strip(),
            force_standalone=bool(cfg.get("cpa_force_standalone", True)),
            cookie_inject=bool(cfg.get("cpa_mint_cookie_inject", True)),
            tools_dir=str(cfg.get("api_reverse_tools") or "").strip(),
            auto_upload_remote=bool(cfg.get("cpa_auto_upload_remote", False)),
            remote_base=str(cfg.get("cpa_remote_base") or "").strip().rstrip("/"),
            management_key=management_key,
        )


def upload_auth_to_remote_cpa(
    auth_path,
    *,
    remote_base,
    management_key,
    log_callback: Optional[Callable[[str], None]] = None,
    timeout_sec: float = 30,
):
    """Upload a local xai-*.json to CLIProxyAPI management auth-files."""
    log = log_callback or (lambda message: None)
    base = str(remote_base or "").strip().rstrip("/")
    key = str(management_key or "").strip()
    source = Path(auth_path)
    if not base or not key:
        return {"ok": False, "skipped": True, "reason": "remote_base/management_key missing"}
    if not source.is_file():
        return {"ok": False, "error": "auth file missing: %s" % source}

    url = "%s/v0/management/auth-files?name=%s" % (base, urllib.parse.quote(source.name))
    body = source.read_bytes()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer %s" % key,
            "X-Management-Key": key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {"status": "ok"}
            except json.JSONDecodeError:
                payload = {"status": "ok", "raw": raw}
            log("[cpa] remote upload ok -> %s name=%s" % (base, source.name))
            return {"ok": True, "remote": base, "name": source.name, "response": payload}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        log("[cpa] remote upload HTTP %s: %s" % (exc.code, detail[:300]))
        return {"ok": False, "error": "HTTP %s: %s" % (exc.code, detail[:300])}
    except Exception as exc:
        log("[cpa] remote upload failed: %s" % exc)
        return {"ok": False, "error": str(exc)}


def _load_mint_and_export(tools_dir=""):
    tools_value = str(tools_dir or "").strip()
    if not tools_value:
        from cpa_xai import mint_and_export
        return mint_and_export
    tools = Path(tools_value).expanduser().resolve()
    package = tools if tools.name == "cpa_xai" else tools / "cpa_xai"
    init_path = package / "__init__.py"
    if package.resolve() in {
        (_bundle_root() / "cpa_xai").resolve(),
        (_writable_root() / "cpa_xai").resolve(),
    }:
        from cpa_xai import mint_and_export
        return mint_and_export
    if not init_path.is_file():
        raise ImportError("cpa_xai package not found under %s" % tools)
    module_name = "_external_cpa_xai_%s" % abs(hash(str(package)))
    spec = importlib.util.spec_from_file_location(
        module_name,
        str(init_path),
        submodule_search_locations=[str(package)],
    )
    if spec is None or spec.loader is None:
        raise ImportError("unable to load cpa_xai from %s" % package)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module.mint_and_export


def export_cookies_from_page(page):
    if page is None:
        return []
    cookies = None
    for getter in (
        lambda: page.cookies(all_domains=True, all_info=True),
        lambda: page.cookies(all_domains=True),
        lambda: page.cookies(),
    ):
        try:
            cookies = getter()
            if cookies:
                break
        except TypeError:
            continue
        except Exception:
            continue
    if not cookies:
        try:
            browser = getattr(page, "browser", None)
            if browser is not None:
                cookies = browser.cookies()
        except Exception:
            cookies = None
    return [item for item in cookies if isinstance(item, dict)] if isinstance(cookies, list) else []


def _normalize_result(result, email=""):
    value = dict(result or {})
    value.setdefault("ok", False)
    value.setdefault("skipped", False)
    value.setdefault("email", str(email or ""))
    value.setdefault("error", None)
    return value


def export_cpa_xai_for_account(email, password, page=None, cookies=None, sso=None,
                               config=None, log_callback=None, cancel_callback=None):
    settings = CpaExportSettings.from_config(config)
    log = log_callback or (lambda message: None)
    if not settings.enabled:
        return _normalize_result({"ok": False, "skipped": True, "reason": "disabled"}, email)
    try:
        mint_and_export = _load_mint_and_export(settings.tools_dir)
    except Exception as exc:
        log("[cpa] import cpa_xai failed: %s" % exc)
        return _normalize_result({"ok": False, "error": "import: %s" % exc}, email)

    use_cookies = cookies
    if use_cookies is None and settings.cookie_inject and page is not None:
        use_cookies = export_cookies_from_page(page)
    if not settings.cookie_inject:
        use_cookies = None
    elif sso:
        base = list(use_cookies) if isinstance(use_cookies, list) else []
        sso_value = str(sso).strip()
        for cookie_name in ("sso", "sso-rw"):
            for domain in (".x.ai", "accounts.x.ai", ".accounts.x.ai", "auth.x.ai", ".auth.x.ai", "grok.com", ".grok.com"):
                base.append({"name": cookie_name, "value": sso_value, "domain": domain,
                             "path": "/", "secure": True, "httpOnly": True})
        use_cookies = base

    settings.auth_dir.mkdir(parents=True, exist_ok=True)
    log("[cpa] mint OIDC for %s -> %s" % (email, settings.auth_dir))
    result = mint_and_export(
        email=email, password=password, auth_dir=settings.auth_dir,
        page=None if settings.force_standalone else page,
        proxy=settings.proxy or None, headless=settings.headless,
        base_url=settings.base_url, browser_timeout_sec=settings.mint_timeout,
        force_standalone=settings.force_standalone, cookies=use_cookies,
        reuse_browser=True, recycle_every=15,
        log=lambda message: log("[cpa] %s" % message), cancel=cancel_callback,
        request_timeout_sec=settings.request_timeout,
        poll_timeout_sec=settings.poll_timeout,
    )
    result = _normalize_result(result, email)
    if result.get("ok") and result.get("path") and settings.copy_to_hotload and settings.hotload_dir:
        try:
            settings.hotload_dir.mkdir(parents=True, exist_ok=True)
            source = Path(result["path"])
            target = settings.hotload_dir / source.name
            shutil.copy2(str(source), str(target))
            try:
                os.chmod(str(target), 0o600)
            except Exception:
                pass
            result["hotload_path"] = str(target)
            log("[cpa] hotload copy -> %s" % target)
        except Exception as exc:
            result["cpa_copy_error"] = str(exc)
            result["warning"] = True
            result["partial"] = True
            log("[cpa] hotload copy failed: %s" % exc)
    if result.get("ok") and result.get("path") and settings.auto_upload_remote:
        remote = upload_auth_to_remote_cpa(
            result["path"],
            remote_base=settings.remote_base,
            management_key=settings.management_key,
            log_callback=log,
        )
        result["remote_upload"] = remote
        if remote.get("skipped"):
            result["remote_upload_error"] = remote.get("reason") or "remote upload skipped"
            result["warning"] = True
            result["partial"] = True
            log("[cpa] remote upload skipped: %s" % result["remote_upload_error"])
        elif not remote.get("ok"):
            result["remote_upload_error"] = remote.get("error") or "remote upload failed"
            result["warning"] = True
            result["partial"] = True
    if not result.get("ok"):
        fail_path = settings.auth_dir / "cpa_auth_failed.txt"
        try:
            with open(str(fail_path), "a", encoding="utf-8") as handle:
                handle.write("%s----%s----%s\n" % (email, result.get("error") or "unknown", int(time.time())))
        except Exception as exc:
            log("[cpa] failed to persist failure record: %s" % exc)
    return result
