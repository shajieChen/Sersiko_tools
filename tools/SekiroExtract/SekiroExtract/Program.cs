using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Coremats;
using SoulsFormats;
using CoreBhd = Coremats.BHD5;
using CoreDcx = Coremats.DCX;

Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: SekiroExtract <config.json> <keys directory>");
    return;
}
var configPath = Path.GetFullPath(args[0]);
var keysDir = Path.GetFullPath(args[1]);
if (!File.Exists(configPath))
{
    Console.Error.WriteLine("config not found: " + configPath);
    return;
}
if (!Directory.Exists(keysDir))
{
    Console.Error.WriteLine("keys directory not found: " + keysDir);
    return;
}
using var configDoc = JsonDocument.Parse(File.ReadAllText(configPath));
var gameDir = configDoc.RootElement.GetProperty("gameDir").GetString() ?? "";
var outDir = configDoc.RootElement.GetProperty("resourceDir").GetString() ?? "";
if (!Directory.Exists(gameDir))
{
    Console.Error.WriteLine("gameDir does not exist. Run SetGameDir.bat. " + gameDir);
    return;
}
if (string.IsNullOrWhiteSpace(outDir))
{
    Console.Error.WriteLine("resourceDir is empty. Run SetGameDir.bat.");
    return;
}
Directory.CreateDirectory(outDir);

var oodleSource = Path.Combine(gameDir, "oo2core_6_win64.dll");
var oodleTarget = Path.Combine(AppContext.BaseDirectory, "oo2core_6_win64.dll");
if (!File.Exists(oodleTarget))
    File.Copy(oodleSource, oodleTarget);

var rawRoot = Path.Combine(outDir, "raw");
var unpackedRoot = Path.Combine(outDir, "unpacked");
var previewRoot = Path.Combine(outDir, "preview");
Directory.CreateDirectory(rawRoot);
Directory.CreateDirectory(unpackedRoot);
Directory.CreateDirectory(previewRoot);

var errors = new List<string>();
foreach (var archive in new[] { "Data2", "Data3", "Data4" })
    ExtractArchive(archive, rawRoot, errors, gameDir, keysDir);

Console.WriteLine("Unpacking binders...");
int binders = 0, innerFiles = 0;
foreach (var dcxPath in Directory.EnumerateFiles(rawRoot, "*.dcx", SearchOption.AllDirectories))
{
    try
    {
        innerFiles += UnpackBinder(dcxPath, rawRoot, unpackedRoot);
        binders++;
        if (binders % 100 == 0)
            Console.WriteLine($"  binders {binders}");
    }
    catch (Exception ex)
    {
        errors.Add($"{dcxPath}: {ex.GetType().Name}: {ex.Message}");
    }
}
Console.WriteLine($"Binders {binders}, inner files {innerFiles}");

Console.WriteLine("Exporting preview models...");
var glbs = new List<string>();
foreach (var flverPath in Directory.EnumerateFiles(unpackedRoot, "*.flver", SearchOption.AllDirectories))
{
    try
    {
        var relative = Path.GetRelativePath(unpackedRoot, flverPath);
        var glbPath = Path.Combine(previewRoot, Path.ChangeExtension(relative, ".glb"));
        if (File.Exists(glbPath) && new FileInfo(glbPath).Length > 0)
        {
            glbs.Add(Path.GetRelativePath(previewRoot, glbPath).Replace('\\', '/'));
            continue;
        }
        Directory.CreateDirectory(Path.GetDirectoryName(glbPath)!);
        ExportGlb(flverPath, glbPath);
        glbs.Add(Path.GetRelativePath(previewRoot, glbPath).Replace('\\', '/'));
        if (glbs.Count % 50 == 0)
            Console.WriteLine($"  glb {glbs.Count}");
    }
    catch (Exception ex)
    {
        errors.Add($"{flverPath}: {ex.GetType().Name}: {ex.Message}");
    }
}

var hkx = Directory.EnumerateFiles(unpackedRoot, "*.hkx", SearchOption.AllDirectories)
    .Select(path => Path.GetRelativePath(unpackedRoot, path).Replace('\\', '/'))
    .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
    .ToList();
var flvers = Directory.EnumerateFiles(unpackedRoot, "*.flver", SearchOption.AllDirectories)
    .Select(path => Path.GetRelativePath(unpackedRoot, path).Replace('\\', '/'))
    .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
    .ToList();
glbs.Sort(StringComparer.OrdinalIgnoreCase);
File.WriteAllText(Path.Combine(outDir, "catalog.json"), JsonSerializer.Serialize(new { models = flvers, animations = hkx, preview = glbs }, new JsonSerializerOptions { WriteIndented = true }));
File.WriteAllLines(Path.Combine(outDir, "errors.txt"), errors);
Console.WriteLine($"Models {flvers.Count}, animations {hkx.Count}, preview {glbs.Count}, errors {errors.Count}");

static void ExtractArchive(string archive, string rawRoot, List<string> errors, string gameDir, string keysDir)
{
    var bhdPath = Path.Combine(gameDir, archive + ".bhd");
    var bdtPath = Path.Combine(gameDir, archive + ".bdt");
    var pem = File.ReadAllText(Path.Combine(keysDir, "Key", archive + ".pem"));
    var headerBytes = File.ReadAllBytes(bhdPath);
    if (!CoreBhd.Is(headerBytes))
        headerBytes = Coremats.Crypto.Binder5.DecryptBhd(headerBytes, pem);
    var header = CoreBhd.Read(headerBytes, CoreBhd.Bhd5Format.DarkSouls3);
    var names = new Dictionary<ulong, string>();
    foreach (var line in File.ReadAllLines(Path.Combine(keysDir, "Hash", archive + ".txt")))
    {
        if (!string.IsNullOrWhiteSpace(line))
            names[HashPath(line.Trim())] = line.Trim();
    }

    using var bdt = File.OpenRead(bdtPath);
    int written = 0;
    foreach (var file in header.Buckets.SelectMany(bucket => bucket))
    {
        if (!names.TryGetValue(file.PathHash, out var gamePath) || !Want(gamePath))
            continue;
        try
        {
            var output = Path.Combine(rawRoot, gamePath.TrimStart('/').Replace('/', Path.DirectorySeparatorChar));
            if (File.Exists(output) && new FileInfo(output).Length > 0)
            {
                written++;
                continue;
            }
            var bytes = ReadEntry(bdt, file);
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            File.WriteAllBytes(output, bytes);
            written++;
        }
        catch (Exception ex)
        {
            errors.Add($"{archive} {gamePath}: {ex.GetType().Name}: {ex.Message}");
        }
    }
    Console.WriteLine($"{archive}: wrote {written}");
}

static bool Want(string path)
{
    var value = path.Replace('\\', '/').ToLowerInvariant();
    if (value.Contains("/chr/") && (value.EndsWith(".chrbnd.dcx") || value.EndsWith(".anibnd.dcx") || value.EndsWith(".texbnd.dcx")))
        return true;
    if (value.Contains("/parts/") && value.EndsWith(".partsbnd.dcx"))
        return true;
    if (value.Contains("/obj/") && value.EndsWith(".objbnd.dcx"))
        return true;
    return false;
}

static ulong HashPath(string path)
{
    uint hash = 0;
    foreach (var character in path)
        hash = hash * 37 + character;
    return hash;
}

static byte[] ReadEntry(FileStream bdt, CoreBhd.File file)
{
    var buffer = new byte[file.DataLength];
    bdt.Position = file.DataOffset;
    bdt.ReadExactly(buffer);
    if (file.Encryption != null)
        DecryptEntry(file.Encryption, buffer);
    var length = file.UnpaddedDataLength != 0 ? file.UnpaddedDataLength : file.DataLength;
    return length == buffer.Length ? buffer : buffer.AsSpan(0, length).ToArray();
}

static void DecryptEntry(CoreBhd.FileEncryption encryption, byte[] buffer)
{
    using var aes = Aes.Create();
    aes.Mode = CipherMode.ECB;
    aes.Padding = PaddingMode.None;
    aes.Key = encryption.Key;
    foreach (var range in encryption.Ranges)
    {
        if (range.Start < 0 || range.End < 0 || range.Start == range.End)
            continue;
        var span = buffer.AsSpan((int)range.Start, (int)(range.End - range.Start));
        aes.DecryptEcb(span, span, PaddingMode.None);
    }
}

static int UnpackBinder(string dcxPath, string rawRoot, string unpackedRoot)
{
    var relative = Path.GetRelativePath(rawRoot, dcxPath);
    var container = Path.Combine(unpackedRoot, Path.ChangeExtension(relative, null));
    if (Directory.Exists(container) && Directory.EnumerateFileSystemEntries(container).Any())
        return 0;
    var compressed = File.ReadAllBytes(dcxPath);
    var bytes = SoulsFormats.DCX.Is(compressed) ? SoulsFormats.DCX.Decompress(compressed) : compressed;
    if (!LooksLikeBinder(bytes))
    {
        Directory.CreateDirectory(Path.GetDirectoryName(container)!);
        File.WriteAllBytes(container, bytes);
        return 1;
    }

    var bnd = ReadBinder(bytes);
    Directory.CreateDirectory(container);
    foreach (var file in bnd.Files)
    {
        var name = string.IsNullOrWhiteSpace(file.Name) ? file.ID.ToString() : InnerName(file.Name);
        var payload = file.Bytes;
        if (SoulsFormats.DCX.Is(payload))
        {
            payload = SoulsFormats.DCX.Decompress(payload);
            if (name.EndsWith(".dcx", StringComparison.OrdinalIgnoreCase))
                name = name[..^4];
        }
        var output = Path.Combine(container, name.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        File.WriteAllBytes(output, payload);
        if (name.EndsWith(".tpf", StringComparison.OrdinalIgnoreCase))
            ExtractTpf(payload, output + ".textures");
    }
    return bnd.Files.Count;
}


static string InnerName(string name)
{
    name = name.Replace('\\', '/');
    const string marker = "interroot_win64/";
    var index = name.ToLowerInvariant().LastIndexOf(marker);
    if (index >= 0)
        name = name[(index + marker.Length)..];
    else if (name.Contains(':') || name.StartsWith('/'))
        name = Path.GetFileName(name);
    name = name.TrimStart('/');
    return string.IsNullOrWhiteSpace(name) ? "unnamed" : name;
}

static bool LooksLikeBinder(byte[] bytes)
{
    if (bytes.Length < 4) return false;
    var magic = Encoding.ASCII.GetString(bytes, 0, 4);
    return magic is "BND4" or "BND3";
}

static BND4 ReadBinder(byte[] bytes)
{
    if (!BND4.Is(bytes))
        throw new InvalidDataException("Not a BND4 container.");
    return BND4.Read(bytes);
}

static void ExtractTpf(byte[] bytes, string directory)
{
    try
    {
        if (!TPF.Is(bytes)) return;
        var tpf = TPF.Read(bytes);
        Directory.CreateDirectory(directory);
        var index = 0;
        foreach (var texture in tpf.Textures)
        {
            var name = string.IsNullOrWhiteSpace(texture.Name) ? $"texture_{index}" : Path.GetFileName(texture.Name);
            foreach (var invalid in Path.GetInvalidFileNameChars())
                name = name.Replace(invalid, '_');
            File.WriteAllBytes(Path.Combine(directory, name + ".dds"), texture.Bytes);
            index++;
        }
    }
    catch { }
}

static void ExportGlb(string flverPath, string glbPath)
{
    var bytes = File.ReadAllBytes(flverPath);
    if (!FLVER2.Is(bytes))
        throw new InvalidDataException("Not a FLVER2 model.");
    var model = FLVER2.Read(bytes);
    var bin = new List<byte>();
    var bufferViews = new List<string>();
    var accessors = new List<string>();
    var primitives = new List<string>();

    int AddView(byte[] data, int target)
    {
        while (bin.Count % 4 != 0) bin.Add(0);
        var offset = bin.Count;
        bin.AddRange(data);
        bufferViews.Add(FormattableString.Invariant($"{{\"buffer\":0,\"byteOffset\":{offset},\"byteLength\":{data.Length},\"target\":{target}}}"));
        return bufferViews.Count - 1;
    }

    int AddAccessor(int view, int count, string type, int componentType, string extra)
    {
        accessors.Add($"{{\"bufferView\":{view},\"byteOffset\":0,\"componentType\":{componentType},\"count\":{count},\"type\":\"{type}\"{extra}}}");
        return accessors.Count - 1;
    }

    foreach (var mesh in model.Meshes)
    {
        if (mesh.Vertices == null || mesh.Vertices.Count == 0)
            continue;
        var triangles = mesh.GetFaces(FLVER2.FaceSet.FSFlags.None);
        if (triangles == null || triangles.Count == 0)
            continue;
        var positions = new List<float>(mesh.Vertices.Count * 3);
        var normals = new List<float>(mesh.Vertices.Count * 3);
        var uvs = new List<float>(mesh.Vertices.Count * 2);
        var joints = new List<ushort>(mesh.Vertices.Count * 4);
        var weights = new List<float>(mesh.Vertices.Count * 4);
        var skinned = false;
        var min = new Vector3(float.MaxValue);
        var max = new Vector3(float.MinValue);
        foreach (var vertex in mesh.Vertices)
        {
            var position = Flip(vertex.Position);
            var normal = Flip(vertex.Normal);
            if (normal.LengthSquared() > 0) normal = Vector3.Normalize(normal); else normal = Vector3.UnitY;
            positions.Add(position.X); positions.Add(position.Y); positions.Add(position.Z);
            normals.Add(normal.X); normals.Add(normal.Y); normals.Add(normal.Z);
            min = Vector3.Min(min, position);
            max = Vector3.Max(max, position);
            if (vertex.UVs.Count > 0) { uvs.Add(vertex.UVs[0].X); uvs.Add(1f - vertex.UVs[0].Y); }
            else { uvs.Add(0); uvs.Add(0); }
            for (var channel = 0; channel < 4; channel++)
            {
                var local = channel < vertex.BoneIndices.Length ? vertex.BoneIndices[channel] : 0;
                var weight = channel < vertex.BoneWeights.Length ? vertex.BoneWeights[channel] : 0f;
                var joint = local;
                if (mesh.BoneIndices != null && local >= 0 && local < mesh.BoneIndices.Count)
                    joint = mesh.BoneIndices[local];
                if (joint < 0) joint = 0;
                joints.Add((ushort)Math.Clamp(joint, 0, ushort.MaxValue));
                weights.Add(weight);
                if (weight > 0) skinned = true;
            }
        }
        var indexOf = new Dictionary<FLVER.Vertex, int>();
        for (var i = 0; i < mesh.Vertices.Count; i++)
            indexOf[mesh.Vertices[i]] = i;
        var indices = new List<int>(triangles.Count * 3);
        foreach (var triangle in triangles)
        {
            if (!indexOf.TryGetValue(triangle[0], out var a) || !indexOf.TryGetValue(triangle[1], out var b) || !indexOf.TryGetValue(triangle[2], out var c))
                continue;
            indices.Add(a);
            indices.Add(c);
            indices.Add(b);
        }
        if (indices.Count < 3)
            continue;
        var positionAccessor = AddAccessor(AddView(ToBytes(positions), 34962), mesh.Vertices.Count, "VEC3", 5126, $",\"min\":[{F(min.X)},{F(min.Y)},{F(min.Z)}],\"max\":[{F(max.X)},{F(max.Y)},{F(max.Z)}]");
        var normalAccessor = AddAccessor(AddView(ToBytes(normals), 34962), mesh.Vertices.Count, "VEC3", 5126, "");
        var uvAccessor = AddAccessor(AddView(ToBytes(uvs), 34962), mesh.Vertices.Count, "VEC2", 5126, "");
        var indexAccessor = AddAccessor(AddView(ToIntBytes(indices), 34963), indices.Count, "SCALAR", 5125, "");
        var attributes = $"\"POSITION\":{positionAccessor},\"NORMAL\":{normalAccessor},\"TEXCOORD_0\":{uvAccessor}";
        if (skinned && model.Bones.Count > 0)
        {
            var jointAccessor = AddAccessor(AddView(ToUShortBytes(joints), 34962), mesh.Vertices.Count, "VEC4", 5123, "");
            var weightAccessor = AddAccessor(AddView(ToBytes(weights), 34962), mesh.Vertices.Count, "VEC4", 5126, "");
            attributes += $",\"JOINTS_0\":{jointAccessor},\"WEIGHTS_0\":{weightAccessor}";
        }
        primitives.Add($"{{\"attributes\":{{{attributes}}},\"indices\":{indexAccessor},\"material\":0}}");
    }
    if (primitives.Count == 0)
        throw new InvalidDataException("Model has no triangles.");

    var nodes = new List<string>();
    var skins = "";
    var roots = new List<int>();
    if (model.Bones.Count > 0)
    {
        var flip = Matrix4x4.CreateScale(1, 1, -1);
        var worlds = new Matrix4x4[model.Bones.Count];
        var locals = new Matrix4x4[model.Bones.Count];
        var inverse = new List<float>(model.Bones.Count * 16);
        for (var i = 0; i < model.Bones.Count; i++)
        {
            locals[i] = flip * model.Bones[i].ComputeLocalTransform() * flip;
            var parent = model.Bones[i].ParentIndex;
            worlds[i] = parent >= 0 && parent < model.Bones.Count ? worlds[parent] * locals[i] : locals[i];
        }
        for (var i = 0; i < model.Bones.Count; i++)
        {
            Matrix4x4.Invert(worlds[i], out var inverted);
            AppendMatrix(inverse, inverted);
        }
        var inverseAccessor = AddAccessor(AddView(ToBytes(inverse), 34962), model.Bones.Count, "MAT4", 5126, "");
        skins = $"[{{\"inverseBindMatrices\":{inverseAccessor},\"joints\":[{string.Join(',', Enumerable.Range(1, model.Bones.Count))}],\"skeleton\":1}}]";
        nodes.Add("{\"mesh\":0,\"skin\":0,\"name\":\"model\"}");
        roots.Add(0);
        for (var i = 0; i < model.Bones.Count; i++)
        {
            var children = new List<int>();
            for (var child = 0; child < model.Bones.Count; child++)
                if (model.Bones[child].ParentIndex == i) children.Add(child + 1);
            var childJson = children.Count == 0 ? "" : $",\"children\":[{string.Join(',', children)}]";
            var name = Escape(string.IsNullOrWhiteSpace(model.Bones[i].Name) ? $"bone_{i}" : model.Bones[i].Name);
            nodes.Add($"{{\"name\":\"{name}\",\"matrix\":[{MatrixJson(locals[i])}]{childJson}}}");
            if (model.Bones[i].ParentIndex < 0) roots.Add(i + 1);
        }
    }
    else
    {
        nodes.Add("{\"mesh\":0,\"name\":\"model\"}");
        roots.Add(0);
    }
    WriteGlb(glbPath, bin, bufferViews, accessors, primitives, nodes, skins, roots);
}

static void WriteGlb(string path, List<byte> bin, List<string> views, List<string> accessors, List<string> primitives, List<string> nodes, string skins, List<int> roots)
{
    while (bin.Count % 4 != 0) bin.Add(0);
    var skinJson = string.IsNullOrEmpty(skins) ? "" : $",\"skins\":{skins}";
    var json = "{\"asset\":{\"version\":\"2.0\",\"generator\":\"SekiroExtract\"},\"scene\":0,\"scenes\":[{\"nodes\":[" + string.Join(',', roots) + "]}],\"nodes\":[" + string.Join(',', nodes) + "],\"meshes\":[{\"primitives\":[" + string.Join(',', primitives) + "]}],\"materials\":[{\"pbrMetallicRoughness\":{\"baseColorFactor\":[0.72,0.64,0.52,1],\"metallicFactor\":0,\"roughnessFactor\":0.85},\"doubleSided\":true,\"name\":\"flver\"}],\"accessors\":[" + string.Join(',', accessors) + "],\"bufferViews\":[" + string.Join(',', views) + "],\"buffers\":[{\"byteLength\":" + bin.Count + "}]" + skinJson + "}";
    var jsonBytes = Encoding.UTF8.GetBytes(json);
    if (jsonBytes.Length % 4 != 0)
    {
        var padded = new byte[jsonBytes.Length + (4 - jsonBytes.Length % 4)];
        Buffer.BlockCopy(jsonBytes, 0, padded, 0, jsonBytes.Length);
        for (var i = jsonBytes.Length; i < padded.Length; i++) padded[i] = (byte)' ';
        jsonBytes = padded;
    }
    using var output = File.Create(path);
    using var writer = new BinaryWriter(output);
    writer.Write(0x46546C67);
    writer.Write(2);
    writer.Write(12 + 8 + jsonBytes.Length + 8 + bin.Count);
    writer.Write(jsonBytes.Length);
    writer.Write(0x4E4F534A);
    writer.Write(jsonBytes);
    writer.Write(bin.Count);
    writer.Write(0x004E4942);
    writer.Write(bin.ToArray());
}

static Vector3 Flip(Vector3 value) => new(value.X, value.Y, -value.Z);
static string Escape(string value) => value.Replace("&", "&amp;").Replace("<", "&lt;").Replace("\"", "&quot;");
static string F(float value) => value.ToString("G9", System.Globalization.CultureInfo.InvariantCulture);
static string MatrixJson(Matrix4x4 matrix) => string.Join(',', new[] { matrix.M11, matrix.M21, matrix.M31, matrix.M41, matrix.M12, matrix.M22, matrix.M32, matrix.M42, matrix.M13, matrix.M23, matrix.M33, matrix.M43, matrix.M14, matrix.M24, matrix.M34, matrix.M44 }.Select(F));
static byte[] ToBytes(List<float> values) { var bytes = new byte[values.Count * 4]; Buffer.BlockCopy(values.ToArray(), 0, bytes, 0, bytes.Length); return bytes; }
static byte[] ToUShortBytes(List<ushort> values) { var bytes = new byte[values.Count * 2]; Buffer.BlockCopy(values.ToArray(), 0, bytes, 0, bytes.Length); return bytes; }
static byte[] ToIntBytes(List<int> values) { var bytes = new byte[values.Count * 4]; Buffer.BlockCopy(values.ToArray(), 0, bytes, 0, bytes.Length); return bytes; }
static void AppendMatrix(List<float> target, Matrix4x4 matrix)
{
    target.Add(matrix.M11); target.Add(matrix.M21); target.Add(matrix.M31); target.Add(matrix.M41);
    target.Add(matrix.M12); target.Add(matrix.M22); target.Add(matrix.M32); target.Add(matrix.M42);
    target.Add(matrix.M13); target.Add(matrix.M23); target.Add(matrix.M33); target.Add(matrix.M43);
    target.Add(matrix.M14); target.Add(matrix.M24); target.Add(matrix.M34); target.Add(matrix.M44);
}
