import ast
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.parse
import urllib.request

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOAL = r"H:\SErsiko_Goal"
RESOURCE_SUFFIXES = {".glb", ".flver", ".hkx", ".dds", ".dcx", ".tpf", ".bdt", ".bhd", ".tae"}


def resource_files(root):
    found = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in files:
            if os.path.splitext(name)[1].lower() in RESOURCE_SUFFIXES:
                found.append(os.path.join(dirpath, name))
    return found


def function_dump(path):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            found[node.name] = ast.dump(node)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    found[node.name + "." + item.name] = ast.dump(item)
    return found


def goal_ready():
    return os.path.isdir(os.path.join(GOAL, "preview"))


class SplitTests(unittest.TestCase):
    def test_resource_scan_flags_a_model_file(self):
        folder = os.path.join(GOAL, "preview")
        if not os.path.isdir(folder):
            self.skipTest("resource directory is not on this machine")
        self.assertTrue(resource_files(folder))

    def test_tool_directory_has_no_extracted_resources(self):
        self.assertEqual(resource_files(TOOL), [])

    def test_local_config_is_gitignored(self):
        with open(os.path.join(TOOL, ".gitignore"), encoding="utf-8") as handle:
            ignore = handle.read()
        self.assertIn("config.json", ignore)
        with open(os.path.join(TOOL, "config.example.json"), encoding="utf-8") as handle:
            example = json.load(handle)
        self.assertEqual(set(example), {"gameDir", "resourceDir"})

    def test_programs_read_config_instead_of_fixed_paths(self):
        with open(os.path.join(TOOL, "preview", "server.py"), encoding="utf-8") as handle:
            server = handle.read()
        with open(os.path.join(TOOL, "tools", "SekiroExtract", "SekiroExtract", "Program.cs"), encoding="utf-8") as handle:
            extract = handle.read()
        for text in (server, extract):
            self.assertNotIn("H:\\SErsiko_Goal", text)
            self.assertNotIn("Sekiro Shadows Die Twice", text)
        self.assertIn('GetProperty("gameDir")', extract)
        self.assertIn('GetProperty("resourceDir")', extract)
        self.assertIn("config.json", server)


@unittest.skipUnless(goal_ready(), "resource directory is not on this machine")
class PreviewTests(unittest.TestCase):
    def test_preview_logic_matches_resource_directory(self):
        goal = function_dump(os.path.join(GOAL, "preview", "server.py"))
        tool = function_dump(os.path.join(TOOL, "preview", "server.py"))
        self.assertIn("Handler.translate_path", tool)
        tool.pop("Handler.translate_path")
        self.assertEqual(sorted(goal), sorted(tool))
        for name in goal:
            self.assertEqual(goal[name], tool[name], name)
        for name in ("index.html", "model-viewer.min.js"):
            with open(os.path.join(GOAL, "preview", name), "rb") as handle:
                goal_bytes = handle.read()
            with open(os.path.join(TOOL, "preview", name), "rb") as handle:
                tool_bytes = handle.read()
            self.assertEqual(goal_bytes, tool_bytes, name)
        for name in ("havok_anim.py", "preview_glb.py"):
            with open(os.path.join(GOAL, "tools", name), "rb") as handle:
                goal_bytes = handle.read()
            with open(os.path.join(TOOL, "tools", name), "rb") as handle:
                tool_bytes = handle.read()
            self.assertEqual(goal_bytes, tool_bytes, name)

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(TOOL, "preview", "server.py"), "8766"],
            cwd=TOOL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                urllib.request.urlopen("http://127.0.0.1:8766/api/weapons", timeout=1).read()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("tool preview did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)

    def test_live_lists_match_current_preview(self):
        for path in ("/api/weapons", "/api/models?q=c1010", "/index.html"):
            current = urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=30).read()
            tool = urllib.request.urlopen("http://127.0.0.1:8766" + path, timeout=30).read()
            self.assertEqual(current, tool, path)

    def test_live_clip_matches_current_preview(self):
        models = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/models?q=c1010", timeout=30))
        model = next(item["file"] for item in models if item["file"].endswith("c1010.glb"))
        anims = json.load(urllib.request.urlopen(
            "http://127.0.0.1:8765/api/anims?model=" + urllib.parse.quote(model), timeout=30
        ))
        anim = next(item["file"] for item in anims if item["name"] == "a000_000000")
        query = "/api/clip.glb?model=%s&anim=%s" % (urllib.parse.quote(model), urllib.parse.quote(anim))
        current = urllib.request.urlopen("http://127.0.0.1:8765" + query, timeout=180).read()
        tool = urllib.request.urlopen("http://127.0.0.1:8766" + query, timeout=180).read()
        self.assertTrue(current.startswith(b"glTF"))
        self.assertEqual(current, tool)


if __name__ == "__main__":
    unittest.main()
