from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver import Keys
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .base import ForwardMessage, MessageForwarder

WHATSAPP_URL = "https://web.whatsapp.com/"

DESKTOP_CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
DESKTOP_FIREFOX_UA = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
)

SEARCH_INPUT_LOCATORS = (
    (By.CSS_SELECTOR, "#side input[role='textbox']"),
    (By.CSS_SELECTOR, "#side input[data-tab='3']"),
    (By.CSS_SELECTOR, "#side input"),
    (By.CSS_SELECTOR, "#side div[contenteditable='true']"),
    (By.CSS_SELECTOR, "#side [role='textbox']"),
)

MESSAGE_BOX_LOCATORS = (
    (By.CSS_SELECTOR, "footer div[contenteditable='true'][role='textbox']"),
    (By.CSS_SELECTOR, 'div[contenteditable="true"][data-testid="conversation-compose-box-input"]'),
    (By.CSS_SELECTOR, "div[contenteditable='true'][data-tab='10']"),
    (By.CSS_SELECTOR, "div[contenteditable='true'][aria-label='Type a message']"),
)

QR_LOCATORS = (
    (By.CSS_SELECTOR, "canvas[aria-label*='Scan']"),
    (By.CSS_SELECTOR, "canvas[aria-label*='QR']"),
    (By.CSS_SELECTOR, "div[data-ref]"),
)

LOADING_LOCATORS = (
    (By.CSS_SELECTOR, "[data-testid='wa-web-loading-screen']"),
    (By.CSS_SELECTOR, "progress"),
    (
        By.XPATH,
        "//*[contains(text(), 'Loading your chats') or contains(text(), 'Memuat chat Anda')]",
    ),
)

UNSUPPORTED_BROWSER_MARKERS = (
    "whatsapp dapat digunakan di google chrome",
    "perbarui chrome",
    "update chrome",
    "update your browser",
    "whatsapp works with google chrome",
    "browser is not supported",
)

OUTGOING_MESSAGE_SELECTOR = "#main div.message-out"


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"


def format_message(message: ForwardMessage) -> str:
    timestamp = message.timestamp.strftime("%H:%M") if message.timestamp else ""
    header = message.sender
    if timestamp:
        header = f"{header} {timestamp}"
    text = " ".join(message.text.splitlines()).strip()
    return f"{header}: {text}"


def desktop_user_agent(fallback: str) -> str:
    return os.getenv("WHATSAPP_USER_AGENT", "").strip() or fallback


def build_chrome_options(
    profile_dir: Path,
    *,
    headless: bool,
    attach: str | None = None,
) -> ChromeOptions:
    options = ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--window-size=1400,900")
    # WhatsApp Web rejects the default "HeadlessChrome" user agent.
    options.add_argument(f"--user-agent={desktop_user_agent(DESKTOP_CHROME_UA)}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if attach:
        options.add_experimental_option("debuggerAddress", attach)
        return options

    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={profile_dir}")

    binary = os.getenv("WHATSAPP_CHROME_BINARY", "/usr/bin/chromium")
    if Path(binary).exists():
        options.binary_location = binary

    if headless:
        options.add_argument("--headless=new")

    return options


def build_firefox_options(profile_dir: Path, *, headless: bool) -> FirefoxOptions:
    options = FirefoxOptions()
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("permissions.default.desktop-notification", 2)
    options.set_preference("media.volume_scale", "0.0")
    options.set_preference(
        "general.useragent.override",
        desktop_user_agent(DESKTOP_FIREFOX_UA),
    )

    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument("-profile")
    options.add_argument(str(profile_dir))

    binary = (
        os.getenv("WHATSAPP_FIREFOX_BINARY")
        or shutil.which("firefox")
        or shutil.which("firefox-esr")
    )
    if binary and Path(binary).exists():
        options.binary_location = binary

    if headless:
        options.add_argument("-headless")

    return options


class WhatsAppWebForwarder(MessageForwarder):
    def __init__(
        self,
        target: str,
        profile_dir: Path,
        *,
        browser: str = "chrome",
        headless: bool = False,
        attach: str | None = None,
        timeout: int = 45,
        dry_run: bool = False,
    ) -> None:
        if not target.strip():
            raise ValueError("WhatsApp target chat name cannot be empty")

        self.target = target.strip()
        self.profile_dir = profile_dir
        self.browser = browser.strip().lower()
        self.headless = headless
        self.attach = attach
        self.timeout = timeout
        self.dry_run = dry_run
        self.evidence_dir = Path("logs/whatsapp-failed")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._owns_driver = attach is None

        if self.browser not in {"chrome", "firefox"}:
            raise ValueError(
                f"Unsupported WHATSAPP_BROWSER {self.browser!r}; use 'chrome' or 'firefox'"
            )
        if self.attach and self.browser != "chrome":
            raise ValueError("WHATSAPP_ATTACH is only supported with Chrome")

        self.driver = self._build_driver()
        self.wait = WebDriverWait(self.driver, self.timeout)
        try:
            self._apply_viewport()
            self._open_whatsapp()
            self._select_chat()
        except (TimeoutException, WebDriverException, RuntimeError):
            self._save_evidence("init")
            self.close()
            raise

    def _build_driver(self) -> webdriver.Remote:
        if self.browser == "firefox":
            return self._build_firefox_driver()
        return self._build_chrome_driver()

    def _build_chrome_driver(self) -> webdriver.Chrome:
        options = build_chrome_options(
            self.profile_dir, headless=self.headless, attach=self.attach
        )
        driver_path = os.getenv("WHATSAPP_DRIVER_PATH") or shutil.which(
            "chromedriver"
        )
        service = ChromeService(driver_path) if driver_path else ChromeService()
        return webdriver.Chrome(service=service, options=options)

    def _build_firefox_driver(self) -> webdriver.Firefox:
        options = build_firefox_options(self.profile_dir, headless=self.headless)
        driver_path = os.getenv("WHATSAPP_GECKODRIVER_PATH") or shutil.which(
            "geckodriver"
        )
        service = FirefoxService(driver_path) if driver_path else FirefoxService()
        return webdriver.Firefox(service=service, options=options)

    def _apply_viewport(self) -> None:
        try:
            self.driver.set_window_size(1400, 900)
        except WebDriverException:
            pass

    def _wait_any(
        self,
        locators,
        condition=EC.presence_of_element_located,
        timeout: int | None = None,
    ):
        wait = WebDriverWait(self.driver, timeout or self.timeout)
        return wait.until(EC.any_of(*(condition(locator) for locator in locators)))

    def _visible_elements(self, locators) -> list:
        for locator in locators:
            elements = self.driver.find_elements(*locator)
            visible = [element for element in elements if element.is_displayed()]
            if visible:
                return visible
        return []

    def _qr_visible(self) -> bool:
        return bool(self._visible_elements(QR_LOCATORS))

    def _is_loading_chats(self) -> bool:
        return bool(self._visible_elements(LOADING_LOCATORS))

    def _unsupported_browser(self) -> bool:
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        except WebDriverException:
            return False
        return any(marker in body for marker in UNSUPPORTED_BROWSER_MARKERS)

    def _app_state(self) -> str | None:
        if self._visible_elements(SEARCH_INPUT_LOCATORS):
            return "search"
        if self._qr_visible():
            return "qr"
        if self._unsupported_browser():
            return "unsupported"
        return "loading" if self._is_loading_chats() else None

    def _open_chats_tab(self) -> None:
        for label in ("Chat", "Chats", "Obrolan"):
            for button in self.driver.find_elements(
                By.CSS_SELECTOR, f"button[aria-label='{label}']"
            ):
                if not button.is_displayed():
                    continue
                try:
                    button.click()
                    return
                except WebDriverException:
                    pass

    def _wait_for_app(self, timeout: int) -> str | None:
        def probe(_driver):
            state = self._app_state()
            if state in {"search", "qr", "unsupported"}:
                return state
            self._open_chats_tab()
            self._dismiss_welcome_modal()
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except WebDriverException:
                pass
            return False

        try:
            return WebDriverWait(self.driver, timeout).until(probe)
        except TimeoutException:
            return self._app_state()

    def _open_whatsapp(self) -> None:
        self.driver.get(WHATSAPP_URL)
        state = self._wait_for_app(self.timeout)

        if state == "search":
            self._dismiss_welcome_modal()
            return

        if state == "unsupported":
            self._save_evidence("unsupported-browser")
            raise RuntimeError(
                "WhatsApp Web rejected this browser as unsupported. Selenium may "
                "be sending a headless user agent; set WHATSAPP_USER_AGENT to a "
                "normal desktop user agent or update the browser."
            )

        if state == "qr":
            if self.headless:
                self._save_evidence("headless-qr")
                raise RuntimeError(
                    "WhatsApp Web needs a QR login. Run once with "
                    "WHATSAPP_HEADLESS=false, scan the QR, then restart."
                )
            browser_name = "Firefox" if self.browser == "firefox" else "Chromium"
            print(
                f"WhatsApp Web is not logged in. Scan the QR code in the "
                f"{browser_name} window; waiting up to 3 minutes..."
            )
            self._wait_any(
                SEARCH_INPUT_LOCATORS,
                EC.visibility_of_element_located,
                timeout=180,
            )
            self._dismiss_welcome_modal()
            return

        # Give slow chat sync a quiet grace period before giving up.
        if self._is_loading_chats():
            print("WhatsApp Web is still syncing chats; waiting up to 2 more minutes...")
            try:
                WebDriverWait(self.driver, 120).until(
                    lambda _driver: bool(self._visible_elements(SEARCH_INPUT_LOCATORS))
                )
                self._dismiss_welcome_modal()
                return
            except TimeoutException:
                pass

        self._save_evidence("login")
        raise RuntimeError(
            "Could not load WhatsApp Web. Check the browser window or page source."
        )

    def _dismiss_welcome_modal(self) -> None:
        for label in ("Lanjut", "Continue", "Tutup", "Close"):
            elements = self.driver.find_elements(
                By.XPATH, f"//*[normalize-space(text())='{label}']"
            )
            for element in elements:
                if not element.is_displayed():
                    continue
                try:
                    element.click()
                except WebDriverException:
                    pass

    def _chat_result_locator(self) -> tuple[str, str]:
        return (
            By.XPATH,
            f"//div[@id='pane-side']//span[@title={xpath_literal(self.target)}]",
        )

    def _find_unique_visible(self, locator) -> object:
        def probe(_driver):
            matches = [
                element
                for element in self.driver.find_elements(*locator)
                if element.is_displayed()
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise RuntimeError(
                    f"Expected exactly one WhatsApp chat matching {self.target!r}, "
                    f"found {len(matches)}"
                )
            return False

        return self.wait.until(probe)

    def _select_chat(self) -> None:
        search = self._wait_any(SEARCH_INPUT_LOCATORS, EC.element_to_be_clickable)
        search.click()
        search.send_keys(Keys.CONTROL, "a")
        search.send_keys(Keys.BACKSPACE)
        search.send_keys(self.target)

        result = self._find_unique_visible(self._chat_result_locator())
        result.click()
        self._wait_for_chat_header()

    def _header_title(self) -> str:
        headers = self.driver.find_elements(By.CSS_SELECTOR, "#main header")
        if not headers:
            return ""
        return headers[0].text.splitlines()[0].strip()

    def _wait_for_chat_header(self) -> None:
        self.wait.until(lambda _driver: self._header_title() == self.target)

    def _outgoing_count(self) -> int:
        return len(
            self.driver.find_elements(By.CSS_SELECTOR, OUTGOING_MESSAGE_SELECTOR)
        )

    def _message_box_text(self) -> str:
        boxes = self._visible_elements(MESSAGE_BOX_LOCATORS)
        if not boxes:
            return ""
        return (boxes[0].text or "").strip()

    def _wait_for_send(self, before: int) -> None:
        def sent(_driver) -> bool:
            if not self._message_box_text():
                return True
            return self._outgoing_count() > before

        self.wait.until(sent)

    def _clear_message_box(self) -> None:
        box = self._wait_any(MESSAGE_BOX_LOCATORS, EC.element_to_be_clickable)
        box.click()
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.BACKSPACE)
        self.wait.until(lambda _driver: not self._message_box_text())

    def _dry_run_type(self, text: str) -> None:
        box = self._wait_any(MESSAGE_BOX_LOCATORS, EC.element_to_be_clickable)
        box.click()
        box.send_keys(text)
        self.wait.until(lambda _driver: text[:25] in self._message_box_text())
        print(f"[WhatsApp dry-run] typed: {self._message_box_text()}")

        self._clear_message_box()
        print("[WhatsApp dry-run] input cleared; nothing sent.")

    def send(self, message: ForwardMessage) -> None:
        text = format_message(message)
        if not text:
            return

        try:
            self._select_chat()

            if self.dry_run:
                self._dry_run_type(text)
                return

            box = self._wait_any(MESSAGE_BOX_LOCATORS, EC.element_to_be_clickable)
            before = self._outgoing_count()
            box.click()
            box.send_keys(text)
            box.send_keys(Keys.ENTER)
            self._wait_for_send(before)
        except (TimeoutException, WebDriverException, RuntimeError) as exc:
            self._save_evidence("send")
            raise RuntimeError(f"WhatsApp forward failed: {exc}") from exc

    def _save_evidence(self, label: str) -> None:
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label)
        stem = f"{datetime.now():%Y%m%d-%H%M%S}-{safe_label}"
        try:
            self.driver.save_screenshot(str(self.evidence_dir / f"{stem}.png"))
        except WebDriverException:
            pass
        try:
            (self.evidence_dir / f"{stem}.html").write_text(
                self.driver.page_source, encoding="utf-8"
            )
        except WebDriverException:
            pass

    def close(self) -> None:
        if self.driver is not None and self._owns_driver:
            try:
                self.driver.quit()
            except WebDriverException:
                pass
