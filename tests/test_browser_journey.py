"""
Browser tests for the frontend: register, log in, view and edit the profile,
and log out, checking what is visible on the page.

Requires the complete application running locally and E2E_BASE_URL set:
    E2E_BASE_URL=http://127.0.0.1:8080 .venv/bin/python -m unittest tests.test_browser_journey -v
Skipped otherwise, so the regular test suite does not need a browser.
"""

import os
import unittest
import uuid

BASE_URL = os.environ.get("E2E_BASE_URL")
PASSWORD = "learning123"

if BASE_URL:
    from playwright.sync_api import expect, sync_playwright


def unique_email(label):
    # Synthetic, unique per run so tests never collide with existing accounts.
    return f"e2e.{label}.{uuid.uuid4().hex[:10]}@example.com"


@unittest.skipUnless(BASE_URL, "Set E2E_BASE_URL to run browser tests.")
class BrowserJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def new_page(self):
        # Each context is an isolated browser session, like a private window.
        context = self.browser.new_context()
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(BASE_URL)
        return page

    def register(self, page, first_name, last_name, email):
        page.fill("#register-first-name", first_name)
        page.fill("#register-last-name", last_name)
        page.fill("#register-email", email)
        page.fill("#register-password", PASSWORD)
        page.click("#register-form button[type=submit]")
        expect(page.locator("#status-message")).to_contain_text("Account created")

    def login(self, page, email):
        page.fill("#login-email", email)
        page.fill("#login-password", PASSWORD)
        page.click("#login-form button[type=submit]")
        expect(page.locator("#profile-section")).to_be_visible()

    def test_register_login_update_logout(self):
        page = self.new_page()
        email = unique_email("journey")

        self.register(page, "Ada", "Lovelace", email)
        self.login(page, email)
        expect(page.locator("#profile-first-name")).to_have_text("Ada")
        expect(page.locator("#profile-last-name")).to_have_text("Lovelace")
        expect(page.locator("#profile-email")).to_have_text(email)

        page.fill("#edit-first-name", "Grace")
        page.click("#profile-form button[type=submit]")
        expect(page.locator("#status-message")).to_have_text("Profile saved.")
        expect(page.locator("#profile-first-name")).to_have_text("Grace")

        page.click("#logout-button")
        expect(page.locator("#profile-section")).to_be_hidden()
        expect(page.locator("#login-section")).to_be_visible()
        expect(page.locator("#profile-first-name")).to_be_empty()

    def test_two_sessions_see_only_their_own_profile(self):
        first_page, second_page = self.new_page(), self.new_page()
        first_email, second_email = unique_email("first"), unique_email("second")

        self.register(first_page, "First", "User", first_email)
        self.register(second_page, "Second", "User", second_email)
        self.login(first_page, first_email)
        self.login(second_page, second_email)
        expect(first_page.locator("#profile-email")).to_have_text(first_email)
        expect(second_page.locator("#profile-email")).to_have_text(second_email)

        first_page.fill("#edit-first-name", "Changed")
        first_page.click("#profile-form button[type=submit]")
        expect(first_page.locator("#profile-first-name")).to_have_text("Changed")

        # Log the second user in again to read a fresh profile from the API.
        second_page.click("#logout-button")
        self.login(second_page, second_email)
        expect(second_page.locator("#profile-first-name")).to_have_text("Second")

    def test_duplicate_email_shows_message(self):
        page = self.new_page()
        email = unique_email("duplicate")

        self.register(page, "Dup", "User", email)
        page.fill("#register-first-name", "Dup")
        page.fill("#register-last-name", "Again")
        page.fill("#register-email", email)
        page.fill("#register-password", PASSWORD)
        page.click("#register-form button[type=submit]")
        expect(page.locator("#status-message")).to_have_text("Email is already registered.")


if __name__ == "__main__":
    unittest.main()
