using System.Numerics;
using System.Text;
using SoulsFormats;

Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: RigDump <model.flver> <out.rig>");
    return;
}

var model = FLVER2.Read(File.ReadAllBytes(args[0]));
if (model.Bones.Count == 0)
    throw new InvalidDataException("Model has no bones.");

var flip = Matrix4x4.CreateScale(1, 1, -1);
using var output = new BinaryWriter(File.Create(args[1]));
output.Write(Encoding.ASCII.GetBytes("RIG2"));
output.Write(model.Bones.Count);
foreach (var bone in model.Bones)
{
    var local = flip * bone.ComputeLocalTransform() * flip;
    if (!Matrix4x4.Decompose(local, out var scale, out var rotation, out var translation))
        throw new InvalidDataException($"Cannot decompose {bone.Name}");
    var name = Encoding.UTF8.GetBytes(bone.Name ?? "");
    output.Write((ushort)Math.Min(name.Length, ushort.MaxValue));
    output.Write(name);
    output.Write((int)bone.ParentIndex);
    output.Write(translation.X); output.Write(translation.Y); output.Write(translation.Z);
    output.Write(rotation.X); output.Write(rotation.Y); output.Write(rotation.Z); output.Write(rotation.W);
    output.Write(scale.X); output.Write(scale.Y); output.Write(scale.Z);
}

var meshes = new List<(List<float> Position, List<float> Normal, List<float> Uv, List<ushort> Joints, List<float> Weights, List<int> Indices, ushort Mask)>();
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
        indices.Add(a); indices.Add(c); indices.Add(b);
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
        position.Add(vertex.Position.X); position.Add(vertex.Position.Y); position.Add(-vertex.Position.Z);
        var nx = vertex.Normal.X; var ny = vertex.Normal.Y; var nz = -vertex.Normal.Z;
        var length = MathF.Sqrt(nx * nx + ny * ny + nz * nz);
        if (length > 1e-8f) { nx /= length; ny /= length; nz /= length; } else { nx = 0; ny = 1; nz = 0; }
        normal.Add(nx); normal.Add(ny); normal.Add(nz);
        if (vertex.UVs.Count > 0) { uv.Add(vertex.UVs[0].X); uv.Add(1f - vertex.UVs[0].Y); }
        else { uv.Add(0); uv.Add(0); }
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
            if (bone < 0 || bone >= model.Bones.Count) bone = 0;
            joint[channel] = bone;
            weight[channel] = value < 0 ? 0 : value;
            sum += weight[channel];
        }
        if (sum <= 1e-8f) { weight[0] = 1; sum = 1; }
        for (var channel = 0; channel < 4; channel++)
        {
            joints.Add((ushort)joint[channel]);
            weights.Add(weight[channel] / sum);
        }
    }
    var materialName = model.Materials[mesh.MaterialIndex].Name ?? "";
    meshes.Add((position, normal, uv, joints, weights, indices, DisplayMask(materialName)));
}
if (meshes.Count == 0)
    throw new InvalidDataException("Model has no triangles.");

output.Write(meshes.Count);
foreach (var mesh in meshes)
{
    var vertices = mesh.Position.Count / 3;
    output.Write(vertices);
    output.Write(mesh.Indices.Count);
    output.Write(mesh.Mask);
    foreach (var value in mesh.Position) output.Write(value);
    foreach (var value in mesh.Normal) output.Write(value);
    foreach (var value in mesh.Uv) output.Write(value);
    foreach (var value in mesh.Joints) output.Write(value);
    foreach (var value in mesh.Weights) output.Write(value);
    foreach (var value in mesh.Indices) output.Write(value);
}
Console.WriteLine($"bones {model.Bones.Count} meshes {meshes.Count}");

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

