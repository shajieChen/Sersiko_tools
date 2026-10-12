import os
import sys
import tempfile
import unittest

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TOOL, "tools"))
sys.path.insert(0, os.path.join(TOOL, "gltf"))
sys.path.insert(0, os.path.join(TOOL, "preview"))

import export_clip
import preview_glb

try:
    import server
except SystemExit:
    server = None

THRUST = {300000, 300001, 300010, 300011, 301000, 301050, 302010, 302011, 305000, 305001}


def bone():
    return {"name": "root", "parent": -1, "t": (0, 0, 0), "q": (0, 0, 0, 1), "s": (1, 1, 1)}


def mesh():
    return {
        "positions": [0, 0, 0, 1, 0, 0, 0, 1, 0],
        "normals": [0, 0, 1, 0, 0, 1, 0, 0, 1],
        "uvs": [0, 0, 1, 0, 0, 1],
        "joints": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "weights": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
        "indices": [0, 1, 2],
    }


def clip(name, shift):
    return {
        "name": name,
        "times": [0.0, 1.0],
        "tracks": [{
            "bone": 0,
            "translation": [0, 0, 0, shift, 0, 0],
            "rotation": [0, 0, 0, 1, 0, 0, 0, 1],
            "scale": [1, 1, 1, 1, 1, 1],
        }],
    }


def thrust_names():
    found = []
    for item in server.animation_list("c0000", ""):
        parts = item["name"].split("_")
        if len(parts) < 2 or parts[0] != "a050":
            continue
        try:
            number = int(parts[1])
        except ValueError:
            continue
        if number >= 10000 and number in THRUST:
            found.append(item)
    return found


class CategoryExportTests(unittest.TestCase):
    def test_one_skin_can_carry_each_named_clip(self):
        folder = tempfile.mkdtemp()
        single = os.path.join(folder, "one.glb")
        preview_glb.write_glb([bone()], [mesh()], {"times": [0.0, 1.0], "tracks": clip("ignored", 0.2)["tracks"]}, single)
        document, _blob = export_clip.load_glb(single)
        self.assertEqual([item["name"] for item in document["animations"]], ["clip"])

        batch = os.path.join(folder, "batch.glb")
        preview_glb.write_glb([bone()], [mesh()], [clip("a050_300000", 0.2), clip("a050_300001", 0.4)], batch)
        document, _blob = export_clip.load_glb(batch)
        self.assertEqual(len(document["skins"]), 1)
        self.assertEqual([item["name"] for item in document["animations"]], ["a050_300000", "a050_300001"])

    def test_export_click_asks_about_the_detail_category(self):
        with open(os.path.join(TOOL, "preview", "index.html"), encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn('id="exportCategory"', page)
        self.assertIn("是否导出", page)
        self.assertIn("细分类别", page)
        start = page.find("async function exportGlb")
        body = page[start:page.find('document.getElementById("play")', start)]
        self.assertLess(body.find("exportCategory"), body.find('"/api/export?'))
        self.assertIn("/api/export-category", body)

    @unittest.skipUnless(server is not None, "resource directory is not configured")
    def test_thrust_category_exports_one_skinned_file(self):
        clips = thrust_names()
        self.assertGreaterEqual(len(clips), 2)
        model = next(item["file"] for item in server.model_list("c0000") if item["file"].endswith("c0000.glb"))
        dest = server.export_detail(model, [item["file"] for item in clips], "wp_a_0300", "突刺")
        document = export_clip.require_skinned_clip(dest)
        self.assertEqual([item["name"] for item in document["animations"]], [item["name"] for item in clips])
        self.assertGreater(len(document["skins"][0]["joints"]), 100)
        self.assertTrue(dest.replace("\\", "/").endswith("/output/c0000_突刺_wp_a_0300.glb"))


if __name__ == "__main__":
    unittest.main()
