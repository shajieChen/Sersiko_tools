import struct, sys

VAR = [
    (7, 1, 0),
    (14, 2, 0b10000000),
    (21, 3, 0b11000000),
    (27, 4, 0b11100000),
    (35, 5, 0b11101000),
    (40, 6, 0b11111000),
    (59, 8, 0b11110000),
    (64, 9, 0b11111001),
]

def _var_meta(prefix):
    for bits, nbytes, pref in VAR:
        mask = (~((1 << (bits % 8)) - 1)) & 0xFF
        if (prefix & mask) == pref:
            return nbytes, mask
    raise ValueError(hex(prefix))

def read_varuint(data, pos):
    nbytes, mask = _var_meta(data[pos])
    raw = bytearray(data[pos:pos + nbytes])
    raw.reverse()
    if nbytes < 9:
        raw += b"\x00" * (8 - len(raw))
        raw[nbytes - 1] = data[pos] & (~mask & 0xFF)
    return int.from_bytes(raw[:8], "little"), pos + nbytes

def read_cstrs(data, start, end):
    pos = start
    out = []
    while pos < end and data[pos] != 0:
        begin = pos
        while pos < end and data[pos] != 0:
            pos += 1
        out.append(data[begin:pos].decode("ascii", "replace"))
        pos += 1
    return out

def sections(data, start, end):
    pos = start
    out = []
    while pos + 8 <= end:
        length = struct.unpack_from(">I", data, pos)[0] & 0x0FFFFFFF
        sid = data[pos + 4:pos + 8]
        if length < 8 or pos + length > end or not sid.isalnum():
            break
        out.append((sid.decode("ascii"), pos + 8, pos + length))
        pos += length
    return out

def child_map(data, start, end):
    return {name: (a, b) for name, a, b in sections(data, start, end)}

class Types:
    def __init__(self, data, start, end):
        kids = child_map(data, start, end)
        self.strings = read_cstrs(data, *kids["TSTR"])
        self.field_strings = read_cstrs(data, *kids["FSTR"])
        self.types = self._tna1(data, *kids["TNA1"])
        self._tbdy(data, *kids["TBDY"])
        self._inherit()
        self._flatten()

    def _tna1(self, data, start, end):
        pos = start
        num, pos = read_varuint(data, pos)
        types = []
        for _ in range(num):
            types.append({
                "name": "NULL", "params": [], "own": [], "parent": 0,
                "format": 0, "size": 0, "align": 1, "flags": 1, "subtype": 0,
                "has_format": False,
            })
        for i in range(1, num):
            name_i, pos = read_varuint(data, pos)
            count, pos = read_varuint(data, pos)
            types[i]["name"] = self.strings[name_i]
            for _ in range(count):
                pn, pos = read_varuint(data, pos)
                pv, pos = read_varuint(data, pos)
                types[i]["params"].append((self.strings[pn], pv))
        return types

    def _tbdy(self, data, start, end):
        pos = start
        for _ in range(1, len(self.types)):
            if pos >= end:
                break
            index, pos = read_varuint(data, pos)
            if index == 0:
                break
            t = self.types[index]
            t["parent"], pos = read_varuint(data, pos)
            opt, pos = read_varuint(data, pos)
            if opt & 1:
                t["format"], pos = read_varuint(data, pos)
                t["has_format"] = True
            if opt & 2:
                t["subtype"], pos = read_varuint(data, pos)
            if opt & 4:
                _ver, pos = read_varuint(data, pos)
            if opt & 8:
                t["size"], pos = read_varuint(data, pos)
                t["align"], pos = read_varuint(data, pos)
            if opt & 16:
                t["flags"], pos = read_varuint(data, pos)
            if opt & 32:
                packed, pos = read_varuint(data, pos)
                for _j in range(packed & 0xFFFF):
                    ni, pos = read_varuint(data, pos)
                    flags, pos = read_varuint(data, pos)
                    offset, pos = read_varuint(data, pos)
                    mti, pos = read_varuint(data, pos)
                    t["own"].append({
                        "name": self.field_strings[ni],
                        "flags": flags,
                        "offset": offset,
                        "type": mti,
                    })
            if opt & 64:
                niface, pos = read_varuint(data, pos)
                for _j in range(niface):
                    _, pos = read_varuint(data, pos)
                    _, pos = read_varuint(data, pos)
            if opt & 128:
                raise RuntimeError("type attributes are not supported")

    def _inherit(self):
        changed = True
        while changed:
            changed = False
            for t in self.types:
                parent = self.types[t["parent"]] if t["parent"] else None
                if parent is None:
                    continue
                if t["size"] == 0 and parent["size"]:
                    t["size"] = parent["size"]
                    t["align"] = parent["align"] or 1
                    changed = True
                if not t["has_format"] and parent["has_format"]:
                    t["format"] = parent["format"]
                    t["has_format"] = True
                    changed = True
                if t["subtype"] == 0 and parent["subtype"]:
                    t["subtype"] = parent["subtype"]
                    changed = True

    def _flatten(self):
        cache = {}

        def fields_of(index):
            if index in cache:
                return cache[index]
            t = self.types[index]
            parent = fields_of(t["parent"]) if t["parent"] else []
            own_at = {field["offset"] for field in t["own"]}
            merged = [field for field in parent if field["offset"] not in own_at]
            merged.extend(t["own"])
            merged.sort(key=lambda field: field["offset"])
            cache[index] = merged
            return merged

        for i, t in enumerate(self.types):
            t["fields"] = fields_of(i)
            if t["size"] == 0 and (t["format"] & 0xF) == 4:
                t["size"] = max(1, (t["format"] >> 10) // 8)

    def identity(self, index):
        t = self.types[index]
        if not t["params"]:
            return t["name"]
        parts = []
        for name, value in t["params"]:
            if name[:1] == "t":
                parts.append(self.identity(value))
            else:
                parts.append(str(value))
        return f"{t['name']}<{','.join(parts)}>"


def load_compendium(path):
    data = open(path, "rb").read()
    top = sections(data, 0, len(data))
    kids = child_map(data, top[0][1], top[0][2])
    return Types(data, kids["TYPE"][0], kids["TYPE"][1])


class Cursor:
    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def clone(self):
        return Cursor(self.data, self.pos)

    def raw(self):
        return self.data[self.pos:]

    def seek(self, count):
        self.pos += count

    def align(self, boundary):
        if boundary > 1:
            extra = self.pos % boundary
            if extra:
                self.pos += boundary - extra

    def u8(self):
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u16(self):
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def f32(self):
        value = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return value


class HavokFile:
    def __init__(self, types, blob):
        self.types = types
        self.blob = blob
        top = sections(blob, 0, len(blob))
        kids = child_map(blob, top[0][1], top[0][2])
        data_start = kids["DATA"][0]
        item_start, item_end = child_map(blob, kids["INDX"][0], kids["INDX"][1])["ITEM"]
        self.items = []
        pos = item_start
        while pos + 12 <= item_end:
            word, rel, count = struct.unpack_from("<III", blob, pos)
            self.items.append({
                "type": word & 0xFFFFFF,
                "kind": word >> 28,
                "offset": data_start + rel,
                "count": count,
                "objects": None,
                "reading": False,
            })
            pos += 12
        self.root = self._get(1)[0]

    def _get(self, index):
        if index == 0:
            return [None]
        item = self.items[index]
        if item["objects"] is None:
            if item["reading"]:
                return []
            item["reading"] = True
            item["objects"] = []
            pos = item["offset"]
            typ = self.types.types[item["type"]]
            for _ in range(item["count"]):
                if typ["align"] > 1:
                    extra = pos % typ["align"]
                    if extra:
                        pos += typ["align"] - extra
                value, pos = self._read(typ, pos)
                item["objects"].append(value)
        return item["objects"]

    def _read(self, typ, pos):
        kind = typ["format"] & 0xF
        name = typ["name"]
        if kind == 8 and name == "hkArray":
            pointer = struct.unpack_from("<Q", self.blob, pos)[0]
            pos += 16
            return ([] if pointer == 0 else list(self._get(pointer))), pos
        if kind == 8 and name == "hkRelArray":
            pointer = struct.unpack_from("<I", self.blob, pos)[0]
            pos += 4
            return ([] if pointer == 0 else list(self._get(pointer))), pos
        if kind == 8:
            count = typ["format"] >> 8
            sub = self.types.types[typ["subtype"]]
            values = []
            for _ in range(count):
                value, pos = self._read(sub, pos)
                values.append(value)
            return values, pos
        if kind == 6:
            pointer = struct.unpack_from("<Q", self.blob, pos)[0]
            pos += 8
            if pointer == 0:
                return None, pos
            values = self._get(pointer)
            return (values[0] if values else None), pos
        if kind == 3:
            if typ["format"] & 0x10:
                length = typ["format"] >> 16
                raw = self.blob[pos:pos + length]
                return raw.split(b"\x00", 1)[0].decode("utf-8", "replace"), pos + length
            pointer = struct.unpack_from("<Q", self.blob, pos)[0]
            pos += 8
            if pointer == 0:
                return "", pos
            chars = self._get(pointer)
            raw = bytes(int(c) & 0xFF for c in chars)
            return raw.split(b"\x00", 1)[0].decode("utf-8", "replace"), pos
        if kind == 5:
            return self._float(typ, pos)
        if kind in (2, 4):
            return self._int(typ, pos)
        if kind == 7 or typ["fields"]:
            return self._record(typ, pos)
        raise RuntimeError(f"unsupported kind {kind} for {name}")

    def _float(self, typ, pos):
        size = typ["size"] or 4
        big = ">" if typ["format"] & 0x100 else "<"
        if size == 4:
            return struct.unpack_from(big + "f", self.blob, pos)[0], pos + 4
        if size == 8:
            return struct.unpack_from(big + "d", self.blob, pos)[0], pos + 8
        if size == 16:
            value = struct.unpack_from(big + "f", self.blob, pos)[0]
            return value, pos + 16
        raise RuntimeError(f"float size {size}")

    def _int(self, typ, pos):
        size = typ["size"] or max(1, (typ["format"] >> 10) // 8)
        big = typ["format"] & 0x100
        signed = bool(typ["format"] & 0x200) or typ["name"] in ("int", "short", "long") or typ["name"].startswith("hkInt")
        endian = ">" if big else "<"
        if size == 1:
            value = self.blob[pos]
            if signed and value >= 128:
                value -= 256
            return value, pos + 1
        code = {2: "h", 4: "i", 8: "q"}[size]
        if not signed:
            code = code.upper()
        return struct.unpack_from(endian + code, self.blob, pos)[0], pos + size

    def _record(self, typ, pos):
        start = pos
        values = {}
        for field in typ["fields"]:
            gap = field["offset"] - (pos - start)
            if gap < 0:
                raise RuntimeError(f"{typ['name']}.{field['name']} overlapped")
            pos += gap
            field_type = self.types.types[field["type"]]
            if field["flags"] & 1:
                pos += field_type["size"]
                continue
            values[field["name"]], pos = self._read(field_type, pos)
        end = start + typ["size"]
        if pos > end:
            raise RuntimeError(f"{typ['name']} read {pos - start} of {typ['size']}")
        return values, end


def _find_span(n, degree, u, knots):
    if u >= knots[n + 1]:
        return n
    if u <= knots[0]:
        return degree
    low = degree
    high = n + 1
    mid = (low + high) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            high = mid
        else:
            low = mid
        mid = (low + high) // 2
    return mid

def _read_knots(reader, quantized_time, frame_duration):
    n = reader.u16()
    degree = reader.u8()
    raw = reader.raw()
    span = _find_span(n, degree, quantized_time, raw)
    knots = [0.0] * (2 * degree)
    for i in range(2 * degree):
        # Knot bytes are absolute frame numbers and may skip frames.
        # The window has to be the knots around this span, not the first knots shifted by the span.
        knots[i] = raw[i + span - degree + 1] * frame_duration
    reader.seek(n + degree + 2)
    return n, degree, knots, span

def _unpack_quat32(data):
    packed = int.from_bytes(data[:4], "little")
    low = float(packed & 0x3FFFF)
    high = float((packed & 0xFFC0000) >> 18) / 1023.0
    value = 1.0 - high * high
    a = low ** 0.5
    b = low - a * a
    c = 1e30 if a == 0 else 1.0 / (a + a)
    theta = a / 511.0 * (3.14159265 / 2.0)
    phi = b * c * (3.14159265 / 2.0)
    import math
    result = [
        math.sin(theta) * math.cos(phi),
        math.sin(theta) * math.sin(phi),
        math.cos(theta),
        1.0,
    ]
    scale = math.sqrt(max(0.0, 1.0 - value * value))
    result = [item * scale for item in result]
    result[3] = value
    mask = packed >> 28
    for i in range(4):
        if mask & (1 << i):
            result[i] = -result[i]
    return result

def _unpack_quat40(data):
    permute = bytes([0, 1, 0, 0, 1, 2, 0, 0, 3, 4, 0, 0, 0, 0, 0, 0])
    block = data[:8].ljust(8, b"\x00")
    shuffled = bytes(block[permute[i]] for i in range(16))
    words = list(struct.unpack("<4I", shuffled))
    for i in range(4):
        if (2 & (1 << i)) != 0:
            words[i] >>= 4
    mask_and = (4095, 4095, 4095, 0)
    mask_or = (0, 0, 0, 2047)
    for i in range(4):
        words[i] = (words[i] & mask_and[i]) | mask_or[i]
    result = [((words[i] - 2047.0) / 2895.0) for i in range(3)]
    result.append(1.0)
    length_sq = sum(v * v for v in result[:3])
    import math
    remaining = math.sqrt(max(0.0, 1.0 - length_sq))
    second = int.from_bytes(data[4:8].ljust(4, b"\x00"), "little")
    if second & 64:
        remaining = -remaining
    which = second & 48
    if which == 0:
        return [remaining, result[0], result[1], result[2]]
    if which == 16:
        return [result[0], remaining, result[1], result[2]]
    if which == 32:
        return [result[0], result[1], remaining, result[2]]
    return [result[0], result[1], result[2], remaining]

def _unpack_quat48(data):
    a, b, c = struct.unpack_from("<3H", data)
    item1, item2, item3 = a & 0x7FFF, b & 0x7FFF, c & 0x7FFF
    missing = ((b & 0x8000) >> 14) | ((a & 0x8000) >> 15)
    vals = [0x3FFF, 0x3FFF, 0x3FFF, 0x3FFF]
    index = int(missing == 0)
    vals[index] = item1
    index += 1 + int(missing == index + 1)
    vals[index] = item2
    index += 1 + int(missing == index + 1)
    vals[index] = item3
    result = [((v - 16383.0) / 23169.0) for v in vals]
    import math
    length_sq = sum(v * v for v in result)
    remaining = math.sqrt(max(0.0, 1.0 - length_sq))
    if c & 0x8000:
        remaining = -remaining
    result[missing] = remaining
    return result

_QUAT_ALIGN = {0: 4, 1: 1, 2: 2, 3: 1, 4: 2, 5: 4}
_QUAT_BYTES = {0: 4, 1: 5, 2: 6, 3: 3, 4: 2, 5: 16}

def _unpack_quat(kind, data):
    if kind == 0:
        return _unpack_quat32(data)
    if kind == 1:
        return _unpack_quat40(data)
    if kind == 2:
        return _unpack_quat48(data)
    raise RuntimeError(f"rotation quantization {kind}")

def _read_quats(reader, kind, n, degree, span):
    reader.align(_QUAT_ALIGN[kind])
    width = _QUAT_BYTES[kind]
    raw = reader.raw()
    values = []
    for i in range(degree + 1):
        at = width * (i + span - degree)
        values.append(_unpack_quat(kind, raw[at:at + 16]))
    reader.seek(width * (n + 1))
    return values

def _recompose(mask, static, identity, values):
    inverted = (~mask) & 0xFF
    dynamic = (inverted >> 4) & (inverted & 0x0F)
    static_mask = mask & 0x0F
    for i in range(4):
        if static_mask & (1 << i):
            values[i] = static[i]
    for i in range(4):
        if dynamic & (1 << i):
            values[i] = identity[i]
    return values

def _evaluate(time, degree, knots, points):
    if degree == 1:
        span = knots[1] - knots[0]
        t = 0.0 if span == 0 else (time - knots[0]) / span
        return [points[0][i] + t * (points[1][i] - points[0][i]) for i in range(4)]
    values = [1.0] * 16
    low = [0.0] * 16
    high = [0.0] * 16
    previous = degree - 1
    for i in range(1, degree + 1):
        high[4 * i] = time - knots[previous + 1 - i]
        low[4 * i] = knots[i + previous] - time
        carry = 0.0
        for j in range(i):
            denom = low[4 * (j + 1)] + high[4 * (i - j)]
            ratio = 0.0 if denom == 0 else values[4 * j] / denom
            values[4 * j] = carry + low[4 * (j + 1)] * ratio
            carry = high[4 * (i - j)] * ratio
        values[4 * i] = carry
    result = [0.0, 0.0, 0.0, 0.0]
    for i in range(degree + 1):
        for j in range(4):
            result[j] += values[4 * i] * points[i][j]
    return result

def _unpack8(mins, maxs, raw):
    return [((raw[i] / 255.0) * (maxs[i] - mins[i]) + mins[i]) for i in range(4)]

def _unpack16(mins, maxs, raw):
    return [((raw[i] / 65535.0) * (maxs[i] - mins[i]) + mins[i]) for i in range(4)]

def _read_curve(reader, scalar_kind, quantized_time, frame_duration, time, mask, identity):
    static = [0.0, 0.0, 0.0, 1.0]
    minimum = [0.0, 0.0, 0.0, 1.0]
    maximum = [0.0, 0.0, 0.0, 1.0]
    if mask & 0xF0:
        n, degree, knots, span = _read_knots(reader, quantized_time, frame_duration)
    else:
        n = degree = span = 0
        knots = [0.0] * 10
    reader.align(4)
    for i in range(3):
        if mask & (1 << i):
            static[i] = reader.f32()
        elif mask & (1 << (i + 4)):
            minimum[i] = reader.f32()
            maximum[i] = reader.f32()
    if mask & 0xF0:
        width = 1 if scalar_kind == 0 else 2
        reader.align(2)
        size = [0, 1, 1, 2, 1, 2, 2, 3][(mask >> 4) & 7]
        source = reader.clone()
        source.seek(width * size * (span - degree))
        points = []
        for _ in range(degree + 1):
            if scalar_kind == 0:
                raw = [0, 0, 0, 0]
                for j in range(3):
                    if mask & (1 << (j + 4)):
                        raw[j] = source.u8()
                point = _unpack8(minimum, maximum, raw)
            else:
                raw = [0, 0, 0, 0]
                for j in range(3):
                    if mask & (1 << (j + 4)):
                        raw[j] = source.u16()
                point = _unpack16(minimum, maximum, raw)
            points.append(_recompose(mask, static, identity, point))
        reader.seek(width * size * (n + 1))
        return _evaluate(time, degree, knots, points)
    return _recompose(mask, static, identity, identity[:])

def _read_quat_curve(reader, kind, quantized_time, frame_duration, time, mask):
    if mask & 0xF0:
        n, degree, knots, span = _read_knots(reader, quantized_time, frame_duration)
        points = _read_quats(reader, kind, n, degree, span)
        return _evaluate(time, degree, knots, points)
    if mask & 0x0F:
        reader.align(_QUAT_ALIGN[kind])
        value = _unpack_quat(kind, reader.raw())
        reader.seek(_QUAT_BYTES[kind])
        return value
    return [0.0, 0.0, 0.0, 1.0]

def sample_spline(anim, time):
    duration = float(anim["duration"])
    frames = int(anim["numFrames"])
    blocks = int(anim["numBlocks"])
    per_block = int(anim["maxFramesPerBlock"])
    mask_size = int(anim["maskAndQuantizationSize"]) & 0x7FFFFFFF
    inverse = float(anim["blockInverseDuration"])
    frame_duration = float(anim["frameDuration"])
    offsets = [int(v) & 0xFFFFFFFF for v in anim["blockOffsets"]]
    data = bytes(int(v) & 0xFF for v in anim["data"])
    tracks = int(anim["numberOfTransformTracks"])
    if frames <= 1 or duration <= 0:
        frame_f = 0.0
    else:
        frame_f = max(0.0, min(frames - 1.0001, (time / duration) * (frames - 1)))
    frame = int(frame_f)
    delta = frame_f - frame
    block = 0
    if per_block > 1:
        block = frame // (per_block - 1)
    block = max(0, min(blocks - 1, block))
    first = block * (per_block - 1) if per_block > 1 else 0
    block_time = (frame - first + delta) * frame_duration
    quantized = int((block_time * inverse) * (per_block - 1)) if per_block > 1 else 0
    quantized = max(0, min(255, quantized))
    base = offsets[block]
    payload = Cursor(data, base + mask_size)
    mask = Cursor(data, base)
    pose = []
    for _ in range(tracks):
        packed = mask.u8()
        translation_q = packed & 3
        rotation_q = (packed >> 2) & 0x0F
        scale_q = (packed >> 6) & 3
        translation = _read_curve(payload, translation_q, quantized, frame_duration, block_time, mask.u8(), [0, 0, 0, 0])
        payload.align(4)
        rotation = _read_quat_curve(payload, rotation_q, quantized, frame_duration, block_time, mask.u8())
        payload.align(4)
        scale = _read_curve(payload, scale_q, quantized, frame_duration, block_time, mask.u8(), [1, 1, 1, 1])
        payload.align(4)
        pose.append((translation, rotation, scale))
    return pose

def animation_clip(root):
    container = None
    for variant in root.get("namedVariants") or []:
        value = variant.get("variant") if isinstance(variant, dict) else None
        if isinstance(value, dict) and "animations" in value:
            container = value
            break
    if container is None:
        raise RuntimeError("animation container not found")
    anims = container.get("animations") or []
    bindings = container.get("bindings") or []
    if not anims or not isinstance(anims[0], dict):
        raise RuntimeError("clip has no animation")
    anim = anims[0]
    if "data" not in anim or "numFrames" not in anim:
        raise RuntimeError("only spline clips are supported, found " + ",".join(anim.keys()))
    binding = bindings[0] if bindings else {}
    bones = [int(v) for v in (binding.get("transformTrackToBoneIndices") or [])]
    return anim, bones

def summarize(path_comp, path_hkx):
    types = load_compendium(path_comp)
    root = HavokFile(types, open(path_hkx, "rb").read()).root
    anim, bones = animation_clip(root)
    print("duration", anim["duration"], "frames", anim["numFrames"], "blocks", anim["numBlocks"], "per", anim["maxFramesPerBlock"])
    print("tracks", anim["numberOfTransformTracks"], "mask", anim["maskAndQuantizationSize"], "data", len(anim["data"]), "map", len(bones))
    a = sample_spline(anim, 0.0)
    b = sample_spline(anim, float(anim["duration"]) * 0.5)
    moved = 0
    for left, right in zip(a, b):
        if sum(abs(left[0][i] - right[0][i]) for i in range(3)) > 0.001 or sum(abs(left[1][i] - right[1][i]) for i in range(4)) > 0.001:
            moved += 1
    print("moved_tracks", moved, "/", len(a))
    print("track0_t0", [round(v, 4) for v in a[0][0][:3]], [round(v, 4) for v in a[0][1]])
    print("track0_mid", [round(v, 4) for v in b[0][0][:3]], [round(v, 4) for v in b[0][1]])

if __name__ == "__main__":
    summarize(sys.argv[1], sys.argv[2])
