using System.Numerics;
using System.Text;
using SoulsFormats;

Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
if (args.Length < 3)
{
    Console.Error.WriteLine("Usage: Assemble <out.rig> <player.flver> <part.flver>...");
    return;
}

var flip = Matrix4x4.CreateScale(1, 1, -1);
var player = FLVER2.Read(File.ReadAllBytes(args[1]));
var playerNames = player.Bones.Select(bone => bone.Name ?? "").ToList();
var nameIndex = new Dictionary<string, int>();
var bones = new List<(string Name, int Parent, Vector3 T, Quaternion Q, Vector3 S)>();
var playerWorld = new Matrix4x4?[player.Bones.Count];

Matrix4x4 WorldOf(int index)
{
    if (playerWorld[index] is Matrix4x4 cached)
        return cached;
    var local = player.Bones[index].ComputeLocalTransform();
    var parent = player.Bones[index].ParentIndex;
    var world = parent < 0 ? local : local * WorldOf(parent);
    playerWorld[index] = world;
    return world;
}

int AddBone(string name, int parent, Matrix4x4 local)
{
    var flipped = flip * local * flip;
    if (!Matrix4x4.Decompose(flipped, out var scale, out var rotation, out var translation))
        throw new InvalidDataException($"Cannot decompose {name}");
    bones.Add((name, parent, translation, rotation, scale));
    return bones.Count - 1;
}

for (var i = 0; i < player.Bones.Count; i++)
{
    var bone = player.Bones[i];
    AddBone(bone.Name ?? "", bone.ParentIndex, bone.ComputeLocalTransform());
    if (!nameIndex.ContainsKey(bone.Name ?? ""))
        nameIndex[bone.Name ?? ""] = i;
}

var meshes = new List<(List<float> Position, List<float> Normal, List<float> Uv, List<ushort> Joints, List<float> Weights, List<int> Indices, ushort Mask)>();

static Matrix4x4 Frame(Vector3 position, Vector3 forward, Vector3 upward)
{
    var f = forward.LengthSquared() < 1e-10f ? -Vector3.UnitZ : Vector3.Normalize(forward);
    var u = upward.LengthSquared() < 1e-10f ? Vector3.UnitY : Vector3.Normalize(upward);
    var side = Vector3.Cross(u, f);
    if (side.LengthSquared() < 1e-10f)
    {
        var helper = MathF.Abs(f.Y) < 0.9f ? Vector3.UnitY : Vector3.UnitX;
        side = Vector3.Cross(helper, f);
    }
    side = Vector3.Normalize(side);
    u = Vector3.Normalize(Vector3.Cross(f, side));
    return new Matrix4x4(
        side.X, side.Y, side.Z, 0,
        u.X, u.Y, u.Z, 0,
        f.X, f.Y, f.Z, 0,
        position.X, position.Y, position.Z, 1);
}

static bool TryInvert(Matrix4x4 matrix, out Matrix4x4 inverse) => Matrix4x4.Invert(matrix, out inverse);

(int Parent, Matrix4x4 World, string Note) Attach(FLVER2 model, string path)
{
    var file = path.Replace('\\', '/').ToLowerInvariant();
    var left = file.Contains("/wp_a_07");
    short handId = left ? (short)130 : (short)120;
    var handName = left ? "L_Weapon" : "R_Weapon";
    var weaponGrip = model.Dummies.FirstOrDefault(dummy => dummy.ReferenceID == 120);
    var sheathRoot = model.Bones.FindIndex(bone => bone.Name == "Sheath_master");
    if (weaponGrip != null)
    {
        var hand = player.Dummies.FirstOrDefault(item => item.ReferenceID == handId && item.AttachBoneIndex >= 0 && item.AttachBoneIndex < playerNames.Count && playerNames[item.AttachBoneIndex] == handName);
        if (hand != null && nameIndex.TryGetValue(handName, out var parent) && TryInvert(Frame(weaponGrip.Position, weaponGrip.Forward, weaponGrip.Upward), out var inverseGrip))
        {
            var world = inverseGrip * Frame(hand.Position, hand.Forward, hand.Upward);
            var grip = Vector3.Transform(weaponGrip.Position, world);
            var tip = Vector3.Transform(weaponGrip.Position + Vector3.Normalize(weaponGrip.Forward), world);
            var aimed = Vector3.Normalize(tip - grip);
            var wanted = Vector3.Normalize(hand.Forward);
            var angle = MathF.Acos(Math.Clamp(Vector3.Dot(aimed, wanted), -1f, 1f)) * 180f / MathF.PI;
            Console.WriteLine($"orient {handId} {handName} angle {angle:0.0} grip {grip.X:0.###},{grip.Y:0.###},{grip.Z:0.###}");
            return (parent, world, handName);
        }
    }
    else if (sheathRoot >= 0 && nameIndex.ContainsKey("Sheath"))
    {
        var dummy = player.Dummies.FirstOrDefault(item => item.ReferenceID == 147 && item.AttachBoneIndex >= 0 && item.AttachBoneIndex < playerNames.Count && playerNames[item.AttachBoneIndex] == "Sheath");
        if (dummy != null && nameIndex.TryGetValue("Sheath", out var parent) && TryInvert(Frame(Vector3.Zero, -Vector3.UnitZ, Vector3.UnitY), out var inverseSheath))
        {
            var world = inverseSheath * Frame(dummy.Position, dummy.Forward, dummy.Upward);
            var mouth = Vector3.Transform(Vector3.Zero, world);
            var tip = Vector3.Transform(-Vector3.UnitY, world);
            var aimed = Vector3.Normalize(tip - mouth);
            var fromDown = MathF.Acos(Math.Clamp(Vector3.Dot(aimed, -Vector3.UnitY), -1f, 1f)) * 180f / MathF.PI;
            Console.WriteLine($"orient 147 Sheath fromDown {fromDown:0.0} mouth {mouth.X:0.###},{mouth.Y:0.###},{mouth.Z:0.###} tip {aimed.X:0.###},{aimed.Y:0.###},{aimed.Z:0.###}");
            return (parent, world, "Sheath");
        }
    }
    else if (file.Contains("/wp_a_") && nameIndex.ContainsKey(handName))
    {
        var hand = player.Dummies.FirstOrDefault(item => item.ReferenceID == handId && item.AttachBoneIndex >= 0 && item.AttachBoneIndex < playerNames.Count && playerNames[item.AttachBoneIndex] == handName);
        if (hand != null && TryInvert(Frame(Vector3.Zero, -Vector3.UnitZ, Vector3.UnitY), out var inverseGrip))
            return (nameIndex[handName], inverseGrip * Frame(hand.Position, hand.Forward, hand.Upward), handName);
    }
    return (-1, Matrix4x4.Identity, "");
}

void AddPart(string path)
{
    var model = FLVER2.Read(File.ReadAllBytes(path));
    var needed = new HashSet<int>();
    foreach (var mesh in model.Meshes)
    {
        if (mesh.Vertices == null)
            continue;
        foreach (var vertex in mesh.Vertices)
        {
            for (var channel = 0; channel < 4; channel++)
            {
                var weight = channel < vertex.BoneWeights.Length ? vertex.BoneWeights[channel] : 0f;
                if (weight <= 1e-4f)
                    continue;
                var localIndex = channel < vertex.BoneIndices.Length ? vertex.BoneIndices[channel] : 0;
                var bone = localIndex;
                if (mesh.BoneIndices != null && localIndex >= 0 && localIndex < mesh.BoneIndices.Count)
                    bone = mesh.BoneIndices[localIndex];
                if (bone >= 0 && bone < model.Bones.Count)
                    needed.Add(bone);
            }
        }
    }

    var (attachParent, weaponRoot, note) = Attach(model, path);
    var oldWorld = new Matrix4x4?[model.Bones.Count];
    Matrix4x4 OldWorld(int index)
    {
        if (oldWorld[index] is Matrix4x4 cached)
            return cached;
        var local = model.Bones[index].ComputeLocalTransform();
        var parent = model.Bones[index].ParentIndex;
        var world = parent < 0 ? local : local * OldWorld(parent);
        oldWorld[index] = world;
        return world;
    }
    var handWorld = attachParent >= 0 ? WorldOf(attachParent) : Matrix4x4.Identity;
    if (attachParent >= 0 && !TryInvert(handWorld, out _))
        attachParent = -1;

    bool HairRoot(string boneName) => boneName is "HD_L_bone1" or "HD_R_bone1";
    bool HairLink(string boneName) => boneName is "HD_L_bone2" or "HD_L_bone3" or "HD_R_bone002" or "HD_R_bone03";
    Matrix4x4 Hang(Matrix4x4 basis)
    {
        var origin = Vector3.Transform(Vector3.Zero, basis);
        var rotation = Matrix4x4.CreateRotationX(120f * MathF.PI / 180f);
        var rotated = Vector3.Transform(origin, rotation);
        rotation.M41 = origin.X - rotated.X;
        rotation.M42 = origin.Y - rotated.Y;
        rotation.M43 = origin.Z - rotated.Z;
        return basis * rotation;
    }
    var posed = new Matrix4x4?[model.Bones.Count];
    Matrix4x4 Posed(int boneIndex)
    {
        if (posed[boneIndex] is Matrix4x4 cached)
            return cached;
        var boneName = model.Bones[boneIndex].Name ?? "";
        var boneParent = model.Bones[boneIndex].ParentIndex;
        Matrix4x4 result;
        if (HairRoot(boneName))
            result = Hang(OldWorld(boneIndex));
        else
        {
            var boneLocal = model.Bones[boneIndex].ComputeLocalTransform();
            if (HairLink(boneName))
                boneLocal = Matrix4x4.CreateRotationX(30f * MathF.PI / 180f) * boneLocal;
            result = boneParent < 0 ? boneLocal : boneLocal * Posed(boneParent);
        }
        posed[boneIndex] = result;
        return result;
    }
    Vector3 Drape(Vector3 value, int[] joints, float[] weights, bool normal)
    {
        var moved = Vector3.Zero;
        var sum = 0f;
        for (var channel = 0; channel < 4; channel++)
        {
            var weight = weights[channel];
            if (weight <= 0f)
                continue;
            sum += weight;
            var bone = joints[channel];
            var boneName = bone >= 0 && bone < model.Bones.Count ? model.Bones[bone].Name ?? "" : "";
            if ((HairRoot(boneName) || HairLink(boneName)) && TryInvert(OldWorld(bone), out var inverseOld))
            {
                var delta = inverseOld * Posed(bone);
                moved += (normal ? Vector3.TransformNormal(value, delta) : Vector3.Transform(value, delta)) * weight;
            }
            else
                moved += value * weight;
        }
        if (sum <= 1e-8f)
            return value;
        if (sum < 1f)
            moved += value * (1f - sum);
        return moved;
    }
    var remap = new int[model.Bones.Count];
    var done = new bool[model.Bones.Count];
    int Ensure(int index)
    {
        if (index < 0)
            return -1;
        if (done[index])
            return remap[index];
        done[index] = true;
        var bone = model.Bones[index];
        var parent = bone.ParentIndex;
        if (parent >= 0)
            Ensure(parent);
        var name = bone.Name ?? "";
        if (nameIndex.TryGetValue(name, out var existing))
        {
            remap[index] = existing;
            return existing;
        }
        var source = OldWorld(index);
        var moved = attachParent >= 0 ? source * weaponRoot : source;
        int parentIndex;
        Matrix4x4 local;
        if (parent < 0 && attachParent >= 0 && TryInvert(handWorld, out var inverseHand))
        {
            parentIndex = attachParent;
            local = moved * inverseHand;
        }
        else if (parent >= 0 && attachParent >= 0 && TryInvert(OldWorld(parent) * weaponRoot, out var inverseParent))
        {
            parentIndex = remap[parent];
            local = moved * inverseParent;
        }
        else
        {
            parentIndex = parent >= 0 ? remap[parent] : -1;
            local = bone.ComputeLocalTransform();
            if (HairRoot(name) && parent >= 0 && TryInvert(OldWorld(parent), out var inverseHead))
                local = Hang(OldWorld(index)) * inverseHead;
            else if (HairLink(name))
                local = Matrix4x4.CreateRotationX(30f * MathF.PI / 180f) * local;
        }
        remap[index] = AddBone(name, parentIndex, local);
        nameIndex[name] = remap[index];
        return remap[index];
    }
    foreach (var index in needed.OrderBy(index => index))
        Ensure(index);

    var written = 0;
    foreach (var mesh in model.Meshes)
    {
        if (mesh.Vertices == null || mesh.Vertices.Count == 0)
            continue;
        var faces = mesh.GetFaces(FLVER2.FaceSet.FSFlags.None);
        if (faces == null || faces.Count == 0)
            continue;
        var indexOf = new Dictionary<FLVER.Vertex, int>();
        for (var i = 0; i < mesh.Vertices.Count; i++)
            indexOf[mesh.Vertices[i]] = i;
        var indices = new List<int>();
        foreach (var face in faces)
        {
            if (!indexOf.TryGetValue(face[0], out var a) || !indexOf.TryGetValue(face[1], out var b) || !indexOf.TryGetValue(face[2], out var c))
                continue;
            indices.Add(a);
            indices.Add(c);
            indices.Add(b);
        }
        if (indices.Count < 3)
            continue;
        var position = new List<float>(mesh.Vertices.Count * 3);
        var normal = new List<float>(mesh.Vertices.Count * 3);
        var uv = new List<float>(mesh.Vertices.Count * 2);
        var joints = new List<ushort>(mesh.Vertices.Count * 4);
        var weights = new List<float>(mesh.Vertices.Count * 4);
        foreach (var vertex in mesh.Vertices)
        {
            var sourceJoints = new int[4];
            var influence = new float[4];
            for (var channel = 0; channel < 4; channel++)
            {
                var localIndex = channel < vertex.BoneIndices.Length ? vertex.BoneIndices[channel] : 0;
                var bone = localIndex;
                if (mesh.BoneIndices != null && localIndex >= 0 && localIndex < mesh.BoneIndices.Count)
                    bone = mesh.BoneIndices[localIndex];
                sourceJoints[channel] = bone;
                influence[channel] = channel < vertex.BoneWeights.Length ? vertex.BoneWeights[channel] : 0f;
            }
            var point = Drape(vertex.Position, sourceJoints, influence, false);
            var direction = Drape(vertex.Normal, sourceJoints, influence, true);
            if (attachParent >= 0)
            {
                point = Vector3.Transform(point, weaponRoot);
                direction = Vector3.TransformNormal(direction, weaponRoot);
            }
            position.Add(point.X);
            position.Add(point.Y);
            position.Add(-point.Z);
            var nx = direction.X;
            var ny = direction.Y;
            var nz = -direction.Z;
            var length = MathF.Sqrt(nx * nx + ny * ny + nz * nz);
            if (length > 1e-8f)
            {
                nx /= length;
                ny /= length;
                nz /= length;
            }
            else
            {
                nx = 0;
                ny = 1;
                nz = 0;
            }
            normal.Add(nx);
            normal.Add(ny);
            normal.Add(nz);
            if (vertex.UVs.Count > 0)
            {
                uv.Add(vertex.UVs[0].X);
                uv.Add(1f - vertex.UVs[0].Y);
            }
            else
            {
                uv.Add(0);
                uv.Add(0);
            }
            float sum = 0;
            var joint = new int[4];
            var weight = new float[4];
            for (var channel = 0; channel < 4; channel++)
            {
                var localIndex = channel < vertex.BoneIndices.Length ? vertex.BoneIndices[channel] : 0;
                var value = channel < vertex.BoneWeights.Length ? vertex.BoneWeights[channel] : 0f;
                var bone = localIndex;
                if (mesh.BoneIndices != null && localIndex >= 0 && localIndex < mesh.BoneIndices.Count)
                    bone = mesh.BoneIndices[localIndex];
                var mapped = bone >= 0 && bone < remap.Length && done[bone] ? remap[bone] : 0;
                if (mapped < 0)
                    mapped = 0;
                joint[channel] = mapped;
                weight[channel] = value < 0 ? 0 : value;
                sum += weight[channel];
            }
            if (sum <= 1e-8f)
            {
                weight[0] = 1;
                sum = 1;
            }
            for (var channel = 0; channel < 4; channel++)
            {
                joints.Add((ushort)joint[channel]);
                weights.Add(weight[channel] / sum);
            }
        }
        meshes.Add((position, normal, uv, joints, weights, indices, DisplayMask(model.Materials[mesh.MaterialIndex].Name ?? "")));
        written++;
    }
    Console.WriteLine($"{Path.GetFileName(path)} {note} meshes {written} bonesNow {bones.Count}");
}

static List<string> Choose(IEnumerable<string> paths)
{
    var kept = new List<string>();
    foreach (var group in paths.GroupBy(path => Path.GetDirectoryName(path) ?? ""))
    {
        var rows = new List<(string Path, int Vertices, bool Grip)>();
        foreach (var path in group)
        {
            if (!path.Replace('\\', '/').ToLowerInvariant().Contains("/wp_a_"))
            {
                kept.Add(path);
                continue;
            }
            var model = FLVER2.Read(File.ReadAllBytes(path));
            var vertices = model.Meshes.Sum(mesh => mesh.Vertices?.Count ?? 0);
            if (vertices == 0)
                continue;
            rows.Add((path, vertices, model.Dummies.Any(dummy => dummy.ReferenceID == 120)));
        }
        var grips = rows.Where(row => row.Grip).ToList();
        if (grips.Count > 0)
            kept.Add(grips.OrderByDescending(row => row.Vertices).First().Path);
        kept.AddRange(rows.Where(row => !row.Grip).Select(row => row.Path));
    }
    return kept;
}

foreach (var path in Choose(args.Skip(2)))
    AddPart(path);

using var output = new BinaryWriter(File.Create(args[0]));
output.Write(Encoding.ASCII.GetBytes("RIG2"));
output.Write(bones.Count);
foreach (var bone in bones)
{
    var name = Encoding.UTF8.GetBytes(bone.Name);
    output.Write((ushort)Math.Min(name.Length, ushort.MaxValue));
    output.Write(name);
    output.Write(bone.Parent);
    output.Write(bone.T.X);
    output.Write(bone.T.Y);
    output.Write(bone.T.Z);
    output.Write(bone.Q.X);
    output.Write(bone.Q.Y);
    output.Write(bone.Q.Z);
    output.Write(bone.Q.W);
    output.Write(bone.S.X);
    output.Write(bone.S.Y);
    output.Write(bone.S.Z);
}
output.Write(meshes.Count);
foreach (var mesh in meshes)
{
    output.Write(mesh.Position.Count / 3);
    output.Write(mesh.Indices.Count);
    output.Write(mesh.Mask);
    foreach (var value in mesh.Position) output.Write(value);
    foreach (var value in mesh.Normal) output.Write(value);
    foreach (var value in mesh.Uv) output.Write(value);
    foreach (var value in mesh.Joints) output.Write(value);
    foreach (var value in mesh.Weights) output.Write(value);
    foreach (var value in mesh.Indices) output.Write(value);
}
Console.WriteLine($"bones {bones.Count} meshes {meshes.Count}");

static ushort DisplayMask(string name)
{
    var first = name.IndexOf('#');
    if (first < 0)
        return ushort.MaxValue;
    var second = name.IndexOf('#', first + 1);
    if (second <= first + 1)
        return ushort.MaxValue;
    return ushort.TryParse(name.Substring(first + 1, second - first - 1), out var mask) ? mask : ushort.MaxValue;
}
