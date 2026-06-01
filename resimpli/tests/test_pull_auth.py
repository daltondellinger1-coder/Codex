#!/usr/bin/env python3
"""Regression tests for reSimpli auth selection without touching live CRM data."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pull  # noqa: E402


class AuthSelectionTests(unittest.TestCase):
    def test_failed_email_login_falls_back_to_api_token(self) -> None:
        with patch.object(pull, "login", return_value=None) as login:
            _session, token = pull.get_session_and_jwt(
                "bad@example.com", "bad-password", "fallback-token"
            )

        login.assert_called_once()
        self.assertEqual(token, "fallback-token")

    def test_failed_email_login_without_token_exits(self) -> None:
        with patch.object(pull, "login", return_value=None):
            with self.assertRaises(SystemExit) as raised:
                pull.get_session_and_jwt("bad@example.com", "bad-password", None)

        self.assertIn("RESIMPLI_API_TOKEN", str(raised.exception))

    def test_successful_email_login_wins_over_api_token(self) -> None:
        with patch.object(pull, "login", return_value="session-token"):
            _session, token = pull.get_session_and_jwt(
                "good@example.com", "good-password", "fallback-token"
            )

        self.assertEqual(token, "session-token")


if __name__ == "__main__":
    unittest.main()
