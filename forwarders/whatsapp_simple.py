from __future__ import annotations

import os
import shutil
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver import Keys
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .base import ForwardMessage, MessageForwarder
from .whatsapp import DESKTOP_CHROME_UA, format_message, xpath_literal

WHATSAPP_URL = "https://web.whatsapp.com/"

SEARCH_INPUT_LOCATORS = (
    (By.XPATH, '//input[@data-tab="3"]'),
    (By.CSS_SELECTOR, "#side input[role='textbox']"),
)

MESSAGE_BOX_LOCATORS = (
    (By.CSS_SELECTOR, "footer div[contenteditable='true'][role='textbox']"),
    (By.XPATH, '//div[@data-testid="conversation-compose-box-input"]'),
)

Locator = tuple[str, str]


def build_chrome_options(profile_dir: Path, headless: bool) -> ChromeOptions:
    options = ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--window-size=1400,900")
    # WhatsApp Web rejects the default "HeadlessChrome" user agent.
    options.add_argument(f"--user-agent={DESKTOP_CHROME_UA}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    if headless:
        options.add_argument("--headless=new")
    return options


def dismiss_welcome_modal(driver: webdriver.Chrome) -> None:
    for label in ("Lanjut", "Continue", "Tutup", "Close"):
        for element in driver.find_elements(
            By.XPATH, f"//*[normalize-space(text())='{label}']"
        ):
            if not element.is_displayed():
                continue
            try:
                element.click()
            except WebDriverException:
                pass


def open_whatsapp(driver: webdriver.Chrome, timeout: int) -> WebDriverWait:
    driver.get(WHATSAPP_URL)
    login_wait = WebDriverWait(driver, max(timeout, 120))
    login_wait.until(EC.presence_of_element_located((By.ID, "pane-side")))
    dismiss_welcome_modal(driver)
    return WebDriverWait(driver, timeout)


def wait_clickable(
    wait: WebDriverWait, locators: tuple[Locator, ...]
) -> WebElement:
    return wait.until(
        EC.any_of(*(EC.element_to_be_clickable(locator) for locator in locators))
    )


def chat_result_locator(target: str) -> tuple[Locator, ...]:
    return (
        (
            By.XPATH,
            f"//div[@id='pane-side']//span[@title={xpath_literal(target)}]",
        ),
    )


def open_chat(wait: WebDriverWait, target: str) -> None:
    search_box = wait_clickable(wait, SEARCH_INPUT_LOCATORS)
    search_box.click()
    search_box.send_keys(Keys.CONTROL, "a")
    search_box.send_keys(Keys.BACKSPACE)
    search_box.send_keys(target)

    result = wait_clickable(wait, chat_result_locator(target))
    try:
        result.click()
    except WebDriverException:
        result.parent.execute_script("arguments[0].click()", result)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#main header")))


def message_box_text(driver: webdriver.Chrome) -> str:
    for locator in MESSAGE_BOX_LOCATORS:
        for element in driver.find_elements(*locator):
            if element.is_displayed():
                return (element.text or "").strip()
    return ""


def send_text(driver: webdriver.Chrome, wait: WebDriverWait, text: str, dry_run: bool) -> None:
    message_box = wait_clickable(wait, MESSAGE_BOX_LOCATORS)
    message_box.click()
    message_box.send_keys(text)
    wait.until(lambda _driver: text[:25] in message_box_text(driver))

    if dry_run:
        message_box.send_keys(Keys.CONTROL, "a")
        message_box.send_keys(Keys.BACKSPACE)
        wait.until(lambda _driver: not message_box_text(driver))
        print(f"[WhatsApp dry-run] {text}")
        return

    message_box.send_keys(Keys.ENTER)
    wait.until(lambda _driver: not message_box_text(driver))


class SimpleWhatsAppForwarder(MessageForwarder):
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
        self._owns_driver = attach is None

        if self.browser != "chrome":
            raise ValueError(
                "SimpleWhatsAppForwarder only supports the Chrome browser"
            )

        self.driver = self._build_driver()
        try:
            self.wait = open_whatsapp(self.driver, self.timeout)
            open_chat(self.wait, self.target)
        except (TimeoutException, WebDriverException):
            self.close()
            raise

    def _build_driver(self) -> webdriver.Chrome:
        if self.attach:
            options = ChromeOptions()
            options.add_experimental_option("debuggerAddress", self.attach)
            return webdriver.Chrome(options=options)

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options = build_chrome_options(self.profile_dir, self.headless)
        driver_path = os.getenv("WHATSAPP_DRIVER_PATH") or shutil.which("chromedriver")
        service = ChromeService(driver_path) if driver_path else ChromeService()
        return webdriver.Chrome(service=service, options=options)

    def send(self, message: ForwardMessage) -> None:
        text = format_message(message)
        if not text:
            return

        try:
            open_chat(self.wait, self.target)
            send_text(self.driver, self.wait, text, self.dry_run)
        except (TimeoutException, WebDriverException) as exc:
            raise RuntimeError(f"WhatsApp forward failed: {exc}") from exc

    def close(self) -> None:
        if self._owns_driver and getattr(self, "driver", None) is not None:
            try:
                self.driver.quit()
            except WebDriverException:
                pass
