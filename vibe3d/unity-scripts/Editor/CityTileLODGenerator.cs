using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Generates LOD meshes for CityTile OBJ photogrammetry assets using Vertex Clustering decimation.
/// Menu: Vibe3D > Generate City Tile LODs
/// </summary>
public class CityTileLODGenerator : EditorWindow
{
    // LOD level definitions: (vertex ratio, screen relative height)
    private static readonly (float ratio, float screenHeight)[] LOD_LEVELS = new[]
    {
        (1.00f, 0.50f), // LOD0: original mesh, visible when >50% screen height
        (0.40f, 0.25f), // LOD1: 40% vertices, medium distance
        (0.15f, 0.05f), // LOD2: 15% vertices, far distance
        (0.00f, 0.01f), // LOD3: culled, <1% screen height
    };

    private bool _replaceColliders = true;
    private bool _exportOBJ = true;
    private bool _processing;

    [MenuItem("Vibe3D/Generate City Tile LODs")]
    static void ShowWindow()
    {
        GetWindow<CityTileLODGenerator>("City Tile LOD Generator").Show();
    }

    void OnGUI()
    {
        GUILayout.Label("City Tile LOD Generator", EditorStyles.boldLabel);
        EditorGUILayout.Space();

        _replaceColliders = EditorGUILayout.Toggle("Replace Colliders with LOD2", _replaceColliders);
        _exportOBJ = EditorGUILayout.Toggle("Export OBJ for Web Viewer", _exportOBJ);

        EditorGUILayout.Space();
        EditorGUILayout.HelpBox(
            "LOD0: 100% (original)\nLOD1: 40% (mid-range)\nLOD2: 15% (far)\nLOD3: Culled (<1% screen)",
            MessageType.Info);

        EditorGUI.BeginDisabledGroup(_processing);
        if (GUILayout.Button("Generate LODs for All City Tiles", GUILayout.Height(40)))
        {
            _processing = true;
            GenerateAllLODs();
            _processing = false;
        }
        EditorGUI.EndDisabledGroup();
    }

    void GenerateAllLODs()
    {
        string tilesRoot = "Assets/CityTiles";
        if (!AssetDatabase.IsValidFolder(tilesRoot))
        {
            EditorUtility.DisplayDialog("Error", "Assets/CityTiles folder not found.", "OK");
            return;
        }

        string[] tileFolders = AssetDatabase.GetSubFolders(tilesRoot);
        int total = tileFolders.Length;
        int processed = 0;

        try
        {
            foreach (string tileFolder in tileFolders)
            {
                processed++;
                string tileName = Path.GetFileName(tileFolder);
                bool cancel = EditorUtility.DisplayCancelableProgressBar(
                    "Generating LODs",
                    $"Processing {tileName} ({processed}/{total})",
                    (float)processed / total);

                if (cancel) break;

                ProcessTileFolder(tileFolder, tileName);
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log($"[CityTileLOD] Completed: {processed}/{total} tiles processed.");
    }

    void ProcessTileFolder(string tileFolder, string tileName)
    {
        // Find the imported model prefab
        string[] guids = AssetDatabase.FindAssets("t:GameObject", new[] { tileFolder });
        if (guids.Length == 0)
        {
            Debug.LogWarning($"[CityTileLOD] No model found in {tileFolder}");
            return;
        }

        // Get the first model asset
        string modelPath = AssetDatabase.GUIDToAssetPath(guids[0]);
        GameObject modelPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
        if (modelPrefab == null) return;

        // Collect meshes from the model
        MeshFilter[] meshFilters = modelPrefab.GetComponentsInChildren<MeshFilter>();
        if (meshFilters.Length == 0)
        {
            // Try MeshRenderer on skinned meshes
            MeshRenderer[] renderers = modelPrefab.GetComponentsInChildren<MeshRenderer>();
            if (renderers.Length == 0)
            {
                Debug.LogWarning($"[CityTileLOD] No meshes found in {tileName}");
                return;
            }
        }

        // Create LOD output folder
        string lodFolder = $"{tileFolder}/LOD";
        if (!AssetDatabase.IsValidFolder(lodFolder))
        {
            AssetDatabase.CreateFolder(tileFolder, "LOD");
        }

        // Process each mesh filter
        foreach (MeshFilter mf in meshFilters)
        {
            Mesh srcMesh = mf.sharedMesh;
            if (srcMesh == null || !srcMesh.isReadable)
            {
                Debug.LogWarning($"[CityTileLOD] Mesh not readable: {srcMesh?.name} in {tileName}. Re-import with isReadable=true.");
                continue;
            }

            string meshBaseName = string.IsNullOrEmpty(srcMesh.name) ? tileName : srcMesh.name;

            // Generate LOD1 and LOD2 meshes (LOD0 = original)
            Mesh lod1Mesh = DecimateVertexClustering(srcMesh, LOD_LEVELS[1].ratio);
            lod1Mesh.name = $"{meshBaseName}_LOD1";
            SaveMeshAsset(lod1Mesh, $"{lodFolder}/{meshBaseName}_LOD1.asset");

            Mesh lod2Mesh = DecimateVertexClustering(srcMesh, LOD_LEVELS[2].ratio);
            lod2Mesh.name = $"{meshBaseName}_LOD2";
            SaveMeshAsset(lod2Mesh, $"{lodFolder}/{meshBaseName}_LOD2.asset");

            Debug.Log($"[CityTileLOD] {tileName}/{meshBaseName}: LOD1={lod1Mesh.vertexCount}v LOD2={lod2Mesh.vertexCount}v (original={srcMesh.vertexCount}v)");

            // Export OBJ for web viewer
            if (_exportOBJ)
            {
                ExportMeshToOBJ(lod1Mesh, $"{lodFolder}/{meshBaseName}_LOD1.obj");
                ExportMeshToOBJ(lod2Mesh, $"{lodFolder}/{meshBaseName}_LOD2.obj");
            }

            // Replace MeshCollider with LOD2 mesh
            if (_replaceColliders)
            {
                ReplaceMeshColliders(tileFolder, tileName, srcMesh, lod2Mesh);
            }
        }

        // Set up LODGroup on the scene instance (if it exists in the scene)
        SetupLODGroupInScene(tileName, meshFilters, lodFolder);
    }

    // ── Vertex Clustering Decimation ────────────────────────────

    /// <summary>
    /// Decimate a mesh using Vertex Clustering.
    /// Divides the bounding box into a 3D grid, merges co-located vertices,
    /// and removes degenerate triangles.
    /// </summary>
    Mesh DecimateVertexClustering(Mesh src, float targetRatio)
    {
        Vector3[] srcVerts = src.vertices;
        Vector2[] srcUVs = src.uv;
        Vector3[] srcNormals = src.normals;
        int srcVertCount = srcVerts.Length;

        if (srcVertCount == 0) return Object.Instantiate(src);

        // Calculate grid resolution from target ratio
        // ratio = targetVerts / srcVerts ≈ (gridRes^3) / srcVerts ... but actually
        // we want fewer grid cells → more merging. Use cube root approximation.
        float targetVerts = srcVertCount * targetRatio;
        Bounds bounds = src.bounds;
        Vector3 bSize = bounds.size;
        float volume = Mathf.Max(bSize.x, 0.01f) * Mathf.Max(bSize.y, 0.01f) * Mathf.Max(bSize.z, 0.01f);

        // Cell size: larger cells → more decimation
        // Estimate: targetVerts ≈ volume / cellSize^3 (roughly)
        float cellSize = Mathf.Pow(volume / Mathf.Max(targetVerts, 1f), 1f / 3f);
        cellSize = Mathf.Max(cellSize, 0.001f);

        Vector3 bMin = bounds.min;
        int gx = Mathf.Max(1, Mathf.CeilToInt(bSize.x / cellSize));
        int gy = Mathf.Max(1, Mathf.CeilToInt(bSize.y / cellSize));
        int gz = Mathf.Max(1, Mathf.CeilToInt(bSize.z / cellSize));

        // Map each vertex to a grid cell
        int[] vertToCell = new int[srcVertCount];
        Dictionary<int, List<int>> cellVerts = new Dictionary<int, List<int>>();

        for (int i = 0; i < srcVertCount; i++)
        {
            Vector3 p = srcVerts[i];
            int cx = Mathf.Clamp(Mathf.FloorToInt((p.x - bMin.x) / cellSize), 0, gx - 1);
            int cy = Mathf.Clamp(Mathf.FloorToInt((p.y - bMin.y) / cellSize), 0, gy - 1);
            int cz = Mathf.Clamp(Mathf.FloorToInt((p.z - bMin.z) / cellSize), 0, gz - 1);
            int cellId = cx + cy * gx + cz * gx * gy;
            vertToCell[i] = cellId;

            if (!cellVerts.ContainsKey(cellId))
                cellVerts[cellId] = new List<int>();
            cellVerts[cellId].Add(i);
        }

        // Compute merged vertex for each cell (weighted average)
        Dictionary<int, int> cellToNewVert = new Dictionary<int, int>();
        List<Vector3> newVerts = new List<Vector3>();
        List<Vector2> newUVs = new List<Vector2>();
        List<Vector3> newNormals = new List<Vector3>();

        bool hasUV = srcUVs != null && srcUVs.Length == srcVertCount;
        bool hasNormals = srcNormals != null && srcNormals.Length == srcVertCount;

        foreach (var kvp in cellVerts)
        {
            int cellId = kvp.Key;
            List<int> verts = kvp.Value;
            int newIdx = newVerts.Count;
            cellToNewVert[cellId] = newIdx;

            // Average position
            Vector3 avgPos = Vector3.zero;
            Vector2 avgUV = Vector2.zero;
            Vector3 avgNorm = Vector3.zero;

            foreach (int vi in verts)
            {
                avgPos += srcVerts[vi];
                if (hasUV) avgUV += srcUVs[vi];
                if (hasNormals) avgNorm += srcNormals[vi];
            }

            float count = verts.Count;
            newVerts.Add(avgPos / count);
            newUVs.Add(hasUV ? avgUV / count : Vector2.zero);
            newNormals.Add(hasNormals ? (avgNorm / count).normalized : Vector3.up);
        }

        // Remap triangles per submesh, removing degenerate ones
        Mesh result = new Mesh();
        if (newVerts.Count > 65535)
            result.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;

        result.SetVertices(newVerts);
        if (hasUV) result.SetUVs(0, newUVs);
        if (hasNormals) result.SetNormals(newNormals);

        int subMeshCount = src.subMeshCount;
        result.subMeshCount = subMeshCount;

        for (int sub = 0; sub < subMeshCount; sub++)
        {
            int[] srcTris = src.GetTriangles(sub);
            List<int> newTris = new List<int>();

            for (int t = 0; t < srcTris.Length; t += 3)
            {
                int a = cellToNewVert[vertToCell[srcTris[t]]];
                int b = cellToNewVert[vertToCell[srcTris[t + 1]]];
                int c = cellToNewVert[vertToCell[srcTris[t + 2]]];

                // Skip degenerate triangles (two or more vertices merged to same cell)
                if (a == b || b == c || a == c) continue;

                newTris.Add(a);
                newTris.Add(b);
                newTris.Add(c);
            }

            result.SetTriangles(newTris.ToArray(), sub);
        }

        result.RecalculateBounds();
        if (!hasNormals)
            result.RecalculateNormals();

        return result;
    }

    // ── Asset Saving ──────────────────────────────────────────

    void SaveMeshAsset(Mesh mesh, string assetPath)
    {
        Mesh existing = AssetDatabase.LoadAssetAtPath<Mesh>(assetPath);
        if (existing != null)
        {
            EditorUtility.CopySerialized(mesh, existing);
        }
        else
        {
            AssetDatabase.CreateAsset(mesh, assetPath);
        }
    }

    // ── OBJ Export ──────────────────────────────────────────────

    void ExportMeshToOBJ(Mesh mesh, string assetPath)
    {
        // Convert asset path to full system path
        string fullPath = Path.Combine(
            Path.GetDirectoryName(Application.dataPath),
            assetPath);

        string dir = Path.GetDirectoryName(fullPath);
        if (!Directory.Exists(dir))
            Directory.CreateDirectory(dir);

        Vector3[] verts = mesh.vertices;
        Vector3[] normals = mesh.normals;
        Vector2[] uvs = mesh.uv;

        StringBuilder sb = new StringBuilder();
        sb.AppendLine($"# Vibe3D LOD Export - {mesh.name}");
        sb.AppendLine($"# Vertices: {verts.Length}");

        // Vertices
        for (int i = 0; i < verts.Length; i++)
        {
            sb.AppendLine($"v {verts[i].x:F6} {verts[i].y:F6} {verts[i].z:F6}");
        }

        // UVs
        if (uvs != null && uvs.Length > 0)
        {
            for (int i = 0; i < uvs.Length; i++)
            {
                sb.AppendLine($"vt {uvs[i].x:F6} {uvs[i].y:F6}");
            }
        }

        // Normals
        if (normals != null && normals.Length > 0)
        {
            for (int i = 0; i < normals.Length; i++)
            {
                sb.AppendLine($"vn {normals[i].x:F6} {normals[i].y:F6} {normals[i].z:F6}");
            }
        }

        // Faces (per submesh)
        bool hasUV = uvs != null && uvs.Length > 0;
        bool hasNorm = normals != null && normals.Length > 0;

        for (int sub = 0; sub < mesh.subMeshCount; sub++)
        {
            if (mesh.subMeshCount > 1)
                sb.AppendLine($"g submesh_{sub}");

            int[] tris = mesh.GetTriangles(sub);
            for (int t = 0; t < tris.Length; t += 3)
            {
                // OBJ indices are 1-based
                int a = tris[t] + 1;
                int b = tris[t + 1] + 1;
                int c = tris[t + 2] + 1;

                if (hasUV && hasNorm)
                    sb.AppendLine($"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}");
                else if (hasUV)
                    sb.AppendLine($"f {a}/{a} {b}/{b} {c}/{c}");
                else if (hasNorm)
                    sb.AppendLine($"f {a}//{a} {b}//{b} {c}//{c}");
                else
                    sb.AppendLine($"f {a} {b} {c}");
            }
        }

        File.WriteAllText(fullPath, sb.ToString());
    }

    // ── MeshCollider Replacement ────────────────────────────────

    void ReplaceMeshColliders(string tileFolder, string tileName, Mesh originalMesh, Mesh lod2Mesh)
    {
        // Find scene instances of this tile and replace their colliders
        GameObject[] allObjects = FindObjectsByType<GameObject>(FindObjectsSortMode.None);
        foreach (GameObject go in allObjects)
        {
            if (!go.name.Contains(tileName)) continue;

            MeshCollider mc = go.GetComponent<MeshCollider>();
            if (mc != null && mc.sharedMesh == originalMesh)
            {
                mc.sharedMesh = lod2Mesh;
                Debug.Log($"[CityTileLOD] Replaced collider on {go.name} with LOD2 mesh");
            }

            // Also check children
            foreach (MeshCollider childMC in go.GetComponentsInChildren<MeshCollider>())
            {
                if (childMC.sharedMesh == originalMesh)
                {
                    childMC.sharedMesh = lod2Mesh;
                }
            }
        }
    }

    // ── LODGroup Setup ──────────────────────────────────────────

    void SetupLODGroupInScene(string tileName, MeshFilter[] modelMeshFilters, string lodFolder)
    {
        // Find the scene instance for this tile
        GameObject[] allObjects = FindObjectsByType<GameObject>(FindObjectsSortMode.None);
        foreach (GameObject go in allObjects)
        {
            if (!go.name.Contains(tileName)) continue;

            MeshFilter mf = go.GetComponentInChildren<MeshFilter>();
            MeshRenderer mr = go.GetComponentInChildren<MeshRenderer>();
            if (mf == null || mr == null || mf.sharedMesh == null) continue;

            string meshBaseName = string.IsNullOrEmpty(mf.sharedMesh.name) ? tileName : mf.sharedMesh.name;

            // Load LOD meshes
            Mesh lod1 = AssetDatabase.LoadAssetAtPath<Mesh>($"{lodFolder}/{meshBaseName}_LOD1.asset");
            Mesh lod2 = AssetDatabase.LoadAssetAtPath<Mesh>($"{lodFolder}/{meshBaseName}_LOD2.asset");

            if (lod1 == null || lod2 == null) continue;

            // Remove existing LODGroup if any
            LODGroup existingLOD = go.GetComponent<LODGroup>();
            if (existingLOD != null)
                DestroyImmediate(existingLOD);

            // Create LOD child objects
            // LOD0: original (existing renderer)
            GameObject lod0Obj = mf.gameObject;

            // LOD1: create child with LOD1 mesh
            GameObject lod1Obj = CreateLODChild(go, $"{go.name}_LOD1", lod1, mr.sharedMaterials);
            lod1Obj.SetActive(false); // LODGroup manages visibility

            // LOD2: create child with LOD2 mesh
            GameObject lod2Obj = CreateLODChild(go, $"{go.name}_LOD2", lod2, mr.sharedMaterials);
            lod2Obj.SetActive(false);

            // Set up LODGroup
            LODGroup lodGroup = go.AddComponent<LODGroup>();
            LOD[] lods = new LOD[4];

            lods[0] = new LOD(LOD_LEVELS[0].screenHeight, new Renderer[] { lod0Obj.GetComponentInChildren<MeshRenderer>() });
            lods[1] = new LOD(LOD_LEVELS[1].screenHeight, new Renderer[] { lod1Obj.GetComponent<MeshRenderer>() });
            lods[2] = new LOD(LOD_LEVELS[2].screenHeight, new Renderer[] { lod2Obj.GetComponent<MeshRenderer>() });
            lods[3] = new LOD(LOD_LEVELS[3].screenHeight, new Renderer[0]); // Culled

            lodGroup.SetLODs(lods);
            lodGroup.RecalculateBounds();

            EditorUtility.SetDirty(go);
            Debug.Log($"[CityTileLOD] LODGroup set up on {go.name}");
            break; // Process first matching instance
        }
    }

    GameObject CreateLODChild(GameObject parent, string name, Mesh mesh, Material[] materials)
    {
        // Check if child already exists
        Transform existing = parent.transform.Find(name);
        if (existing != null)
            DestroyImmediate(existing.gameObject);

        GameObject child = new GameObject(name);
        child.transform.SetParent(parent.transform, false);

        MeshFilter mf = child.AddComponent<MeshFilter>();
        mf.sharedMesh = mesh;

        MeshRenderer mr = child.AddComponent<MeshRenderer>();
        mr.sharedMaterials = materials;

        return child;
    }
}
