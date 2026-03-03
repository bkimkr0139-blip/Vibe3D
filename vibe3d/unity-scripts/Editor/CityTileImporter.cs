// CityTileImporter.cs — Section 4.1
// Editor Tool: Auto-import/placement of city tiles.
// Scans folder → tile_id parsing → world coordinate placement →
// LODGroup creation → Collider proxy linking → Static flags → BuildingIndex loading.

using UnityEngine;
using UnityEditor;
using System.IO;
using System.Text.RegularExpressions;
using System.Collections.Generic;

public class CityTileImporter : EditorWindow
{
    private string tileFolder = "Assets/CityTiles";
    private string colliderFolder = "Assets/CityTiles/Colliders";
    private string buildingIndexPath = "";
    private float gridSpacing = 0f; // 0 = auto from mesh bounds
    private float gridOffsetX = 0f;
    private float gridOffsetZ = 0f;
    private bool importColliders = true;
    private bool setStaticFlags = true;
    private bool createLODGroups = true;
    private string physicsLayer = "TerrainCollider";
    private Vector2 scrollPos;

    [MenuItem("Vibe3D/City Tile Importer")]
    public static void ShowWindow()
    {
        GetWindow<CityTileImporter>("City Tile Importer");
    }

    void OnGUI()
    {
        scrollPos = EditorGUILayout.BeginScrollView(scrollPos);

        GUILayout.Label("City Tile Auto-Import (Section 4.1)", EditorStyles.boldLabel);
        EditorGUILayout.Space();

        // Folder settings
        EditorGUILayout.LabelField("Folders", EditorStyles.miniLabel);
        tileFolder = EditorGUILayout.TextField("Tile Folder", tileFolder);
        colliderFolder = EditorGUILayout.TextField("Collider Folder", colliderFolder);
        buildingIndexPath = EditorGUILayout.TextField("BuildingIndex Path", buildingIndexPath);

        EditorGUILayout.Space();

        // Grid settings
        EditorGUILayout.LabelField("Grid Placement", EditorStyles.miniLabel);
        gridSpacing = EditorGUILayout.FloatField("Grid Spacing (0=auto)", gridSpacing);
        gridOffsetX = EditorGUILayout.FloatField("Offset X", gridOffsetX);
        gridOffsetZ = EditorGUILayout.FloatField("Offset Z", gridOffsetZ);

        EditorGUILayout.Space();

        // Options
        importColliders = EditorGUILayout.Toggle("Import Collider Proxies", importColliders);
        setStaticFlags = EditorGUILayout.Toggle("Set Static Flags", setStaticFlags);
        createLODGroups = EditorGUILayout.Toggle("Create LODGroups", createLODGroups);
        physicsLayer = EditorGUILayout.TextField("Physics Layer", physicsLayer);

        EditorGUILayout.Space();

        // Actions
        if (GUILayout.Button("Scan & Preview", GUILayout.Height(30)))
        {
            ScanTiles();
        }

        if (GUILayout.Button("Import All Tiles", GUILayout.Height(35)))
        {
            ImportAllTiles();
        }

        EditorGUILayout.EndScrollView();
    }

    void ScanTiles()
    {
        string fullPath = Path.Combine(Application.dataPath, tileFolder.Replace("Assets/", ""));
        if (!Directory.Exists(fullPath))
        {
            Debug.LogWarning($"[TileImporter] Folder not found: {fullPath}");
            return;
        }

        var objFiles = Directory.GetFiles(fullPath, "*.obj", SearchOption.AllDirectories);
        var fbxFiles = Directory.GetFiles(fullPath, "*.fbx", SearchOption.AllDirectories);

        int count = objFiles.Length + fbxFiles.Length;
        Debug.Log($"[TileImporter] Scan result: {count} model files found " +
                  $"({objFiles.Length} OBJ, {fbxFiles.Length} FBX)");

        foreach (var f in objFiles)
        {
            var tileId = ParseTileId(Path.GetFileNameWithoutExtension(f));
            if (tileId != null)
                Debug.Log($"  Tile: {tileId.Value.x},{tileId.Value.y} — {Path.GetFileName(f)}");
        }
    }

    void ImportAllTiles()
    {
        string fullPath = Path.Combine(Application.dataPath, tileFolder.Replace("Assets/", ""));
        if (!Directory.Exists(fullPath))
        {
            EditorUtility.DisplayDialog("Error", $"Tile folder not found:\n{fullPath}", "OK");
            return;
        }

        var modelFiles = new List<string>();
        modelFiles.AddRange(Directory.GetFiles(fullPath, "*.obj", SearchOption.AllDirectories));
        modelFiles.AddRange(Directory.GetFiles(fullPath, "*.fbx", SearchOption.AllDirectories));

        if (modelFiles.Count == 0)
        {
            EditorUtility.DisplayDialog("Error", "No model files (OBJ/FBX) found.", "OK");
            return;
        }

        // Create root container
        GameObject root = new GameObject("CityTiles");

        int imported = 0;
        int skipped = 0;

        for (int i = 0; i < modelFiles.Count; i++)
        {
            string filePath = modelFiles[i];
            string fileName = Path.GetFileNameWithoutExtension(filePath);

            EditorUtility.DisplayProgressBar(
                "Importing Tiles",
                $"Processing {fileName}... ({i + 1}/{modelFiles.Count})",
                (float)i / modelFiles.Count
            );

            // Skip collider files
            if (fileName.Contains("_COLLIDER") || fileName.Contains("_collider"))
            {
                skipped++;
                continue;
            }

            // Skip LOD variants (will be handled as part of LODGroup)
            if (Regex.IsMatch(fileName, @"_LOD[12]$", RegexOptions.IgnoreCase))
            {
                continue;
            }

            // Parse tile ID
            Vector2Int? tileId = ParseTileId(fileName);

            // Get asset path relative to Assets
            string assetPath = "Assets" + filePath.Replace(Application.dataPath, "").Replace("\\", "/");

            // Load prefab from imported model
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (prefab == null)
            {
                Debug.LogWarning($"[TileImporter] Cannot load: {assetPath}");
                skipped++;
                continue;
            }

            // Instantiate
            GameObject tileGO = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            tileGO.name = fileName;
            tileGO.transform.SetParent(root.transform);

            // Position based on tile grid ID
            if (tileId != null && gridSpacing > 0)
            {
                tileGO.transform.position = new Vector3(
                    tileId.Value.x * gridSpacing + gridOffsetX,
                    0,
                    tileId.Value.y * gridSpacing + gridOffsetZ
                );
            }

            // LODGroup
            if (createLODGroups)
            {
                SetupLODGroup(tileGO, fileName, assetPath);
            }

            // Collider proxy
            if (importColliders)
            {
                AttachColliderProxy(tileGO, fileName);
            }

            // Static flags
            if (setStaticFlags)
            {
                SetStaticRecursive(tileGO, StaticEditorFlags.BatchingStatic |
                                            StaticEditorFlags.OccludeeStatic |
                                            StaticEditorFlags.OccluderStatic);
            }

            imported++;
        }

        EditorUtility.ClearProgressBar();

        // BuildingIndex
        if (!string.IsNullOrEmpty(buildingIndexPath))
        {
            var indexMgr = root.AddComponent<BuildingIndexManager>();
            indexMgr.jsonlPath = buildingIndexPath;
        }

        Undo.RegisterCreatedObjectUndo(root, "Import City Tiles");

        Debug.Log($"[TileImporter] Import complete: {imported} tiles imported, " +
                  $"{skipped} skipped");

        EditorUtility.DisplayDialog("Import Complete",
            $"Imported: {imported} tiles\nSkipped: {skipped}", "OK");
    }

    void SetupLODGroup(GameObject tileGO, string baseName, string baseAssetPath)
    {
        // Look for LOD1, LOD2 variants
        string dir = Path.GetDirectoryName(baseAssetPath);
        string ext = Path.GetExtension(baseAssetPath);

        string lod1Path = Path.Combine(dir, baseName + "_LOD1" + ext).Replace("\\", "/");
        string lod2Path = Path.Combine(dir, baseName + "_LOD2" + ext).Replace("\\", "/");

        GameObject lod1 = AssetDatabase.LoadAssetAtPath<GameObject>(lod1Path);
        GameObject lod2 = AssetDatabase.LoadAssetAtPath<GameObject>(lod2Path);

        if (lod1 == null && lod2 == null)
            return; // No LOD variants found

        LODGroup lodGroup = tileGO.AddComponent<LODGroup>();

        var lods = new List<LOD>();

        // LOD0 = current model (full detail)
        Renderer[] lod0Renderers = tileGO.GetComponentsInChildren<Renderer>();
        lods.Add(new LOD(0.5f, lod0Renderers));

        // LOD1
        if (lod1 != null)
        {
            GameObject lod1Inst = (GameObject)PrefabUtility.InstantiatePrefab(lod1);
            lod1Inst.name = baseName + "_LOD1";
            lod1Inst.transform.SetParent(tileGO.transform);
            lod1Inst.transform.localPosition = Vector3.zero;
            lods.Add(new LOD(0.2f, lod1Inst.GetComponentsInChildren<Renderer>()));
        }

        // LOD2
        if (lod2 != null)
        {
            GameObject lod2Inst = (GameObject)PrefabUtility.InstantiatePrefab(lod2);
            lod2Inst.name = baseName + "_LOD2";
            lod2Inst.transform.SetParent(tileGO.transform);
            lod2Inst.transform.localPosition = Vector3.zero;
            lods.Add(new LOD(0.05f, lod2Inst.GetComponentsInChildren<Renderer>()));
        }

        lodGroup.SetLODs(lods.ToArray());
        lodGroup.RecalculateBounds();
    }

    void AttachColliderProxy(GameObject tileGO, string baseName)
    {
        // Look for collider proxy file
        string colliderName = baseName + "_COLLIDER";
        string fullColliderPath = Path.Combine(Application.dataPath,
            colliderFolder.Replace("Assets/", ""));

        string[] extensions = { ".fbx", ".glb", ".obj" };
        string colliderAssetPath = null;

        foreach (var ext in extensions)
        {
            string testPath = Path.Combine(fullColliderPath, colliderName + ext);
            if (File.Exists(testPath))
            {
                colliderAssetPath = "Assets" + testPath.Replace(Application.dataPath, "")
                    .Replace("\\", "/");
                break;
            }
        }

        if (colliderAssetPath == null)
        {
            // Also check in the tile folder itself
            string tileFolderFull = Path.Combine(Application.dataPath,
                tileFolder.Replace("Assets/", ""));
            foreach (var ext in extensions)
            {
                string testPath = Path.Combine(tileFolderFull, colliderName + ext);
                if (File.Exists(testPath))
                {
                    colliderAssetPath = "Assets" + testPath.Replace(Application.dataPath, "")
                        .Replace("\\", "/");
                    break;
                }
            }
        }

        if (colliderAssetPath == null) return;

        // Create collider child object
        GameObject colliderPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(colliderAssetPath);
        if (colliderPrefab == null) return;

        GameObject colliderGO = new GameObject(baseName + "_Collider");
        colliderGO.transform.SetParent(tileGO.transform);
        colliderGO.transform.localPosition = Vector3.zero;

        // Add mesh collider from proxy mesh
        MeshFilter[] meshFilters = colliderPrefab.GetComponentsInChildren<MeshFilter>();
        foreach (var mf in meshFilters)
        {
            if (mf.sharedMesh == null) continue;
            MeshCollider mc = colliderGO.AddComponent<MeshCollider>();
            mc.sharedMesh = mf.sharedMesh;
        }

        // Set layer
        int layerIdx = LayerMask.NameToLayer(physicsLayer);
        if (layerIdx >= 0)
        {
            colliderGO.layer = layerIdx;
        }

        // Disable renderer (collider only)
        Renderer rend = colliderGO.GetComponent<Renderer>();
        if (rend != null) rend.enabled = false;

        // Static
        if (setStaticFlags)
        {
            GameObjectUtility.SetStaticEditorFlags(colliderGO,
                StaticEditorFlags.BatchingStatic | StaticEditorFlags.NavigationStatic);
        }
    }

    static void SetStaticRecursive(GameObject go, StaticEditorFlags flags)
    {
        GameObjectUtility.SetStaticEditorFlags(go, flags);
        foreach (Transform child in go.transform)
        {
            SetStaticRecursive(child.gameObject, flags);
        }
    }

    /// <summary>Parse tile_id (x,y) from filename like "tile_0001_0007" or "tile_1_7".</summary>
    static Vector2Int? ParseTileId(string filename)
    {
        // Match patterns: tile_XXXX_YYYY, tile_X_Y
        var match = Regex.Match(filename, @"tile[_-](\d+)[_-](\d+)", RegexOptions.IgnoreCase);
        if (match.Success)
        {
            int x = int.Parse(match.Groups[1].Value);
            int y = int.Parse(match.Groups[2].Value);
            return new Vector2Int(x, y);
        }
        return null;
    }
}
