"""提供共享的 HTTP 请求、代理处理和 CloakBrowser 启动参数。"""
import os
import threading
import urllib.parse

from curl_cffi import requests
from cpa_xai.proxyutil import (
    LocalAuthProxyBridge,
    prepare_chromium_proxy,
    proxy_for_chromium,
)

_config = {}
_extension_path = ""
# Playwright Sync: one driver root per thread. Track the active adapter so CPA
# mint can supersede the registration browser on the same worker thread.
_thread_browser = threading.local()


def configure_runtime(config_ref, extension_path=""):
    global _config, _extension_path
    _config = config_ref
    _extension_path = str(extension_path or "")


def get_configured_proxy():
    return str(_config.get("proxy", "") or "").strip()


def get_proxies():
    proxy = get_configured_proxy()
    return {"http": proxy, "https": proxy} if proxy else {}


def _parse_proxy_url(proxy):
    raw = str(proxy or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    try:
        return urllib.parse.urlsplit(raw)
    except Exception:
        return None


def _safe_proxy_port(parsed):
    try:
        return parsed.port
    except Exception:
        return None


def _proxy_has_auth(proxy):
    parsed = _parse_proxy_url(proxy)
    return bool(parsed and parsed.hostname and (parsed.username is not None or parsed.password is not None))


def _strip_proxy_auth(proxy):
    raw = str(proxy or "").strip()
    parsed = _parse_proxy_url(raw)
    if not parsed or not parsed.hostname:
        return raw
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    port = _safe_proxy_port(parsed)
    netloc = "%s:%s" % (host, port) if port else host
    stripped = urllib.parse.urlunsplit((parsed.scheme or "http", netloc, parsed.path, parsed.query, parsed.fragment))
    return stripped.split("://", 1)[1] if "://" not in raw else stripped


def _proxy_endpoint_terms(proxy=None):
    parsed = _parse_proxy_url(proxy or get_configured_proxy())
    if not parsed or not parsed.hostname:
        return []
    terms = [parsed.hostname]
    port = _safe_proxy_port(parsed)
    if port:
        terms.extend(["%s:%s" % (parsed.hostname, port), "port %s" % port])
    return [item.lower() for item in terms if item]


def is_proxy_connection_error(exc):
    if not get_configured_proxy():
        return False
    err = str(exc or "").lower()
    if not err:
        return False
    if any(item in err for item in ("proxy", "tunnel", "socks")):
        return True
    markers = (
        "could not connect", "failed to connect", "connection refused",
        "connection reset", "connect error", "timed out", "timeout",
    )
    if any(item in err for item in markers):
        terms = _proxy_endpoint_terms()
        return not terms or any(term in err for term in terms)
    return False


def page_has_proxy_error(page_obj):
    try:
        url = str(getattr(page_obj, "url", "") or "")
        title = str(page_obj.run_js("return document.title || ''") or "")
        body = str(page_obj.run_js("return document.body ? document.body.innerText.slice(0, 2000) : ''") or "")
    except Exception:
        return False
    text = "%s\n%s\n%s" % (url, title, body)
    text = text.lower()
    return any(marker in text for marker in (
        "err_proxy", "proxy connection failed", "proxy server",
        "proxy authentication", "tunnel connection failed",
        "无法连接到代理服务器", "代理服务器",
    ))


def prepare_browser_proxy(use_proxy=True, log_callback=None):
    proxy = get_configured_proxy()
    if not use_proxy or not proxy:
        return "", None
    parsed = _parse_proxy_url(proxy)
    if _proxy_has_auth(proxy) and parsed and (parsed.scheme or "http").lower() not in ("http", "https"):
        stripped = _strip_proxy_auth(proxy)
        if log_callback:
            log_callback("[!] 浏览器暂不直接支持该认证代理协议，已使用去认证代理地址，失败将回退直连")
        return stripped, None
    logger = None
    if log_callback:
        logger = lambda message: log_callback("[*] 已为浏览器启动本地认证代理桥: %s" % message.split(": ", 1)[-1]) if "started authenticated proxy bridge" in message else log_callback(message)
    return prepare_chromium_proxy(proxy, log=logger)


class BrowserLaunchOptions:
    """Launch config consumed by ``launch_browser_from_options``.

    Keeps a small ChromiumOptions-like surface (headless/set_argument/add_extension)
    so call sites and tests can still shape options without DrissionPage.
    """

    def __init__(
        self,
        browser_proxy="",
        extension_path="",
        headless=False,
        humanize=True,
        geoip=None,
        args=None,
    ):
        self.browser_proxy = str(browser_proxy or "").strip()
        self.extension_path = str(extension_path or "").strip()
        self._headless = bool(headless)
        self.humanize = bool(humanize)
        # None → enable geoip automatically when a proxy is present
        self.geoip = geoip
        self.args = list(args or [])
        self.extra_kwargs = {}

    def headless(self, enabled=True):
        self._headless = bool(enabled)
        return self

    def is_headless(self) -> bool:
        return bool(self._headless)

    def set_argument(self, *parts):
        if not parts:
            return self
        if len(parts) == 1:
            flag = str(parts[0])
        elif str(parts[0]).endswith("="):
            flag = "%s%s" % (parts[0], parts[1])
        else:
            flag = "%s=%s" % (parts[0], parts[1])
        if flag and flag not in self.args:
            self.args.append(flag)
        return self

    def add_extension(self, path):
        path = str(path or "").strip()
        if path:
            self.extension_path = path
        return self

    def set_proxy(self, proxy):
        self.browser_proxy = str(proxy or "").strip()
        return self

    def auto_port(self):
        return self

    def set_timeouts(self, **_kwargs):
        return self

    def set_browser_path(self, _path):
        return self

    def to_launch_kwargs(self) -> dict:
        proxy = self.browser_proxy
        geoip = self.geoip
        if geoip is None:
            geoip = bool(proxy)
        kwargs = {
            "headless": bool(self._headless),
            "humanize": bool(self.humanize),
            "geoip": bool(geoip) if proxy else False,
        }
        if proxy:
            kwargs["proxy"] = proxy
        extensions = []
        if self.extension_path and os.path.exists(self.extension_path):
            extensions.append(self.extension_path)
        if extensions:
            kwargs["extension_paths"] = extensions
        if self.args:
            kwargs["args"] = list(self.args)
        kwargs.update(self.extra_kwargs)
        return kwargs


def apply_browser_proxy_option(options, proxy):
    if not proxy:
        return
    if hasattr(options, "set_proxy"):
        try:
            options.set_proxy(proxy)
            return
        except Exception:
            pass
    if hasattr(options, "set_argument"):
        try:
            options.set_argument("--proxy-server=%s" % proxy)
            return
        except TypeError:
            options.set_argument("--proxy-server", proxy)
            return
    raise AttributeError("当前浏览器 options 不支持设置代理")


def create_browser_options(browser_proxy="", extension_path=None):
    """Build launch options for CloakBrowser (anti-detect defaults on)."""
    effective_extension = _extension_path if extension_path is None else str(extension_path or "")
    options = BrowserLaunchOptions(
        browser_proxy=browser_proxy or "",
        extension_path=effective_extension,
        headless=False,
        humanize=True,
        geoip=None,
    )
    # Keep proxy on the options object (also used when launching without re-apply)
    if browser_proxy:
        apply_browser_proxy_option(options, browser_proxy)
    return options


def _release_thread_playwright_owners():
    """Playwright Sync API allows only one driver per thread.

    CPA mint launches a second browser while registration TabPool still holds the
    first → 'Sync API inside the asyncio loop'. Drop the current-thread owner so
    a new CloakBrowser root can start. Safe after SSO is already captured.
    """
    active = getattr(_thread_browser, "browser", None)
    if active is not None:
        try:
            active.quit()
        except Exception:
            pass
        _thread_browser.browser = None
    try:
        from tab_pool import TabPool

        if TabPool.get_browser() is not None:
            TabPool.release_tab()
    except Exception:
        pass
    try:
        import registration_browser as rb

        if getattr(rb, "browser", None) is not None or getattr(rb, "page", None) is not None:
            rb.browser = None
            rb.page = None
    except Exception:
        pass


def launch_browser_from_options(options=None, **overrides):
    """Launch CloakBrowser and return a BrowserAdapter (DrissionPage-shaped)."""
    from cloakbrowser import launch
    from browser_adapter import BrowserAdapter

    if options is None:
        options = create_browser_options()
    if isinstance(options, BrowserLaunchOptions):
        launch_kwargs = options.to_launch_kwargs()
    elif isinstance(options, dict):
        launch_kwargs = dict(options)
    else:
        # Unknown object: try to read common attributes
        launch_kwargs = BrowserLaunchOptions(
            browser_proxy=str(getattr(options, "browser_proxy", "") or ""),
            extension_path=str(getattr(options, "extension_path", "") or ""),
            headless=bool(getattr(options, "_headless", False)),
            humanize=bool(getattr(options, "humanize", True)),
        ).to_launch_kwargs()
    launch_kwargs.update(overrides)
    # Anti-detect: humanize on by default unless caller disables it.
    launch_kwargs.setdefault("humanize", True)
    launch_kwargs.setdefault("headless", False)
    proxy = launch_kwargs.get("proxy") or ""
    if proxy and "geoip" not in overrides:
        launch_kwargs.setdefault("geoip", True)

    def _launch_once():
        pw_browser = launch(**launch_kwargs)
        context = pw_browser.new_context()
        adapter = BrowserAdapter(pw_browser, context=context)
        _thread_browser.browser = adapter
        return adapter

    # Preemptively free any same-thread Playwright owner (registration → CPA mint).
    if getattr(_thread_browser, "browser", None) is not None or _tab_pool_has_browser():
        _release_thread_playwright_owners()

    try:
        return _launch_once()
    except Exception as exc:
        message = str(exc or "")
        nested = (
            "asyncio loop" in message
            or "Sync API" in message
            or "another synchronous" in message.lower()
        )
        if not nested:
            raise
        _release_thread_playwright_owners()
        return _launch_once()


def _tab_pool_has_browser() -> bool:
    try:
        from tab_pool import TabPool

        return TabPool.get_browser() is not None
    except Exception:
        return False


def _build_request_kwargs(**kwargs):
    request_kwargs = dict(kwargs)
    proxies = request_kwargs.pop("proxies", None)
    if proxies is None:
        proxies = get_proxies()
    if proxies:
        request_kwargs["proxies"] = proxies
    request_kwargs.setdefault("timeout", 15)
    return request_kwargs


def http_get(url, **kwargs):
    request_kwargs = _build_request_kwargs(**kwargs)
    try:
        return requests.get(url, **request_kwargs)
    except Exception as exc:
        if is_proxy_connection_error(exc):
            direct = dict(request_kwargs)
            direct.pop("proxies", None)
            return requests.get(url, **direct)
        raise


def http_post(url, **kwargs):
    request_kwargs = _build_request_kwargs(**kwargs)
    try:
        return requests.post(url, **request_kwargs)
    except Exception as exc:
        if is_proxy_connection_error(exc):
            direct = dict(request_kwargs)
            direct.pop("proxies", None)
            return requests.post(url, **direct)
        raise
