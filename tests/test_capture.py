import unittest
from unittest.mock import Mock, patch

from gi.repository import GLib

from zprint_app.capture import ScreenshotRequest, PATH


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.callback = Mock()
        self.request = ScreenshotRequest(self.callback)
        self.connection = Mock()
        self.connection.get_unique_name.return_value = ":1.23"
        self.connection.signal_subscribe.return_value = 42

    def respond(self, code, result):
        self.request._response(None, None, None, None, None,
                               GLib.Variant("(ua{sv})", (code, result)))

    def test_subscribe_before_call_and_use_interactive_v2(self):
        with patch("zprint_app.capture.Gio.bus_get_finish", return_value=self.connection):
            self.request._connected(None, None)
        calls = self.connection.method_calls
        names = [call[0] for call in calls]
        self.assertLess(names.index("signal_subscribe"), names.index("call"))
        params = self.connection.call.call_args.args[4].unpack()
        self.assertTrue(params[1]["interactive"])
        self.assertTrue(self.request.path.startswith(PATH + "/request/1_23/zprint_"))
        self.request.cancel()
        self.assertEqual(self.request.subscription, 0)
        self.assertEqual(self.request.timer, 0)

    def test_success_returns_exact_uri_once(self):
        self.respond(0, {"uri": GLib.Variant("s", "file:///tmp/screenshot.png")})
        self.respond(1, {})
        self.callback.assert_called_once_with("file:///tmp/screenshot.png", None)

    def test_cancel_response_is_not_error(self):
        self.respond(1, {})
        self.callback.assert_called_once_with(None, None)

    def test_failed_response_is_error(self):
        self.respond(2, {})
        self.assertIsNotNone(self.callback.call_args.args[1])

    def test_missing_uri_reports_error(self):
        self.respond(0, {})
        self.assertIsNotNone(self.callback.call_args.args[1])

    def test_timeout_closes_remote_request(self):
        self.request.connection = self.connection
        self.request.path = "/request/test"
        self.request._timeout()
        self.assertEqual(self.connection.call.call_args.args[3], "Close")
        self.assertIsNotNone(self.callback.call_args.args[1])
        self.request.cancel()
        self.callback.assert_called_once()

    def test_late_method_response_does_not_reopen_finished_request(self):
        self.request.cancel()
        self.connection.call_finish.return_value = GLib.Variant("(o)", ("/late",))
        self.request._called(self.connection, None)
        self.connection.signal_subscribe.assert_not_called()
        self.callback.assert_called_once_with(None, None)
