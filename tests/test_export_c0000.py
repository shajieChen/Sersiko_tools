import os
import sys
import unittest

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TOOL, "preview"))
sys.path.insert(0, os.path.join(TOOL, "gltf"))

try:
    import server
    import export_clip
except SystemExit:
    server = None
    export_clip = None


@unittest.skipUnless(server is not None, "resource directory is not configured")
class ExportC0000Tests(unittest.TestCase):
    def test_exports_c0000_as_skinned_animated_gltf(self):
        model = next(item["file"] for item in server.model_list("c0000") if item["file"].endswith("c0000.glb"))
        anim = next(item["file"] for item in server.animation_list("c0000", "") if item["name"] == "a000_000000")
        built = server.build_clip(model, anim, "wp_a_0300")
        dest = export_clip.publish(built, server.TOOL, model, anim, "wp_a_0300")

        self.assertTrue(os.path.isfile(dest))
        self.assertTrue(dest.replace("\\", "/").endswith("/output/c0000_a000_000000_wp_a_0300.glb"))
        document = export_clip.require_skinned_clip(dest)
        names = [node.get("name") for node in document["nodes"]]
        self.assertIn("Sheath", names)
        self.assertIn("R_Weapon", names)
        self.assertGreater(len(document["skins"][0]["joints"]), 100)
        self.assertGreater(len(document["animations"][0]["channels"]), 1)


if __name__ == "__main__":
    unittest.main()
