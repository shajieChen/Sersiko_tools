"""Publish one preview clip as a single glTF file (.glb) with skin and animation."""

import json
import os
import re
import shutil
import struct

def output_dir(tool):
    path = os.path.join(tool, "output")
    os.makedirs(path, exist_ok=True)
    return path

def _stem(value):
    base = os.path.splitext(os.path.basename(str(value).replace("\\", "/")))[0]
    base = re.sub(r"[^0-9A-Za-z._-]+", "_", base).strip("._")
    return base or "clip"

def clip_name(model, anim_file, weapon=""):
    parts = [_stem(model), _stem(anim_file)]
    if weapon:
        parts.append(_stem(weapon))
    return "_".join(parts) + ".glb"

def load_glb(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a glTF file")
    version, _total = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise ValueError("unsupported glTF version")
    length, kind = struct.unpack_from("<I4s", data, 12)
    if kind != b"JSON":
        raise ValueError("glTF JSON chunk is missing")
    document = json.loads(data[20:20 + length])
    bin_at = 20 + length
    bin_length, bin_kind = struct.unpack_from("<I4s", data, bin_at)
    if bin_kind != b"BIN\x00":
        raise ValueError("glTF binary chunk is missing")
    return document, data[bin_at + 8:bin_at + 8 + bin_length]

def _read(document, blob, index, limit):
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    kind = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    code = {5121: "B", 5123: "H", 5125: "I", 5126: "f"}[accessor["componentType"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = kind * struct.calcsize("<" + code)
    count = min(accessor["count"], limit)
    values = [
        struct.unpack_from("<" + code * kind, blob, offset + item * stride)
        for item in range(count)
    ]
    return accessor["count"], values

def _read_at(document, blob, index, item):
    _count, values = _read(document, blob, index, item + 1)
    return values[-1]

def require_skinned_clip(path):
    document, blob = load_glb(path)
    skins = document.get("skins") or []
    animations = document.get("animations") or []
    if not skins or not skins[0].get("joints"):
        raise ValueError("glTF has no skeleton")
    joint_count = len(skins[0]["joints"])
    primitives = [
        primitive
        for mesh in document.get("meshes") or []
        for primitive in mesh.get("primitives") or []
    ]
    weighted = 0
    for primitive in primitives:
        attributes = primitive.get("attributes") or {}
        if "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
            raise ValueError("glTF mesh has no skin weights")
        _joint_total, joints = _read(document, blob, attributes["JOINTS_0"], 64)
        _weight_total, weights = _read(document, blob, attributes["WEIGHTS_0"], 64)
        if any(index >= joint_count for point in joints for index in point):
            raise ValueError("glTF joint index is outside the skeleton")
        if any(abs(sum(point) - 1.0) < 0.05 and max(point) > 0.0 for point in weights):
            weighted += 1
    if not weighted:
        raise ValueError("glTF skin weights are empty")
    if not animations:
        raise ValueError("glTF has no animation")
    for animation in animations:
        channels = animation.get("channels") or []
        if not channels:
            raise ValueError("glTF has no animation")
        moving = False
        for channel in channels:
            sampler = animation["samplers"][channel["sampler"]]
            accessor = document["accessors"][sampler["output"]]
            if accessor["count"] < 2:
                continue
            picks = {0, accessor["count"] // 2, accessor["count"] - 1}
            samples = [_read_at(document, blob, sampler["output"], index) for index in sorted(picks)]
            if any(samples[0] != sample for sample in samples[1:]):
                moving = True
                break
        if not moving:
            raise ValueError("glTF animation does not move: " + str(animation.get("name") or ""))
    return document

def publish(source_glb, tool, model, anim_file, weapon=""):
    if not os.path.isfile(source_glb):
        raise FileNotFoundError("clip was not built")
    dest = os.path.join(output_dir(tool), clip_name(model, anim_file, weapon))
    shutil.copyfile(source_glb, dest)
    require_skinned_clip(dest)
    return dest

def category_filename(model, detail, weapon=""):
    label = re.sub(r'[\\/:*?"<>|]+', "_", str(detail)).strip(" ._") or "category"
    parts = [_stem(model), label]
    if weapon:
        parts.append(_stem(weapon))
    return "_".join(parts) + ".glb"


def publish_as(source_glb, tool, filename):
    if not os.path.isfile(source_glb):
        raise FileNotFoundError("clip was not built")
    dest = os.path.join(output_dir(tool), filename)
    shutil.copyfile(source_glb, dest)
    require_skinned_clip(dest)
    return dest
