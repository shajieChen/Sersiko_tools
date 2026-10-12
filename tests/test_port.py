import os
import socket
import sys
import unittest

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TOOL, "tools"))

import preview_launch


class PortTests(unittest.TestCase):
    def test_occupied_port_uses_the_next_one(self):
        held = socket.socket()
        held.bind(("127.0.0.1", 0))
        occupied = held.getsockname()[1]
        try:
            self.assertEqual(preview_launch.first_free_port(occupied), occupied + 1)
        finally:
            held.close()


if __name__ == "__main__":
    unittest.main()
