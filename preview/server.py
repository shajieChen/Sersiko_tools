import hashlib, json, os, re, subprocess, sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(TOOL, "config.json"), encoding="utf-8") as _config_file:
    _config = json.load(_config_file)
ROOT = _config.get("resourceDir") or ""
if not ROOT or not os.path.isdir(ROOT):
    raise SystemExit("resourceDir is missing. Run SetGameDir.bat and choose the resource directory.")
PREVIEW = os.path.join(ROOT, "preview")
UNPACKED = os.path.join(ROOT, "unpacked")
CACHE = os.path.join(PREVIEW, "cache")
TOOLS = os.path.join(TOOL, "tools")
RIGDUMP = os.path.join(TOOLS, "RigDump", "bin", "Release", "net10.0", "RigDump.exe")
ASSEMBLE = os.path.join(TOOLS, "Assemble", "bin", "Release", "net10.0", "Assemble.exe")
PLAYER_FILE = "chr/c0000.chrbnd/chr/c0000/c0000.glb"
PLAYER_PARTS = [
    os.path.join(UNPACKED, "parts", "bd_m_9000.partsbnd", "parts", "FullBody", "BD_M_9000", "BD_M_9000.flver"),
    os.path.join(UNPACKED, "parts", "am_m_9000.partsbnd", "parts", "FullBody", "AM_M_9000", "AM_M_9000.flver"),
    os.path.join(UNPACKED, "parts", "lg_m_9000.partsbnd", "parts", "FullBody", "LG_M_9000", "LG_M_9000.flver"),
    os.path.join(UNPACKED, "parts", "fc_m_0100.partsbnd", "parts", "Face", "FC_M_0100", "FC_M_0100.flver"),
    os.path.join(UNPACKED, "parts", "hd_m_9510.partsbnd", "parts", "FullBody", "HD_M_9510", "HD_M_9510.flver"),
    os.path.join(UNPACKED, "parts", "wp_a_0300.partsbnd", "parts", "Weapon", "WP_A_0300", "WP_A_0300.flver"),
    os.path.join(UNPACKED, "parts", "wp_a_0300.partsbnd", "parts", "Weapon", "WP_A_0300", "WP_A_0300_1.flver"),
]
sys.path.insert(0, TOOLS)
import havok_anim
import preview_glb

os.makedirs(CACHE, exist_ok=True)

def character_id(model):
    for part in model.replace("\\", "/").split("/"):
        if part.endswith(".chrbnd"):
            return part[:-7]
    if model.replace("\\", "/").startswith("parts/"):
        return "c0000"
    return None

def safe_join(base, relative):
    relative = unquote(relative).replace("\\", "/").lstrip("/")
    if ".." in relative.split("/"):
        raise ValueError("bad path")
    path = os.path.normpath(os.path.join(base, relative.replace("/", os.sep)))
    if os.path.commonpath([base, path]) != os.path.normpath(base):
        raise ValueError("bad path")
    return path

_MODEL_INDEX = None

def model_index():
    global _MODEL_INDEX
    if _MODEL_INDEX is None:
        found = []
        for dirpath, _, files in os.walk(PREVIEW):
            if os.path.basename(dirpath) == "cache":
                continue
            for name in files:
                if name.lower().endswith(".glb"):
                    found.append(os.path.relpath(os.path.join(dirpath, name), PREVIEW).replace("\\", "/"))
        found.sort()
        _MODEL_INDEX = found
    return _MODEL_INDEX

def model_label(relative):
    stem = os.path.splitext(os.path.basename(relative))[0]
    for part in relative.split("/"):
        if part.endswith(".chrbnd"):
            ident = part[:-7]
            return ident if stem == ident else ident + " / " + stem
    return relative


ITEM_NAMES = {'0100': '太刀', '0201': '太刀', '0300': '楔丸', '0301': '楔丸', '0310': '拜泪', '0320': '空模型', '0700': '手里剑', '0701': '幻影苦无', '0702': '钱币投掷', '0710': '爆竹', '0711': '爆竹', '0720': '火焰筒', '0730': '装载斧', '0731': '装载斧', '0732': '装载斧', '0740': '雾鸦', '0741': '雾鸦', '0742': '雾鸦', '0750': '忍刀', '0751': '忍刀', '0760': '铁伞', '0761': '铁伞', '0762': '铁伞', '0763': '铁伞', '0770': '神扇', '0771': '神扇', '0772': '神扇', '0780': '枪', '0781': '枪', '0782': '枪', '0790': '指笛', '0791': '指笛', '2300': '提灯', '2400': '空模型', '9500': '钩锁', '9501': '楔丸与拜泪', '9502': '楔丸与拜泪', '9503': '楔丸与拜泪', '9504': '楔丸与拜泪'}

def split_item_binder(binder):
    stem = binder[: -len(".partsbnd")]
    body = stem[5:]
    if body.endswith("_l"):
        return body[:-2], "lod"
    if body.endswith("_m"):
        return body[:-2], "menu"
    return body, "std"

def item_label(relative, num, tier):
    mesh = os.path.splitext(os.path.basename(relative))[0]
    name = ITEM_NAMES.get(num, num)
    mark = {"lod": " \u4f4e\u6a21", "menu": " \u83dc\u5355"}.get(tier, "")
    return name + " " + mesh + mark

def item_list(query):
    query = query.lower().strip()
    files = [item for item in model_index() if item.startswith("parts/wp_a_") and ".partsbnd/" in item]
    binders = {item.split("/")[1] for item in files}
    plain_ids = set()
    parsed = {}
    for binder in binders:
        num, tier = split_item_binder(binder)
        parsed[binder] = (num, tier)
        if tier == "std":
            plain_ids.add(num)
    rows = []
    for item in files:
        num, tier = parsed[item.split("/")[1]]
        if tier == "menu" and num not in plain_ids:
            tier = "std"
        label = item_label(item, num, tier)
        if query and query not in item.lower() and query not in label.lower():
            continue
        rows.append({"file": item, "name": label, "tier": tier})
    return rows


def weapon_id_ok(weapon):
    return bool(re.fullmatch(r"wp_a_\d{4}", weapon or ""))

def weapon_folder(weapon):
    base = os.path.join(UNPACKED, "parts")
    direct = os.path.join(base, weapon + ".partsbnd")
    menu = os.path.join(base, weapon + "_m.partsbnd")
    if os.path.isdir(direct):
        return direct
    if os.path.isdir(menu):
        return menu
    return None

def weapon_flvers(weapon):
    folder = weapon_folder(weapon)
    if not folder:
        return []
    found = []
    for dirpath, _, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(".flver"):
                found.append(os.path.join(dirpath, name))
    found.sort()
    return found

def player_parts(weapon):
    body = PLAYER_PARTS[:5]
    sword = PLAYER_PARTS[5:]
    if not weapon_id_ok(weapon):
        weapon = "wp_a_0300"
    extra = weapon_flvers(weapon)
    if weapon.startswith("wp_a_07") and extra:
        return body + sword + extra
    if extra:
        return body + extra
    return list(PLAYER_PARTS)

def weapon_choices():
    rows = []
    for weapon, name in sorted(ITEM_NAMES.items()):
        ident = "wp_a_" + weapon
        if name == "\u7a7a\u6a21\u578b" or not weapon_folder(ident):
            continue
        hand = "\u5de6\u624b" if ident.startswith("wp_a_07") else "\u53f3\u624b"
        rows.append({"id": ident, "name": name + " " + hand, "hand": hand})
    return rows

def model_list(query, kind=""):
    if kind == "item":
        return item_list(query)
    query = query.lower().strip()
    rows = model_index()
    if query:
        matched = [item for item in rows if query in item.lower()]
    else:
        matched = [
            item for item in rows
            if item.startswith("chr/")
            and os.path.splitext(os.path.basename(item))[0] == os.path.basename(os.path.dirname(item))
        ]
    rows = [{"file": item, "name": model_label(item)} for item in matched[:200]]
    if not query or "c0000" in query:
        rows.insert(0, {"file": PLAYER_FILE, "name": "c0000 狼"})
    return rows[:200]


def animation_roots(char_id):
    folder = os.path.join(UNPACKED, "chr")
    names = []
    if not os.path.isdir(folder):
        return names
    for name in os.listdir(folder):
        if char_id == "c0000":
            if name.startswith("c0000") and name.endswith(".anibnd"):
                names.append(os.path.join(folder, name))
        elif name == f"{char_id}.anibnd":
            names.append(os.path.join(folder, name))
    return names

def compendium_for(char_id):
    for root in animation_roots(char_id):
        for dirpath, _, files in os.walk(root):
            for name in files:
                if name.endswith(".compendium"):
                    return os.path.join(dirpath, name)
    return None

def compendium_for_clip(hkx, char_id):
    folder = os.path.dirname(hkx)
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".compendium"):
                return os.path.join(folder, name)
    return compendium_for(char_id)

def animation_list(char_id, query):
    query = query.lower()
    found = []
    for root in animation_roots(char_id):
        for dirpath, _, files in os.walk(root):
            for name in files:
                lower = name.lower()
                # skeleton.hkx is the bind rig, not a playable clip. Sampling it has no tracks.
                if not lower.endswith(".hkx") or lower == "skeleton.hkx":
                    continue
                if query and query not in lower:
                    continue
                relative = os.path.relpath(os.path.join(dirpath, name), UNPACKED).replace("\\", "/")
                found.append({"name": name[:-4], "file": relative})
    found.sort(key=lambda item: item["name"])
    return found



def ensure_player_rig(weapon="wp_a_0300"):
    player = os.path.join(UNPACKED, "chr", "c0000.chrbnd", "chr", "c0000", "c0000.flver")
    paths = [player] + player_parts(weapon)
    stamp = "|".join(path + str(int(os.path.getmtime(path))) for path in paths) + "|orient3|" + weapon
    rig = os.path.join(CACHE, hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:16] + ".rig2")
    if not os.path.exists(rig):
        subprocess.run([ASSEMBLE, rig] + paths, check=True)
    return rig

def ensure_rig(flver):
    stamp = str(int(os.path.getmtime(flver)))
    key = hashlib.sha1((flver + stamp).encode("utf-8")).hexdigest()[:16]
    rig = os.path.join(CACHE, key + ".rig2")
    if not os.path.exists(rig):
        subprocess.run([RIGDUMP, flver, rig], check=True)
    return rig


def visible_meshes(meshes):
    """Keep the always-on meshes plus mask groups that add new surface.

    Material names like #18# are mutually exclusive display masks. Drawing
    every mask stacks alternate heads, cloaks and weapons, which looks like
    broken skin. A mask is kept only when most of its vertices are not
    already sitting on a mesh we draw. Weapons laid beside the bind pose
    """
    cell = 0.045

    def bounds(group):
        xs, zs = [], []
        for mesh in group:
            pos = mesh["positions"]
            xs.extend(pos[0::3])
            zs.extend(pos[2::3])
        return (min(xs) + max(xs)) / 2, max(xs) - min(xs), max(zs) - min(zs)

    def add_surface(buckets, group):
        for mesh in group:
            pos = mesh["positions"]
            count = len(pos) // 3
            step = max(1, count // 800)
            for index in range(0, count, step):
                x, y, z = pos[index * 3], pos[index * 3 + 1], pos[index * 3 + 2]
                buckets.setdefault((int(x / cell), int(y / cell), int(z / cell)), []).append((x, y, z))

    def on_surface(buckets, x, y, z):
        ix, iy, iz = int(x / cell), int(y / cell), int(z / cell)
        limit = cell * cell
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for px, py, pz in buckets.get((ix + dx, iy + dy, iz + dz), ()):
                        if (px - x) ** 2 + (py - y) ** 2 + (pz - z) ** 2 <= limit:
                            return True
        return False

    kept = []
    grouped = {}
    for mesh in meshes:
        mask = mesh.get("mask", 65535)
        if mask == 65535:
            kept.append(mesh)
        else:
            grouped.setdefault(mask, []).append(mesh)
    surface = {}
    add_surface(surface, kept)
    ranked = sorted(grouped.items(), key=lambda item: -sum(len(mesh["positions"]) // 3 for mesh in item[1]))
    for mask, group in ranked:
        center_x, span_x, span_z = bounds(group)
        if abs(center_x) > 0.9 and min(span_x, span_z) < 0.25:
            continue
        samples = []
        for mesh in group:
            pos = mesh["positions"]
            count = len(pos) // 3
            step = max(1, count // 250)
            samples.extend((pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]) for i in range(0, count, step))
        hits = sum(1 for x, y, z in samples if on_surface(surface, x, y, z))
        if samples and hits / len(samples) > 0.55:
            continue
        kept.extend(group)
        add_surface(surface, group)
    return kept or meshes


def build_clip(model, anim_file, weapon="wp_a_0300"):
    flver = safe_join(UNPACKED, os.path.splitext(model)[0] + ".flver")
    hkx = safe_join(UNPACKED, anim_file)
    if not os.path.isfile(flver) or not os.path.isfile(hkx):
        raise FileNotFoundError("model or animation is missing")
    char_id = character_id(model)
    compendium = compendium_for_clip(hkx, char_id) if char_id else None
    if not compendium:
        raise FileNotFoundError("no animation set for this model")
    player = os.path.basename(flver).lower() == "c0000.flver"
    held = weapon if weapon_id_ok(weapon) else "wp_a_0300"
    token = hashlib.sha1((flver + "|" + hkx + ("|orient3|" + held if player else "|body5")).encode("utf-8")).hexdigest()[:16]
    target = os.path.join(CACHE, token + ".glb")
    if os.path.exists(target) and os.path.getmtime(target) >= os.path.getmtime(hkx):
        return target
    bones, meshes = preview_glb.read_rig(ensure_player_rig(held) if player else ensure_rig(flver))
    types = havok_anim.load_compendium(compendium)
    clip, mapping = havok_anim.animation_clip(havok_anim.HavokFile(types, open(hkx, "rb").read()).root)
    count = int(clip["numFrames"])
    duration = float(clip["duration"])
    times = [0.0 if count <= 1 else duration * i / (count - 1) for i in range(count)]
    step = max(1, count // 48)
    picked = list(range(0, count, step))
    if picked[-1] != count - 1:
        picked.append(count - 1)
    times = [times[i] for i in picked]
    poses = [havok_anim.sample_spline(clip, time) for time in times]
    names = {bone["name"]: index for index, bone in enumerate(bones)}
    named = []
    for item in clip.get("annotationTracks") or []:
        if isinstance(item, dict):
            named.append(names.get(item.get("trackName")))
        else:
            named.append(None)
    if not any(index is not None for index in named):
        named = [bone if 0 <= bone < len(bones) else None for bone in mapping]
    tracks = []
    for track, bone in enumerate(named):
        if bone is None:
            continue
        translation, rotation, scale, previous = [], [], [], None
        for pose in poses:
            moved_t, moved_q, moved_s = preview_glb.flip_pose(pose[track][0], pose[track][1], pose[track][2])
            moved_q = preview_glb.normalize(moved_q)
            if previous is not None and sum(a * b for a, b in zip(previous, moved_q)) < 0:
                moved_q = tuple(-v for v in moved_q)
            previous = moved_q
            translation.extend(moved_t)
            rotation.extend(moved_q)
            scale.extend(moved_s[:3])
        tracks.append({"bone": bone, "translation": translation, "rotation": rotation, "scale": scale})
    preview_glb.write_glb(bones, visible_meshes(meshes), {"times": times, "tracks": tracks}, target)
    return target

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        rel = unquote(clean).replace('\\', "/").lstrip("/")
        if rel in ("", "index.html"):
            return os.path.join(APP, "index.html")
        if rel == "model-viewer.min.js":
            return os.path.join(APP, rel)
        return safe_join(PREVIEW, rel)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/models":
            args = parse_qs(parsed.query)
            return self._json(model_list(args.get("q", [""])[0], args.get("kind", [""])[0]))
        if parsed.path == "/api/anims":
            args = parse_qs(parsed.query)
            char_id = character_id(args.get("model", [""])[0])
            query = args.get("q", [""])[0]
            return self._json(animation_list(char_id, query) if char_id else [])
        if parsed.path == "/api/weapons":
            return self._json(weapon_choices())
        if parsed.path == "/api/clip.glb":
            args = parse_qs(parsed.query)
            try:
                target = build_clip(args.get("model", [""])[0], args.get("anim", [""])[0], args.get("weapon", ["wp_a_0300"])[0])
            except Exception as exc:
                data = str(exc).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.path = "/" + os.path.relpath(target, PREVIEW).replace("\\", "/")
        return super().do_GET()

    def _json(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
