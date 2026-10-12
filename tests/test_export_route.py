import os
import sys
import unittest

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TOOL, "tools"))

import preview_launch


class ExportRouteTests(unittest.TestCase):
    def test_only_this_preview_server_is_stopped(self):
        command = "python " + os.path.join(TOOL, "preview", "server.py") + " 8766"
        relative = r'"C:\Program Files\Python314\python.exe" preview\server.py 8766'
        other = "python -m http.server 8756"
        self.assertTrue(preview_launch.is_preview_server_command(command, TOOL))
        self.assertTrue(preview_launch.is_preview_server_command(relative, TOOL))
        self.assertFalse(preview_launch.is_preview_server_command(other, TOOL))
        self.assertFalse(preview_launch.is_preview_server_command("python server.py", TOOL))

    def test_stop_kills_matching_preview_server_only(self):
        killed = []
        processes = [
            (11, "python " + os.path.join(TOOL, "preview", "server.py") + " 8766"),
            (22, "python -m http.server 8756"),
        ]
        preview_launch.stop_preview_servers(processes, TOOL, kill=killed.append)
        self.assertEqual(killed, [11])

    def test_export_error_does_not_paste_the_html_404_page(self):
        with open(os.path.join(TOOL, "preview", "index.html"), encoding="utf-8") as handle:
            page = handle.read()
        self.assertNotIn(
            'status.textContent = "导出失败 " + (await response.text())',
            page,
        )
        self.assertIn("当前预览是旧进程", page)


if __name__ == "__main__":
    unittest.main()
