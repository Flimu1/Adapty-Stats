"""Secret redaction tests for application and third-party log records."""
import io
import logging
import unittest
from unittest.mock import patch


class TestSecretRedactionFilter(unittest.TestCase):
    def _capture(self, secret: str):
        from safe_logging import SecretRedactionFilter

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        handler.addFilter(SecretRedactionFilter([secret]))
        logger = logging.getLogger(f"safe-logging-test-{id(stream)}")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        return logger, stream

    def test_redacts_direct_secret_bot_url_and_logging_args(self):
        secret = "123456:telegram-secret"
        logger, stream = self._capture(secret)

        logger.warning(
            "retry url=%s token=%s",
            f"https://api.telegram.org/bot{secret}/getUpdates",
            secret,
        )

        output = stream.getvalue()
        self.assertNotIn(secret, output)
        self.assertIn("/bot[REDACTED]/getUpdates", output)
        self.assertIn("token=[REDACTED]", output)

    def test_redacts_secret_from_exception_traceback(self):
        secret = "123456:telegram-secret"
        logger, stream = self._capture(secret)

        try:
            raise ConnectionError(
                f"request failed for https://api.telegram.org/bot{secret}/getUpdates"
            )
        except ConnectionError:
            logger.exception("poll failed")

        output = stream.getvalue()
        self.assertNotIn(secret, output)
        self.assertIn("/bot[REDACTED]/getUpdates", output)

    def test_configure_installs_filter_on_existing_root_handlers(self):
        from safe_logging import SecretRedactionFilter, configure_secret_redaction

        root = logging.getLogger()
        handler = logging.StreamHandler(io.StringIO())
        original_handlers = root.handlers[:]
        try:
            root.handlers = [handler]
            configure_secret_redaction(["secret-value"])
            self.assertTrue(
                any(isinstance(item, SecretRedactionFilter) for item in handler.filters)
            )
        finally:
            root.handlers = original_handlers

    @patch.dict(
        "safe_logging.os.environ",
        {
            "ADAPTY_API_KEY_APP1": "first-adapty-secret",
            "ADAPTY_API_KEY_APP23": "second-adapty-secret",
        },
        clear=False,
    )
    def test_configure_defaults_redact_every_numbered_adapty_key_in_args_and_traceback(
        self,
    ):
        from safe_logging import configure_secret_redaction

        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        original_handlers = root.handlers[:]
        original_level = root.level
        try:
            root.handlers = [handler]
            root.setLevel(logging.DEBUG)
            configure_secret_redaction()
            logger = logging.getLogger("safe-logging-default-app-keys")
            logger.warning(
                "keys: %s %s", "first-adapty-secret", "second-adapty-secret"
            )
            try:
                raise RuntimeError("failed with first-adapty-secret and second-adapty-secret")
            except RuntimeError:
                logger.exception("request failed")
        finally:
            root.handlers = original_handlers
            root.setLevel(original_level)

        output = stream.getvalue()
        self.assertNotIn("first-adapty-secret", output)
        self.assertNotIn("second-adapty-secret", output)
        self.assertGreaterEqual(output.count("[REDACTED]"), 4)


if __name__ == "__main__":
    unittest.main()
