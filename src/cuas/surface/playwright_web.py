from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Frame, FrameLocator, Page, Playwright, async_playwright
from playwright.async_api import Locator as PwLocator

from cuas.models.action import ActionSpec, ActionType, Checkpoint, CheckpointKind, Locator, LocatorStrategy, Target
from cuas.models.observation import Control, Observation

INTERACTIVE_ROLES = ("button", "textbox", "link", "combobox", "checkbox", "radio", "spinbutton")


class TargetNotFound(LookupError):
    pass


class AmbiguousTarget(LookupError):
    pass


class PlaywrightWebSurface:
    """Web adapter. Locators are semantic; CSS is only a fallback."""

    def __init__(
        self,
        *,
        headed: bool = False,
        cdp_port: int | None = None,
    ) -> None:
        self.headed = headed
        self.cdp_port = cdp_port
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self._used_strategy: str | None = None
        self._human_callback: Any = None
        self._human_fn_exposed = False

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        args = []
        if self.cdp_port:
            args.append(f"--remote-debugging-port={self.cdp_port}")
        self._browser = await self._pw.chromium.launch(headless=not self.headed, args=args)
        self._context = await self._browser.new_context(viewport={"width": 1100, "height": 800})
        self.page = await self._context.new_page()
        self.page.set_default_timeout(8000)

    async def goto(self, url: str) -> None:
        assert self.page is not None
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(150)

    async def current_url(self) -> str:
        assert self.page is not None
        return self.page.url

    async def title(self) -> str:
        assert self.page is not None
        return await self.page.title()

    async def visible_text(self) -> str:
        assert self.page is not None
        try:
            return (await self.page.inner_text("body")).strip()
        except Exception:
            return ""

    async def observe(self) -> Observation:
        assert self.page is not None
        url = self.page.url
        title = await self.page.title()
        visible = await self.visible_text()
        aria_parts: list[str] = []
        controls: list[Control] = []
        index = 0
        for frame in self.page.frames:
            frame_path = _frame_path(self.page, frame)
            label = "/".join(frame_path) if frame_path else "top"
            try:
                snap = await frame.locator("body").aria_snapshot()
                aria_parts.append(f"# frame:{label}\n{snap}")
            except Exception:
                snap = ""
            index, extra = await _collect_controls(frame, frame_path, index)
            controls.extend(extra)
        errors = _guess_errors(visible)
        return Observation(
            url=url,
            title=title,
            aria_snapshot="\n".join(aria_parts),
            visible_text=visible,
            controls=controls,
            errors=errors,
        )

    def _scope(self, frame_names: list[str]) -> Page | FrameLocator:
        assert self.page is not None
        scope: Page | FrameLocator = self.page
        for name in frame_names:
            if name.startswith("iframe"):
                scope = scope.frame_locator(name)
            else:
                scope = scope.frame_locator(f'iframe[name="{name}"]')
        return scope

    def _pw_locator(self, locator: Locator) -> PwLocator:
        scope = self._scope(locator.frame)
        if locator.strategy is LocatorStrategy.ROLE_NAME:
            found = scope.get_by_role(locator.role or "button", name=locator.name or "", exact=locator.exact)
        elif locator.strategy is LocatorStrategy.LABEL:
            found = scope.get_by_label(locator.name or locator.text or "", exact=locator.exact)
        elif locator.strategy is LocatorStrategy.PLACEHOLDER:
            found = scope.get_by_placeholder(locator.text or locator.name or "", exact=locator.exact)
        elif locator.strategy is LocatorStrategy.TEXT:
            found = scope.get_by_text(locator.text or locator.name or "", exact=locator.exact)
        elif locator.strategy is LocatorStrategy.CSS:
            found = scope.locator(locator.selector or "*")
        else:
            raise TargetNotFound(f"unknown strategy {locator.strategy}")
        if locator.nth is not None:
            found = found.nth(locator.nth)
        return found

    async def resolve(self, target: Target) -> PwLocator:
        last_error: Exception | None = None
        chain = [target.primary, *target.fallbacks]
        for locator in chain:
            try:
                handle = self._pw_locator(locator)
                count = await handle.count()
                if count == 0:
                    last_error = TargetNotFound(self.locator_debug(locator))
                    continue
                if count > 1 and locator.nth is None:
                    last_error = AmbiguousTarget(f"{self.locator_debug(locator)} matched {count}")
                    continue
                self._used_strategy = locator.strategy.value
                return handle.first if locator.nth is None else handle
            except Exception as exc:  # pragma: no cover - defensive
                last_error = exc
                continue
        raise last_error or TargetNotFound("no locator resolved")

    async def execute(self, action: ActionSpec) -> dict[str, Any]:
        assert self.page is not None
        self._used_strategy = None
        if action.type is ActionType.NAVIGATE:
            if not action.url:
                raise ValueError("navigate requires url")
            await self.goto(action.url)
            return {"ok": True, "url": self.page.url}
        if action.type is ActionType.WAIT:
            await self.page.wait_for_timeout(int(float(action.value or 500)))
            return {"ok": True}
        if action.type is ActionType.FINISH:
            return {"ok": True, "outputs": action.outputs or {}, "goal_complete": True}
        if action.type is ActionType.READ or action.type is ActionType.EXTRACT:
            text = await self.visible_text()
            return {"ok": True, "text": text[:2000], "strategy": "visible_text"}

        if action.target is None:
            raise ValueError(f"{action.type} requires a target")
        handle = await self.resolve(action.target)
        await handle.wait_for(state="visible")
        if action.type is ActionType.CLICK:
            await handle.click()
        elif action.type is ActionType.TYPE:
            await handle.fill(action.value or "")
        elif action.type is ActionType.SELECT:
            await handle.select_option(label=action.value)
        elif action.type is ActionType.PRESS:
            await handle.press(action.key or action.value or "Enter")
        else:
            raise ValueError(f"unsupported action {action.type}")
        await self.page.wait_for_timeout(200)
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=4000)
        except Exception:
            pass
        return {"ok": True, "strategy": self._used_strategy, "url": self.page.url}

    async def checkpoint(self, spec: Checkpoint) -> bool:
        assert self.page is not None
        timeout = spec.timeout_ms
        try:
            if spec.kind is CheckpointKind.VISIBLE_TEXT:
                await self.page.get_by_text(spec.text or "", exact=False).first.wait_for(
                    state="visible", timeout=timeout
                )
                return True
            if spec.kind is CheckpointKind.ABSENT_TEXT:
                await self.page.get_by_text(spec.text or "", exact=False).first.wait_for(
                    state="hidden", timeout=timeout
                )
                return True
            if spec.kind is CheckpointKind.TITLE:
                await self.page.wait_for_function(
                    "title => document.title.includes(title)",
                    spec.text or "",
                    timeout=timeout,
                )
                return True
            if spec.kind is CheckpointKind.URL_REGEX:
                pattern = spec.pattern or spec.text or ""
                await self.page.wait_for_url(re.compile(pattern), timeout=timeout)
                return True
            if spec.kind is CheckpointKind.ROLE_NAME:
                loc = Locator(
                    strategy=LocatorStrategy.ROLE_NAME,
                    role=spec.role or "button",
                    name=spec.name or spec.text or "",
                )
                handle = self._pw_locator(loc)
                await handle.first.wait_for(state="visible", timeout=timeout)
                return True
        except Exception:
            return False
        return False

    async def matches(self, spec: Checkpoint) -> bool:
        """Non-waiting check used after each step for outcome detectors."""
        assert self.page is not None
        visible = await self.visible_text()
        title = await self.page.title()
        url = self.page.url
        if spec.kind is CheckpointKind.VISIBLE_TEXT:
            return (spec.text or "") in visible
        if spec.kind is CheckpointKind.ABSENT_TEXT:
            return (spec.text or "") not in visible
        if spec.kind is CheckpointKind.TITLE:
            return (spec.text or "") in title
        if spec.kind is CheckpointKind.URL_REGEX:
            return re.search(spec.pattern or spec.text or "", url) is not None
        if spec.kind is CheckpointKind.ROLE_NAME:
            loc = Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role=spec.role or "button",
                name=spec.name or spec.text or "",
            )
            try:
                return await self._pw_locator(loc).count() > 0
            except Exception:
                return False
        return False

    async def extract_regex(self, pattern: str) -> str | None:
        text = await self.visible_text()
        match = re.search(pattern, text)
        if not match:
            return None
        return match.group(1) if match.lastindex else match.group(0)

    async def screenshot(self, path: str) -> None:
        assert self.page is not None
        await self.page.screenshot(path=path, full_page=True)

    def set_human_callback(self, callback: Any) -> None:
        self._human_callback = callback

    async def install_human_listeners(self, endpoint: str) -> None:
        """Record real clicks/submits in this Playwright page (same session).

        Uses expose_function so events do not depend on cross-origin fetch to the
        operator port. A fetch fallback remains for pages that still have it.
        """
        assert self.page is not None

        async def _on_human(payload: dict[str, Any]) -> None:
            cb = self._human_callback
            if cb is None:
                return
            result = cb(payload)
            if hasattr(result, "__await__"):
                await result

        if not self._human_fn_exposed:
            try:
                await self.page.expose_function("__cuasReportHuman", _on_human)
                self._human_fn_exposed = True
            except Exception:
                pass

        script = f"""
        (() => {{
          if (window.__cuasHumanInstalled) return;
          window.__cuasHumanInstalled = true;
          const send = (payload) => {{
            try {{
              if (window.__cuasReportHuman) window.__cuasReportHuman(payload);
            }} catch (e) {{}}
            try {{
              fetch("{endpoint}/human-event", {{
                method: "POST",
                headers: {{"content-type": "application/json"}},
                body: JSON.stringify(payload),
                keepalive: true
              }});
            }} catch (e) {{}}
          }};
          const describe = (t) => ({{
            tag: t && t.tagName,
            text: ((t && (t.innerText || t.value)) || "").slice(0, 80),
            name: (t && (t.getAttribute("aria-label") || t.getAttribute("value") || t.name)) || ""
          }});
          document.addEventListener("click", (e) => {{
            send({{ type: "click", ...describe(e.target) }});
          }}, true);
          document.addEventListener("submit", (e) => {{
            const submitter = e.submitter || e.target;
            send({{ type: "submit", ...describe(submitter) }});
          }}, true);
          document.addEventListener("change", (e) => {{
            const t = e.target;
            send({{
              type: "change",
              tag: t.tagName,
              name: t.getAttribute("aria-label") || t.name || "",
              value: t.type === "password" ? "***" : "[set]"
            }});
          }}, true);
        }})();
        """
        await self.page.add_init_script(script)
        await self.page.evaluate(script)

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._context = None
        self._browser = None
        self._pw = None
        self.page = None
        self._human_fn_exposed = False
        self._human_callback = None

    def locator_debug(self, locator: Locator) -> str:
        frame = "/".join(locator.frame) or "top"
        return (
            f"{locator.strategy.value} role={locator.role!r} name={locator.name!r} "
            f"text={locator.text!r} css={locator.selector!r} frame={frame}"
        )


def _frame_path(page: Page, frame: Frame) -> list[str]:
    if frame == page.main_frame:
        return []
    name = frame.name or ""
    if name:
        return [name]
    url = frame.url
    path = urlparse(url).path
    return [path or url]


async def _collect_controls(frame: Frame, frame_path: list[str], start: int) -> tuple[int, list[Control]]:
    controls: list[Control] = []
    index = start
    for role in INTERACTIVE_ROLES:
        loc = frame.get_by_role(role)
        try:
            count = await loc.count()
        except Exception:
            continue
        for i in range(min(count, 30)):
            item = loc.nth(i)
            try:
                name = await item.evaluate(
                    """el => {
                      const aria = el.getAttribute('aria-label');
                      if (aria) return aria.trim();
                      if (el.labels && el.labels[0]) return el.labels[0].innerText.trim();
                      if (el.type === 'submit' || el.tagName === 'BUTTON') {
                        return (el.value || el.innerText || '').trim();
                      }
                      return (el.innerText || el.placeholder || '').trim();
                    }"""
                )
                value = None
                try:
                    value = await item.input_value()
                except Exception:
                    value = None
                enabled = await item.is_enabled()
                placeholder = await item.get_attribute("placeholder")
            except Exception:
                continue
            controls.append(
                Control(
                    index=index,
                    role=role,
                    name=(name or "").strip()[:80],
                    value=value,
                    frame=list(frame_path),
                    placeholder=placeholder,
                    enabled=enabled,
                )
            )
            index += 1
    return index, controls


def _guess_errors(visible: str) -> list[str]:
    errors = []
    for needle in (
        "Member not found",
        "Permission denied",
        "Session expired",
        "must be",
        "required",
        "Nothing to confirm",
    ):
        if needle.lower() in visible.lower():
            errors.append(needle)
    return errors
