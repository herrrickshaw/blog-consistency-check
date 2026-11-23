"""A minimal fake of playwright.sync_api used by the audit/fix tests (no browser, no network)."""
import contextlib
import sys
import types


class FakePage:
    def __init__(self, log, handler):
        self.log, self.handler = log, handler

    def goto(self, url, **kw):
        self.log.append(("goto", url, kw))
        if "BOOM" in url:
            raise RuntimeError("navigation failed")

    def wait_for_timeout(self, ms):
        self.log.append(("wait", ms))

    def evaluate(self, js, arg=None):
        self.log.append(("eval", js if arg is None else "arg"))
        return self.handler(js, arg)

    def screenshot(self, path, full_page):
        self.log.append(("shot", path, full_page))


class FakeCtx:
    def __init__(self, log, handler, kw):
        self.log, self.handler, self.kw = log, handler, kw

    def new_page(self):
        return FakePage(self.log, self.handler)

    def close(self):
        self.log.append(("ctx-close",))


class FakeBrowser:
    def __init__(self, log, handler):
        self.log, self.handler = log, handler

    def new_context(self, **kw):
        self.log.append(("ctx", kw))
        return FakeCtx(self.log, self.handler, kw)

    def close(self):
        self.log.append(("br-close",))


def install(monkeypatch, handler):
    log = []

    @contextlib.contextmanager
    def sync_playwright():
        p = types.SimpleNamespace(chromium=types.SimpleNamespace(launch=lambda: FakeBrowser(log, handler)))
        yield p

    pw = types.ModuleType("playwright")
    api = types.ModuleType("playwright.sync_api")
    api.sync_playwright = sync_playwright
    pw.sync_api = api
    monkeypatch.setitem(sys.modules, "playwright", pw)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    return log
