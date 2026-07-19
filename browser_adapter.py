"""Thin Playwright adapters that keep DrissionPage-shaped call sites working.

CloakBrowser returns stock Playwright Browser/Page objects. Registration and CPA
code historically used DrissionPage (run_js/ele/get/cookies/actions). This module
wraps Playwright so those call sites need only minimal edits.
"""
from __future__ import annotations

from typing import Any, Optional


class PageDisconnectedError(Exception):
    """Raised when the underlying Playwright page/browser is gone."""


def _is_disconnected(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    markers = (
        "target closed",
        "target page, context or browser has been closed",
        "browser has been closed",
        "context has been closed",
        "connection closed",
        "page crashed",
        "execution context was destroyed",
    )
    return any(marker in text for marker in markers)


def _raise_translated(exc: BaseException):
    if _is_disconnected(exc):
        raise PageDisconnectedError(str(exc)) from exc
    raise exc


def _parse_locator(locator: str) -> str:
    """Map DrissionPage locator strings to Playwright selectors."""
    raw = str(locator or "").strip()
    if not raw:
        return "css=*"
    lower = raw.lower()
    if lower.startswith("css:"):
        return raw[4:].strip()
    if lower.startswith("xpath:"):
        return "xpath=" + raw.split(":", 1)[1]
    if lower.startswith("text:"):
        return "text=" + raw.split(":", 1)[1]
    if lower.startswith("tag:"):
        return raw.split(":", 1)[1].strip()
    if raw.startswith("@"):
        # @name=value / @id=foo
        body = raw[1:]
        if "=" in body:
            attr, value = body.split("=", 1)
            value = value.strip().strip("'\"")
            return f'[{attr.strip()}="{value}"]'
        return f"[{body}]"
    if raw.startswith("//") or raw.startswith("(//"):
        return "xpath=" + raw
    return raw


def _run_js_on(evaluate, script: str, args: tuple) -> Any:
    """Execute DrissionPage-style JS (supports ``return`` + ``arguments[n]``)."""
    code = str(script or "")
    payload = list(args)
    try:
        return evaluate(
            """([code, args]) => {
                const fn = new Function(code);
                return fn.apply(null, args || []);
            }""",
            [code, payload],
        )
    except Exception as exc:
        # Some callers pass expressions without return/braces.
        try:
            return evaluate(
                """([code, args]) => {
                    const fn = new Function('return (' + code + ')');
                    return fn.apply(null, args || []);
                }""",
                [code, payload],
            )
        except Exception:
            _raise_translated(exc)


class _CookieAPI:
    def __init__(self, owner: "BrowserAdapter | PageAdapter"):
        self._owner = owner

    def __call__(self, cookies=None):
        if cookies is None:
            return
        self._owner._set_cookies(cookies)

    def clear(self) -> None:
        self._owner._clear_cookies()

    def remove(self, cookie) -> None:
        self._owner._remove_cookie(cookie)


class _SetAPI:
    def __init__(self, owner: "BrowserAdapter | PageAdapter"):
        self.cookies = _CookieAPI(owner)


class _WaitAPI:
    def __init__(self, page: "PageAdapter"):
        self._page = page

    def doc_loaded(self, timeout: float = 30) -> None:
        self._page._wait_doc_loaded(timeout=timeout)


class _ActionsAPI:
    def __init__(self, page: "PageAdapter"):
        self._page = page

    def type(self, keys, interval: float = 0.0) -> None:
        self._page._type_keys(keys, interval=interval)


class ElementAdapter:
    """Minimal DrissionPage-like element wrapper over a Playwright Locator."""

    def __init__(self, locator, page: "PageAdapter"):
        self._locator = locator
        self._page = page

    def _handle(self):
        try:
            return self._locator.element_handle(timeout=2000)
        except Exception as exc:
            _raise_translated(exc)

    def click(self, by_js: bool = False, **_kwargs) -> None:
        try:
            if by_js:
                self._locator.evaluate("el => el.click()")
            else:
                self._locator.click(timeout=5000)
        except Exception as exc:
            _raise_translated(exc)

    def input(self, value, clear: bool = False, **_kwargs) -> None:
        text = "" if value is None else str(value)
        try:
            if clear:
                self._locator.fill("")
            # Prefer fill for reliability; humanize still applies via locator API.
            self._locator.fill(text, timeout=5000)
        except Exception:
            try:
                if clear:
                    self._locator.evaluate(
                        """el => {
                            el.focus();
                            el.value = '';
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                        }"""
                    )
                self._locator.type(text, delay=20)
            except Exception as exc:
                _raise_translated(exc)

    def clear(self) -> None:
        try:
            self._locator.fill("")
        except Exception:
            try:
                self._locator.evaluate(
                    """el => {
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value')?.set;
                        if (setter) setter.call(el, '');
                        else el.value = '';
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }"""
                )
            except Exception as exc:
                _raise_translated(exc)

    @property
    def value(self) -> str:
        try:
            return str(self._locator.input_value(timeout=1000) or "")
        except Exception:
            try:
                return str(self._locator.evaluate("el => el.value || ''") or "")
            except Exception:
                return ""

    @property
    def text(self) -> str:
        try:
            return str(self._locator.inner_text(timeout=1000) or "")
        except Exception:
            try:
                return str(self._locator.text_content(timeout=1000) or "")
            except Exception:
                return ""

    def parent(self) -> Optional["ElementAdapter"]:
        try:
            parent_loc = self._locator.locator("xpath=..")
            if parent_loc.count() == 0:
                return None
            return ElementAdapter(parent_loc.first, self._page)
        except Exception:
            return None

    @property
    def shadow_root(self) -> Optional["ElementAdapter"]:
        """Best-effort open-shadow access (closed shadow returns None)."""
        try:
            handle = self._handle()
            if handle is None:
                return None
            shadow = handle.evaluate_handle("el => el.shadowRoot")
            if shadow is None:
                return None
            # Represent the shadow host locator; pierce with Playwright CSS.
            # Subsequent .ele() uses page.locator from host >> selector via evaluate.
            return _ShadowRootAdapter(handle, self._page)
        except Exception:
            return None

    def ele(self, locator, timeout: float = 0.5) -> Optional["ElementAdapter"]:
        sel = _parse_locator(locator)
        try:
            child = self._locator.locator(sel)
            wait_ms = max(int(float(timeout) * 1000), 0)
            if wait_ms > 0:
                try:
                    child.first.wait_for(state="attached", timeout=wait_ms)
                except Exception:
                    if child.count() == 0:
                        return None
            elif child.count() == 0:
                return None
            return ElementAdapter(child.first, self._page)
        except Exception:
            return None

    def run_js(self, script: str, *args):
        try:
            return self._locator.evaluate(
                """(el, payload) => {
                    const code = payload[0];
                    const fnArgs = payload[1] || [];
                    const fn = new Function(code);
                    return fn.apply(el, fnArgs);
                }""",
                [str(script or ""), list(args)],
            )
        except Exception as exc:
            _raise_translated(exc)


class _ShadowRootAdapter:
    def __init__(self, host_handle, page: "PageAdapter"):
        self._host = host_handle
        self._page = page

    def ele(self, locator, timeout: float = 0.5) -> Optional[ElementAdapter]:
        sel = _parse_locator(locator)
        # query inside open shadow root
        try:
            found = self._host.evaluate(
                """(host, selector) => {
                    const root = host.shadowRoot;
                    if (!root) return null;
                    const node = root.querySelector(selector);
                    if (!node) return null;
                    // mark node for later retrieval is hard; return outerHTML signature
                    return true;
                }""",
                sel,
            )
            if not found:
                return None
            # Playwright can pierce open shadow DOM from page root selectors.
            # Use host element + pierce: rebuild locator via page evaluation click path.
            # Fallback: wrap a synthetic element that only supports click/run_js via host.
            return _ShadowElementAdapter(self._host, sel, self._page)
        except Exception:
            return None


class _ShadowElementAdapter(ElementAdapter):
    def __init__(self, host_handle, selector: str, page: "PageAdapter"):
        self._host = host_handle
        self._selector = selector
        self._page = page
        self._locator = None

    def click(self, by_js: bool = False, **_kwargs) -> None:
        try:
            self._host.evaluate(
                """(host, selector) => {
                    const root = host.shadowRoot;
                    if (!root) return false;
                    const node = root.querySelector(selector);
                    if (!node) return false;
                    node.click();
                    return true;
                }""",
                self._selector,
            )
        except Exception as exc:
            _raise_translated(exc)

    def ele(self, locator, timeout: float = 0.5) -> Optional["ElementAdapter"]:
        sel = _parse_locator(locator)
        combined = f"{self._selector} {sel}".strip()
        try:
            ok = self._host.evaluate(
                """(host, selector) => {
                    const root = host.shadowRoot;
                    if (!root) return false;
                    // nested open shadow
                    const first = root.querySelector(arguments[1] || selector);
                    return !!first;
                }""",
                combined,
            )
            if not ok:
                # try nested shadow for turnstile-style body.shadowRoot
                nested = self._host.evaluate(
                    """(host, outerSel, innerSel) => {
                        const root = host.shadowRoot;
                        if (!root) return false;
                        const mid = root.querySelector(outerSel);
                        if (!mid) return false;
                        const sr = mid.shadowRoot;
                        if (sr) return !!sr.querySelector(innerSel);
                        return !!mid.querySelector(innerSel);
                    }""",
                    self._selector,
                    sel,
                )
                if not nested:
                    return None
                return _NestedShadowElementAdapter(self._host, self._selector, sel, self._page)
            return _ShadowElementAdapter(self._host, combined, self._page)
        except Exception:
            return None

    def run_js(self, script: str, *args):
        try:
            return self._host.evaluate(
                """(host, payload) => {
                    const selector = payload[0];
                    const code = payload[1];
                    const args = payload[2] || [];
                    const root = host.shadowRoot;
                    if (!root) return null;
                    const node = root.querySelector(selector);
                    if (!node) return null;
                    // Prefer contentWindow for iframe
                    if (node.tagName === 'IFRAME' && node.contentWindow) {
                        try {
                            const fn = new node.contentWindow.Function(code);
                            return fn.apply(node.contentWindow, args);
                        } catch (e) {}
                    }
                    const fn = new Function(code);
                    return fn.apply(node, args);
                }""",
                [self._selector, str(script or ""), list(args)],
            )
        except Exception as exc:
            _raise_translated(exc)

    @property
    def shadow_root(self):
        return _IframeOrNestedShadow(self._host, self._selector, self._page)


class _NestedShadowElementAdapter(_ShadowElementAdapter):
    def __init__(self, host_handle, outer_sel: str, inner_sel: str, page: "PageAdapter"):
        self._host = host_handle
        self._outer = outer_sel
        self._inner = inner_sel
        self._page = page
        self._selector = inner_sel

    def click(self, by_js: bool = False, **_kwargs) -> None:
        try:
            self._host.evaluate(
                """(host, outerSel, innerSel) => {
                    const root = host.shadowRoot;
                    if (!root) return false;
                    const mid = root.querySelector(outerSel);
                    if (!mid) return false;
                    const sr = mid.shadowRoot;
                    const node = sr ? sr.querySelector(innerSel) : mid.querySelector(innerSel);
                    if (!node) return false;
                    node.click();
                    return true;
                }""",
                self._outer,
                self._inner,
            )
        except Exception as exc:
            _raise_translated(exc)


class _IframeOrNestedShadow:
    def __init__(self, host_handle, iframe_selector: str, page: "PageAdapter"):
        self._host = host_handle
        self._iframe_sel = iframe_selector
        self._page = page

    def ele(self, locator, timeout: float = 0.5) -> Optional[ElementAdapter]:
        sel = _parse_locator(locator)
        try:
            ok = self._host.evaluate(
                """(host, iframeSel, innerSel) => {
                    const root = host.shadowRoot;
                    if (!root) return false;
                    const iframe = root.querySelector(iframeSel);
                    if (!iframe) return false;
                    try {
                        const doc = iframe.contentDocument || iframe.contentWindow?.document;
                        if (!doc) return false;
                        const body = doc.querySelector(innerSel) || doc.body;
                        return !!body;
                    } catch (e) {
                        return false;
                    }
                }""",
                self._iframe_sel,
                sel,
            )
            if not ok:
                return None
            return _IframeBodyAdapter(self._host, self._iframe_sel, sel, self._page)
        except Exception:
            return None


class _IframeBodyAdapter(_ShadowElementAdapter):
    def __init__(self, host_handle, iframe_sel: str, body_sel: str, page: "PageAdapter"):
        self._host = host_handle
        self._iframe_sel = iframe_sel
        self._body_sel = body_sel
        self._page = page
        self._selector = body_sel

    @property
    def shadow_root(self):
        return _DeepShadowFromIframe(self._host, self._iframe_sel, self._body_sel, self._page)

    def ele(self, locator, timeout: float = 0.5):
        sel = _parse_locator(locator)
        return _IframeDeepElement(self._host, self._iframe_sel, self._body_sel, sel, self._page)


class _DeepShadowFromIframe:
    def __init__(self, host, iframe_sel, body_sel, page):
        self._host = host
        self._iframe_sel = iframe_sel
        self._body_sel = body_sel
        self._page = page

    def ele(self, locator, timeout: float = 0.5):
        sel = _parse_locator(locator)
        return _IframeDeepElement(self._host, self._iframe_sel, self._body_sel, sel, self._page)


class _IframeDeepElement(_ShadowElementAdapter):
    def __init__(self, host, iframe_sel, body_sel, target_sel, page):
        self._host = host
        self._iframe_sel = iframe_sel
        self._body_sel = body_sel
        self._target_sel = target_sel
        self._page = page
        self._selector = target_sel

    def click(self, by_js: bool = False, **_kwargs) -> None:
        try:
            self._host.evaluate(
                """(host, iframeSel, bodySel, targetSel) => {
                    const root = host.shadowRoot;
                    if (!root) return false;
                    const iframe = root.querySelector(iframeSel);
                    if (!iframe) return false;
                    const doc = iframe.contentDocument || iframe.contentWindow?.document;
                    if (!doc) return false;
                    let scope = doc.querySelector(bodySel) || doc.body;
                    if (!scope) return false;
                    // body shadowRoot (turnstile)
                    if (scope.shadowRoot) scope = scope.shadowRoot;
                    const node = scope.querySelector ? scope.querySelector(targetSel) : null;
                    if (!node) return false;
                    node.click();
                    return true;
                }""",
                self._iframe_sel,
                self._body_sel,
                self._target_sel,
            )
        except Exception as exc:
            _raise_translated(exc)

    def run_js(self, script: str, *args):
        try:
            return self._host.evaluate(
                """(host, payload) => {
                    const iframeSel = payload[0];
                    const code = payload[1];
                    const args = payload[2] || [];
                    const root = host.shadowRoot;
                    if (!root) return null;
                    const iframe = root.querySelector(iframeSel);
                    if (!iframe || !iframe.contentWindow) return null;
                    const fn = new iframe.contentWindow.Function(code);
                    return fn.apply(iframe.contentWindow, args);
                }""",
                [self._iframe_sel, str(script or ""), list(args)],
            )
        except Exception as exc:
            _raise_translated(exc)


class PageAdapter:
    """DrissionPage-like tab/page wrapper over Playwright Page."""

    def __init__(self, page, browser: "BrowserAdapter", tab_id: str = ""):
        self._page = page
        self._browser = browser
        self._tab_id = tab_id or f"tab-{id(page)}"
        self.set = _SetAPI(self)
        self.wait = _WaitAPI(self)
        self.actions = _ActionsAPI(self)

    @property
    def browser(self) -> "BrowserAdapter":
        return self._browser

    @property
    def tab_id(self) -> str:
        return self._tab_id

    @property
    def url(self) -> str:
        try:
            return str(self._page.url or "")
        except Exception as exc:
            if _is_disconnected(exc):
                raise PageDisconnectedError(str(exc)) from exc
            return ""

    @property
    def html(self) -> str:
        try:
            return str(self._page.content() or "")
        except Exception as exc:
            if _is_disconnected(exc):
                raise PageDisconnectedError(str(exc)) from exc
            return ""

    def get(self, url: str, timeout: Optional[float] = None, **_kwargs) -> None:
        kwargs = {"wait_until": "domcontentloaded"}
        if timeout is not None:
            kwargs["timeout"] = int(float(timeout) * 1000)
        try:
            self._page.goto(str(url), **kwargs)
        except Exception as exc:
            _raise_translated(exc)

    def run_js(self, script: str, *args):
        try:
            return _run_js_on(self._page.evaluate, script, args)
        except PageDisconnectedError:
            raise
        except Exception as exc:
            _raise_translated(exc)

    def ele(self, locator, timeout: float = 1.0) -> Optional[ElementAdapter]:
        sel = _parse_locator(locator)
        try:
            loc = self._page.locator(sel)
            wait_ms = max(int(float(timeout) * 1000), 0)
            if wait_ms > 0:
                try:
                    loc.first.wait_for(state="attached", timeout=wait_ms)
                except Exception:
                    try:
                        if loc.count() == 0:
                            return None
                    except Exception:
                        return None
            else:
                try:
                    if loc.count() == 0:
                        return None
                except Exception:
                    return None
            return ElementAdapter(loc.first, self)
        except Exception as exc:
            if _is_disconnected(exc):
                raise PageDisconnectedError(str(exc)) from exc
            return None

    def cookies(self, all_domains: bool = True, all_info: bool = True):
        try:
            return list(self._browser._context.cookies())
        except Exception as exc:
            if _is_disconnected(exc):
                raise PageDisconnectedError(str(exc)) from exc
            return []

    def get_screenshot(self, path: Optional[str] = None, name: Optional[str] = None,
                       full_page: bool = False, **_kwargs):
        target = path or name
        try:
            if target:
                return self._page.screenshot(path=str(target), full_page=bool(full_page))
            return self._page.screenshot(full_page=bool(full_page))
        except Exception as exc:
            _raise_translated(exc)

    def close(self) -> None:
        try:
            self._page.close()
        except Exception:
            pass
        self._browser._forget_tab(self)

    def _wait_doc_loaded(self, timeout: float = 30) -> None:
        try:
            self._page.wait_for_load_state(
                "domcontentloaded", timeout=int(float(timeout) * 1000)
            )
        except Exception as exc:
            if _is_disconnected(exc):
                raise PageDisconnectedError(str(exc)) from exc

    def _type_keys(self, keys, interval: float = 0.0) -> None:
        # DrissionPage uses \ue003 for Backspace (WebDriver keys).
        text = str(keys or "")
        delay = max(int(float(interval or 0) * 1000), 0)
        try:
            if text and set(text) == {"\ue003"}:
                for _ in text:
                    self._page.keyboard.press("Backspace", delay=delay)
                return
            # Expand any embedded backspace chars then type remainder.
            if "\ue003" in text:
                for ch in text:
                    if ch == "\ue003":
                        self._page.keyboard.press("Backspace", delay=delay)
                    else:
                        self._page.keyboard.type(ch, delay=delay)
                return
            self._page.keyboard.type(text, delay=delay)
        except Exception as exc:
            _raise_translated(exc)

    def _set_cookies(self, cookies) -> None:
        self._browser._set_cookies(cookies)

    def _clear_cookies(self) -> None:
        self._browser._clear_cookies()

    def _remove_cookie(self, cookie) -> None:
        self._browser._remove_cookie(cookie)


class BrowserAdapter:
    """DrissionPage Chromium-like wrapper over Playwright Browser + one Context."""

    def __init__(self, browser, context=None, user_data_path: str = ""):
        self._browser = browser
        self._user_data_path = user_data_path or ""
        self._tabs: list[PageAdapter] = []
        self._closed = False
        if context is not None:
            self._context = context
        else:
            self._context = browser.new_context()
        # Wrap existing pages (usually none) or create first tab.
        for page in list(self._context.pages):
            self._tabs.append(PageAdapter(page, self))
        if not self._tabs:
            self.new_tab()
        self.set = _SetAPI(self)

    @property
    def user_data_path(self) -> str:
        return self._user_data_path

    @property
    def latest_tab(self) -> PageAdapter:
        if not self._tabs:
            return self.new_tab()
        return self._tabs[-1]

    @property
    def tab_ids(self) -> list:
        self._sync_tabs()
        return [tab.tab_id for tab in self._tabs]

    def get_tabs(self) -> list:
        self._sync_tabs()
        return list(self._tabs)

    def get_tab(self, tab_id=None) -> PageAdapter:
        self._sync_tabs()
        if not self._tabs:
            return self.new_tab()
        if tab_id is None:
            return self._tabs[0]
        if isinstance(tab_id, int):
            if 0 <= tab_id < len(self._tabs):
                return self._tabs[tab_id]
            return self._tabs[-1]
        for tab in self._tabs:
            if tab.tab_id == tab_id:
                return tab
        # Fallback: treat unknown id as latest
        return self._tabs[-1]

    def new_tab(self, url: Optional[str] = None) -> PageAdapter:
        try:
            page = self._context.new_page()
        except Exception as exc:
            _raise_translated(exc)
        tab = PageAdapter(page, self)
        self._tabs.append(tab)
        if url:
            tab.get(url)
        return tab

    def cookies(self, all_domains: bool = True, all_info: bool = True):
        try:
            return list(self._context.cookies())
        except Exception:
            return []

    def quit(self, del_data: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._context.close()
        except Exception:
            pass
        try:
            # CloakBrowser patches close() to stop Playwright as well.
            self._browser.close()
        except Exception:
            pass
        self._tabs.clear()
        try:
            import browser_runtime as br

            if getattr(br._thread_browser, "browser", None) is self:
                br._thread_browser.browser = None
        except Exception:
            pass

    def close(self) -> None:
        self.quit()

    def _forget_tab(self, tab: PageAdapter) -> None:
        self._tabs = [item for item in self._tabs if item is not tab]

    def _sync_tabs(self) -> None:
        """Drop closed pages; adopt any unexpected new pages in the context."""
        live = []
        known_pages = {id(tab._page): tab for tab in self._tabs}
        try:
            context_pages = list(self._context.pages)
        except Exception:
            context_pages = []
        for page in context_pages:
            existing = known_pages.get(id(page))
            if existing is not None:
                live.append(existing)
            else:
                live.append(PageAdapter(page, self))
        self._tabs = live

    def _normalize_cookie(self, cookie: dict) -> Optional[dict]:
        if not isinstance(cookie, dict):
            return None
        name = cookie.get("name") or cookie.get("Name")
        value = cookie.get("value") or cookie.get("Value")
        if not name or value is None:
            return None
        item = {
            "name": str(name),
            "value": str(value),
            "domain": str(cookie.get("domain") or cookie.get("Domain") or ""),
            "path": str(cookie.get("path") or cookie.get("Path") or "/"),
        }
        if not item["domain"]:
            # Playwright requires domain or url
            item["url"] = "https://accounts.x.ai/"
        for src, dst in (
            ("expires", "expires"),
            ("expiry", "expires"),
            ("httpOnly", "httpOnly"),
            ("secure", "secure"),
            ("sameSite", "sameSite"),
        ):
            if src in cookie and cookie[src] is not None:
                val = cookie[src]
                if dst == "expires":
                    try:
                        val = float(val)
                    except Exception:
                        continue
                if dst == "sameSite":
                    text = str(val)
                    # Playwright expects Strict/Lax/None
                    mapping = {
                        "strict": "Strict",
                        "lax": "Lax",
                        "none": "None",
                        "no_restriction": "None",
                    }
                    val = mapping.get(text.lower(), text)
                    if val not in ("Strict", "Lax", "None"):
                        continue
                item[dst] = val
        return item

    def _set_cookies(self, cookies) -> None:
        items = cookies
        if isinstance(cookies, dict) and "name" in cookies:
            items = [cookies]
        if not isinstance(items, (list, tuple)):
            return
        payload = []
        for cookie in items:
            normalized = self._normalize_cookie(cookie) if isinstance(cookie, dict) else None
            if normalized:
                payload.append(normalized)
        if payload:
            try:
                self._context.add_cookies(payload)
            except Exception:
                # Retry one-by-one for partial success
                for item in payload:
                    try:
                        self._context.add_cookies([item])
                    except Exception:
                        pass

    def _clear_cookies(self) -> None:
        try:
            self._context.clear_cookies()
        except Exception:
            pass

    def _remove_cookie(self, cookie) -> None:
        # Playwright has no single-cookie remove; clear+re-add remainder is heavy.
        # Best-effort: clear all when asked to remove (session cleanup paths).
        try:
            if isinstance(cookie, dict):
                name = cookie.get("name")
                domain = cookie.get("domain")
                path = cookie.get("path") or "/"
                remaining = [
                    c
                    for c in self._context.cookies()
                    if not (
                        c.get("name") == name
                        and (not domain or c.get("domain") == domain)
                        and c.get("path", "/") == path
                    )
                ]
                self._context.clear_cookies()
                if remaining:
                    self._context.add_cookies(remaining)
            else:
                self._clear_cookies()
        except Exception:
            pass
