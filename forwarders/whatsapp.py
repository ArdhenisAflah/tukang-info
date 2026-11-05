from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .base import ForwardMessage, MessageForwarder

WHATSAPP_URL = "https://web.whatsapp.com/"

SEARCH_INPUT_LOCATORS = (
    (By.CSS_SELECTOR, "#side input[role='textbox']"),
    (By.CSS_SELECTOR, "#side input[data-tab='3']"),
    (By.CSS_SELECTOR, "#side input"),
)

MESSAGE_BOX_LOCATORS = (
    (By.CSS_SELECTOR, "footer div[contenteditable='true'][role='textbox']"),
    (By.CSS_SELECTOR, "div[contenteditable='true'][data-tab='10']"),
    (By.CSS_SELECTOR, "div[contenteditable='true'][aria-label='Type a message']"),
)

QR_LOCATORS = (
    (By.CSS_SELECTOR, "canvas[aria-label*='Scan']"),
    (By.CSS_SELECTOR, "canvas[aria-label*='QR']"),
    (By.CSS_SELECTOR, "div[data-ref]"),
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


class WhatsAppWebForwarder(MessageForwarder):
    def __init__(
        self,
        target: str,
        profile_dir: Path,
        *,
        headless: bool = False,
        attach: str | None = None,
        timeout: int = 30,
        dry_run: bool = False,
    ) -> None:
        if not target.strip():
            raise ValueError("WhatsApp target chat name cannot be empty")

        self.target = target.strip()
        self.profile_dir = profile_dir
        self.headless = headless
        self.attach = attach
        self.timeout = timeout
        self.dry_run = dry_run
        self.evidence_dir = Path("logs/whatsapp-failed")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._owns_driver = attach is None

        self.driver = self._build_driver()
        self._apply_viewport()
        self.wait = WebDriverWait(self.driver, self.timeout)
        try:
            self._open_whatsapp()
            self._select_chat()
        except (TimeoutException, WebDriverException, RuntimeError):
            self._save_evidence("init")
            self.close()
            raise

    def _build_driver(self) -> webdriver.Chrome:
        options = Options()

        if self.attach:
            options.add_experimental_option("debuggerAddress", self.attach)
        else:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            options.add_argument(f"--user-data-dir={self.profile_dir}")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-notifications")
            options.add_argument("--window-size=1280,900")
            options.add_argument(
                "--user-agent="
                + os.getenv(
                    "WHATSAPP_USER_AGENT",
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
                )
            )
            options.add_experimental_option(
                "excludeSwitches", ["enable-automation"]
            )
            options.add_experimental_option("useAutomationExtension", False)

            binary = os.getenv("WHATSAPP_CHROME_BINARY", "/usr/bin/chromium")
            if Path(binary).exists():
                options.binary_location = binary

            if self.headless:
                options.add_argument("--headless=new")

        driver_path = os.getenv("WHATSAPP_DRIVER_PATH") or shutil.which(
            "chromedriver"
        )
        service = Service(driver_path) if driver_path else Service()
        return webdriver.Chrome(service=service, options=options)

    def _apply_viewport(self) -> None:
        # The window manager may tile the browser to a narrow size, which makes
        # WhatsApp collapse the sidebar and hide the search input.
        try:
            self.driver.execute_cdp_cmd(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1400,
                    "height": 900,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
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

    def _open_chats_tab(self) -> None:
        # WhatsApp may restore the Calls tab after login; switch back to Chats.
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

    def _wait_for_app_ready(self, timeout: int) -> str | None:
        def ready(_driver) -> str | bool:
            if self._visible_elements(SEARCH_INPUT_LOCATORS):
                return "search"
            if self._qr_visible():
                return "qr"
            self._open_chats_tab()
            # A "What's new" overlay can hide the chat list after login.
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except WebDriverException:
                pass
            return False

        try:
            return WebDriverWait(self.driver, timeout).until(ready)
        except TimeoutException:
            return None

    def _open_whatsapp(self) -> None:
        self.driver.get(WHATSAPP_URL)
        state = self._wait_for_app_ready(self.timeout)

        if state == "search":
            self._dismiss_welcome_modal()
            return

        if state != "qr":
            self._save_evidence("login")
            raise RuntimeError(
                "Could not load WhatsApp Web. Check the browser window or page source."
            )

        if self.headless:
            self._save_evidence("headless-qr")
            raise RuntimeError(
                "WhatsApp Web needs a QR login. Run once with "
                "WHATSAPP_HEADLESS=false, scan the QR, then restart."
            )

        print(
            "WhatsApp Web is not logged in. Scan the QR code in the Chromium "
            "window; waiting up to 3 minutes..."
        )
        self._wait_any(
            SEARCH_INPUT_LOCATORS,
            EC.visibility_of_element_located,
            timeout=180,
        )
        self._dismiss_welcome_modal()

    def _dismiss_welcome_modal(self) -> None:
        # WhatsApp Web shows a "What's new" modal after a fresh login.
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
        self.wait.until(EC.presence_of_element_located(locator))
        matches = [
            element
            for element in self.driver.find_elements(*locator)
            if element.is_displayed()
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected exactly one WhatsApp chat matching {self.target!r}, "
                f"found {len(matches)}"
            )
        return matches[0]

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

    def _dry_run_type(self, text: str) -> None:
        self._select_chat()
        box = self._wait_any(MESSAGE_BOX_LOCATORS, EC.element_to_be_clickable)
        box.click()
        box.send_keys(text)
        self.wait.until(lambda _driver: text[:25] in self._message_box_text())
        print(f"[WhatsApp dry-run] typed: {self._message_box_text()}")

        # Clear the draft so a later Enter cannot send it by accident.
        box = self._wait_any(MESSAGE_BOX_LOCATORS, EC.element_to_be_clickable)
        box.click()
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.BACKSPACE)
        self.wait.until(lambda _driver: not self._message_box_text())
        print("[WhatsApp dry-run] input cleared; nothing sent.")

    def send(self, message: ForwardMessage) -> None:
        text = format_message(message)
        if not text:
            return

        if self.dry_run:
            self._dry_run_type(text)
            return

        try:
            self._select_chat()
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
            self.driver.save_screenshot(
                str(self.evidence_dir / f"{stem}.png")
            )
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
