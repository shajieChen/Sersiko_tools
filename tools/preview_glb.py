import json, math, struct, os

def read_rig(path):
    data = open(path, "rb").read()
    if data[:4] != b"RIG2":
        raise ValueError("bad rig")
    pos = 4
    bone_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    bones = []
    for _ in range(bone_count):
        length = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        name = data[pos:pos + length].decode("utf-8", "replace")
        pos += length
        parent = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        values = struct.unpack_from("<10f", data, pos)
        pos += 40
        bones.append({
            "name": name,
            "parent": parent,
            "t": values[0:3],
            "q": values[3:7],
            "s": values[7:10],
        })
    mesh_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    meshes = []
    for _ in range(mesh_count):
        vertices, indices, mask = struct.unpack_from("<IIH", data, pos)
        pos += 10
        def take(count, code):
            nonlocal pos
            size = struct.calcsize(code)
            values = struct.unpack_from("<" + code * count, data, pos)
            pos += size * count
            return values
        meshes.append({
            "positions": take(vertices * 3, "f"),
            "normals": take(vertices * 3, "f"),
            "uvs": take(vertices * 2, "f"),
            "joints": take(vertices * 4, "H"),
            "weights": take(vertices * 4, "f"),
            "indices": take(indices, "I"),
            "mask": mask,
        })
    return bones, meshes

def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def mat_inv(m):
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(4)] for i, row in enumerate(m)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda row: abs(aug[row][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        if abs(scale) < 1e-12:
            raise ValueError("singular bone")
        for j in range(8):
            aug[col][j] /= scale
        for row in range(4):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(8):
                aug[row][j] -= factor * aug[col][j]
    return [row[4:] for row in aug]

def quat_matrix(q):
    x, y, z, w = q
    x2, y2, z2 = x + x, y + y, z + z
    xx, xy, xz = x * x2, x * y2, x * z2
    yy, yz, zz = y * y2, y * z2, z * z2
    wx, wy, wz = w * x2, w * y2, w * z2
    return [
        [1 - (yy + zz), xy - wz, xz + wy, 0],
        [xy + wz, 1 - (xx + zz), yz - wx, 0],
        [xz - wy, yz + wx, 1 - (xx + yy), 0],
        [0, 0, 0, 1],
    ]

def trs_matrix(t, q, s):
    rotation = quat_matrix(q)
    for row in range(3):
        for col in range(3):
            rotation[row][col] *= s[col]
    rotation[0][3], rotation[1][3], rotation[2][3] = t
    return rotation

def column_major(m):
    return [m[row][col] for col in range(4) for row in range(4)]

def flip_pose(translation, rotation, scale):
    tx, ty, tz = translation[:3]
    qx, qy, qz, qw = rotation[:4]
    return (tx, ty, -tz), (-qx, -qy, qz, qw), tuple(scale[:3])

def normalize(q):
    length = math.sqrt(sum(v * v for v in q)) or 1.0
    return tuple(v / length for v in q)

def escape(text):
    out = []
    for char in text:
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif code < 32:
            out.append("\\u%04x" % code)
        else:
            out.append(char)
    return "".join(out)

class Bin:
    def __init__(self):
        self.data = bytearray()
        self.views = []
        self.accessors = []

    def pad(self, alignment):
        while len(self.data) % alignment:
            self.data.append(0)

    def view(self, blob, target=None):
        self.pad(4)
        offset = len(self.data)
        self.data.extend(blob)
        item = {"buffer": 0, "byteOffset": offset, "byteLength": len(blob)}
        if target:
            item["target"] = target
        self.views.append(item)
        return len(self.views) - 1

    def accessor(self, view, count, component, kind, extra=""):
        self.accessors.append(
            f'{{"bufferView":{view},"byteOffset":0,"componentType":{component},"count":{count},"type":"{kind}"{extra}}}'
        )
        return len(self.accessors) - 1

def f32(values):
    return struct.pack("<" + "f" * len(values), *values)

def bounds(values, stride):
    mins = [min(values[i::stride]) for i in range(stride)]
    maxs = [max(values[i::stride]) for i in range(stride)]
    return mins, maxs

def write_glb(bones, meshes, frames, path):
    blob = Bin()
    primitives = []
    position_min = [1e30, 1e30, 1e30]
    position_max = [-1e30, -1e30, -1e30]
    for mesh in meshes:
        count = len(mesh["positions"]) // 3
        mins, maxs = bounds(mesh["positions"], 3)
        position_min = [min(a, b) for a, b in zip(position_min, mins)]
        position_max = [max(a, b) for a, b in zip(position_max, maxs)]
        extra = ',"min":[%s],"max":[%s]' % (",".join(str(v) for v in mins), ",".join(str(v) for v in maxs))
        position = blob.accessor(blob.view(f32(mesh["positions"]), 34962), count, 5126, "VEC3", extra)
        normal = blob.accessor(blob.view(f32(mesh["normals"]), 34962), count, 5126, "VEC3")
        uv = blob.accessor(blob.view(f32(mesh["uvs"]), 34962), count, 5126, "VEC2")
        joints = blob.accessor(blob.view(struct.pack("<" + "H" * len(mesh["joints"]), *mesh["joints"]), 34962), count, 5123, "VEC4")
        weights = blob.accessor(blob.view(f32(mesh["weights"]), 34962), count, 5126, "VEC4")
        indexes = blob.accessor(blob.view(struct.pack("<" + "I" * len(mesh["indices"]), *mesh["indices"]), 34963), len(mesh["indices"]), 5125, "SCALAR")
        primitives.append(
            f'{{"attributes":{{"POSITION":{position},"NORMAL":{normal},"TEXCOORD_0":{uv},"JOINTS_0":{joints},"WEIGHTS_0":{weights}}},"indices":{indexes},"material":0}}'
        )

    worlds = []
    for index, bone in enumerate(bones):
        local = trs_matrix(bone["t"], bone["q"], bone["s"])
        parent = bone["parent"]
        worlds.append(mat_mul(worlds[parent], local) if parent >= 0 else local)
    inverse = []
    for world in worlds:
        inverse.extend(column_major(mat_inv(world)))
    inverse_accessor = blob.accessor(blob.view(f32(inverse), 34962), len(bones), 5126, "MAT4")
    joints = ",".join(str(i + 1) for i in range(len(bones)))

    nodes = ['{"mesh":0,"skin":0,"name":"model"}']
    roots = [0]
    for index, bone in enumerate(bones):
        children = [child + 1 for child, item in enumerate(bones) if item["parent"] == index]
        child_json = "" if not children else ',"children":[%s]' % ",".join(map(str, children))
        t = ",".join(repr(float(v)) for v in bone["t"])
        q = ",".join(repr(float(v)) for v in bone["q"])
        s = ",".join(repr(float(v)) for v in bone["s"])
        nodes.append(
            f'{{"name":"{escape(bone["name"])}","translation":[{t}],"rotation":[{q}],"scale":[{s}]{child_json}}}'
        )
        if bone["parent"] < 0:
            roots.append(index + 1)

    if isinstance(frames, list):
        clips = frames
    elif frames:
        clips = [frames]
    else:
        clips = []
    animation_docs = []
    for clip_frames in clips:
        times = clip_frames["times"]
        time_accessor = blob.accessor(
            blob.view(f32(times), 34962),
            len(times),
            5126,
            "SCALAR",
            ',"min":[%s],"max":[%s]' % (repr(float(times[0])), repr(float(times[-1]))),
        )
        samplers = []
        channels = []
        for track in clip_frames["tracks"]:
            node = track["bone"] + 1
            for path_name, values, kind, stride in (
                ("translation", track["translation"], "VEC3", 3),
                ("rotation", track["rotation"], "VEC4", 4),
                ("scale", track["scale"], "VEC3", 3),
            ):
                mins, maxs = bounds(values, stride)
                extra = ',"min":[%s],"max":[%s]' % (
                    ",".join(repr(float(v)) for v in mins),
                    ",".join(repr(float(v)) for v in maxs),
                )
                output = blob.accessor(blob.view(f32(values), 34962), len(times), 5126, kind, extra)
                sampler = len(samplers)
                samplers.append(f'{{"input":{time_accessor},"output":{output},"interpolation":"LINEAR"}}')
                channels.append(f'{{"sampler":{sampler},"target":{{"node":{node},"path":"{path_name}"}}}}')
        name = escape(clip_frames.get("name") or "clip")
        animation_docs.append(
            '{"name":"%s","samplers":[%s],"channels":[%s]}' % (
                name,
                ",".join(samplers),
                ",".join(channels),
            )
        )
    animations = ""
    if animation_docs:
        animations = ',"animations":[%s]' % ",".join(animation_docs)

    blob.pad(4)
    view_json = ",".join(json.dumps(view, separators=(",", ":")) for view in blob.views)
    scene = ",".join(str(node) for node in roots)
    document = (
        '{"asset":{"version":"2.0","generator":"SekiroPreview"},"scene":0,'
        f'"scenes":[{{"nodes":[{scene}]}}],"nodes":[{",".join(nodes)}],'
        f'"skins":[{{"inverseBindMatrices":{inverse_accessor},"joints":[{joints}],"skeleton":1}}],'
        f'"meshes":[{{"primitives":[{",".join(primitives)}]}}],'
        '"materials":[{"pbrMetallicRoughness":{"baseColorFactor":[0.72,0.64,0.52,1],"metallicFactor":0,"roughnessFactor":0.85},"doubleSided":true}],'
        f'"accessors":[{",".join(blob.accessors)}],"bufferViews":[{view_json}],'
        f'"buffers":[{{"byteLength":{len(blob.data)}}}]'
        + animations
        + "}"
    )
    raw = document.encode("utf-8")
    raw += b" " * ((4 - len(raw) % 4) % 4)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(raw) + 8 + len(blob.data))
    out += struct.pack("<I", len(raw)) + b"JSON" + raw
    out += struct.pack("<I", len(blob.data)) + b"BIN\x00" + blob.data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(out)
    return position_min, position_max
