"""Limited-query identity tests with fake Win32 APIs; no process is contacted."""
from __future__ import annotations
import contextlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("crud_identity_under_test", HERE / "run_live_crud_acceptance.py")
crud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crud)


class EditorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.image = "D:\\games\\原神\\BeyondEditor.exe"
        self.creation = 134032512618814060
        self.handle = 9876
        self.kernel = SimpleNamespace(
            OpenProcess=mock.Mock(return_value=self.handle),
            QueryFullProcessImageNameW=mock.Mock(side_effect=self.query_image),
            GetProcessTimes=mock.Mock(side_effect=self.query_times),
            CloseHandle=mock.Mock(return_value=True),
        )
        self.api = self.stack.enter_context(mock.patch.object(crud.profiles, "windows_api", return_value=(self.kernel, object())))
        self.stack.enter_context(mock.patch.object(crud.subprocess, "run", side_effect=AssertionError("NO PROCESS LAUNCH")))
        self.stack.enter_context(mock.patch.object(crud, "read_json", side_effect=AssertionError("NO SCOPE IDENTITY FALLBACK")))

    def query_image(self, handle, flags, buffer, length):
        self.assertEqual(handle, self.handle)
        self.assertEqual(flags, 0)
        self.assertEqual(length._obj.value, 32768)
        buffer.value = self.image
        length._obj.value = len(self.image)
        return True

    def query_times(self, handle, creation, exit_time, kernel_time, user_time):
        self.assertEqual(handle, self.handle)
        creation._obj.dwLowDateTime = self.creation & 0xffffffff
        creation._obj.dwHighDateTime = self.creation >> 32
        return True

    def test_limited_query_preserves_unicode_and_converts_filetime(self):
        got = crud.query_editor(9340)
        self.assertEqual(got, {"pid": 9340, "startUtcTicks": self.creation + 504911232000000000,
                               "expectedExe": self.image, "processName": "BeyondEditor"})
        self.kernel.OpenProcess.assert_called_once_with(0x1000, False, 9340)
        self.kernel.CloseHandle.assert_called_once_with(self.handle)
        self.kernel.QueryFullProcessImageNameW.assert_called_once()
        self.kernel.GetProcessTimes.assert_called_once()

    def test_invalid_pid_refuses_before_api_access(self):
        for pid in (None, True, False, 0, -1, 2**32, 9340.0, "9340"):
            with self.subTest(pid=pid), self.assertRaises(crud.CrudRefusal):
                crud.query_editor(pid)
        self.api.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()

    def test_access_denied_refuses_without_fallback_or_invalid_close(self):
        self.kernel.OpenProcess.return_value = 0
        with self.assertRaisesRegex(crud.CrudRefusal, "OpenProcess.*failed"):
            crud.query_editor(9340)
        self.kernel.CloseHandle.assert_not_called()
        self.kernel.QueryFullProcessImageNameW.assert_not_called()
        self.kernel.GetProcessTimes.assert_not_called()

    def test_api_unavailable_refuses_without_opening_handle(self):
        self.api.side_effect = OSError("API unavailable")
        with self.assertRaisesRegex(crud.CrudRefusal, "unavailable"):
            crud.query_editor(9340)
        self.kernel.OpenProcess.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()

    def test_failed_image_query_releases_handle(self):
        self.kernel.QueryFullProcessImageNameW.side_effect = None
        self.kernel.QueryFullProcessImageNameW.return_value = False
        with self.assertRaisesRegex(crud.CrudRefusal, "QueryFullProcessImageNameW.*failed"):
            crud.query_editor(9340)
        self.kernel.CloseHandle.assert_called_once_with(self.handle)
        self.kernel.GetProcessTimes.assert_not_called()

    def test_failed_times_query_releases_handle(self):
        self.kernel.GetProcessTimes.side_effect = None
        self.kernel.GetProcessTimes.return_value = False
        with self.assertRaisesRegex(crud.CrudRefusal, "GetProcessTimes.*failed"):
            crud.query_editor(9340)
        self.kernel.CloseHandle.assert_called_once_with(self.handle)

    def test_unexpected_query_exception_still_releases_handle(self):
        self.kernel.GetProcessTimes.side_effect = OSError("fake API error")
        with self.assertRaisesRegex(OSError, "fake API error"):
            crud.query_editor(9340)
        self.kernel.CloseHandle.assert_called_once_with(self.handle)

    def test_empty_image_refuses_and_releases_handle(self):
        self.image = ""
        with self.assertRaisesRegex(crud.CrudRefusal, "image path missing"):
            crud.query_editor(9340)
        self.kernel.CloseHandle.assert_called_once_with(self.handle)

    def test_zero_filetime_refuses_and_releases_handle(self):
        self.creation = 0
        with self.assertRaisesRegex(crud.CrudRefusal, "FILETIME is zero"):
            crud.query_editor(9340)
        self.kernel.CloseHandle.assert_called_once_with(self.handle)


if __name__ == "__main__":
    unittest.main()
