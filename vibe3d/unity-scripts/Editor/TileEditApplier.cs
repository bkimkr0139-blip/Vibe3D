// TileEditApplier.cs — Tile Mesh Edit Integration
// Editor Tool: Scans tiles_edit/ for new versions, applies FBX to LODGroup + MeshCollider.
// Menu: Vibe3D > Apply Tile Edits

using UnityEngine;
using UnityEditor;
using UnityEditor.AI;
using System.IO;
using System.Collections.Generic;

public class TileEditApplier : EditorWindow
{
    private string editFolder = "Assets/CityTiles/tiles_edit";
    private string tileRootFolder = "Assets/CityTiles";
    private bool swapLODs = true;
    private bool swapCollider = true;
    private bool setStaticFlags = true;
    private string colliderLayer = "TerrainCollider";
    private Vector2 scrollPos;
    private List<EditEntry> editEntries = new List<EditEntry>();

    private struct EditEntry
    {
        public string tileId;
        public int version;
        public string folderPath;
        public string[] lodFiles;
        public string colliderFile;
        public bool selected;
    }

    [MenuItem("Vibe3D/Apply Tile Edits")]
    public static void ShowWindow()
    {
        GetWindow<TileEditApplier>("Apply Tile Edits");
    }

    void OnGUI()
    {
        scrollPos = EditorGUILayout.BeginScrollView(scrollPos);

        GUILayout.Label("Tile Edit Applier", EditorStyles.boldLabel);
        EditorGUILayout.HelpBox(
            "Scans tiles_edit/ for versioned edit results (LOD FBX + Collider) " +
            "and applies them to scene GameObjects.",
            MessageType.Info);

        EditorGUILayout.Space();

        // Folder settings
        EditorGUILayout.LabelField("Folders", EditorStyles.miniLabel);
        editFolder = EditorGUILayout.TextField("Edit Folder", editFolder);
        tileRootFolder = EditorGUILayout.TextField("Tile Root", tileRootFolder);

        EditorGUILayout.Space();

        // Options
        swapLODs = EditorGUILayout.Toggle("Swap LOD Meshes", swapLODs);
        swapCollider = EditorGUILayout.Toggle("Swap MeshCollider", swapCollider);
        setStaticFlags = EditorGUILayout.Toggle("Set Static Flags", setStaticFlags);
        colliderLayer = EditorGUILayout.TextField("Collider Layer", colliderLayer);

        EditorGUILayout.Space();

        // Scan button
        if (GUILayout.Button("Scan for Edited Tiles", GUILayout.Height(30)))
        {
            ScanEditedTiles();
        }

        // Display entries
        if (editEntries.Count > 0)
        {
            EditorGUILayout.Space();
            EditorGUILayout.LabelField($"Found {editEntries.Count} edited tiles:", EditorStyles.boldLabel);

            for (int i = 0; i < editEntries.Count; i++)
            {
                var entry = editEntries[i];
                EditorGUILayout.BeginHorizontal();
                entry.selected = EditorGUILayout.Toggle(entry.selected, GUILayout.Width(20));
                EditorGUILayout.LabelField($"{entry.tileId} (v{entry.version})", GUILayout.Width(200));
                EditorGUILayout.LabelField($"LODs: {entry.lodFiles.Length}, Collider: {(string.IsNullOrEmpty(entry.colliderFile) ? "No" : "Yes")}");
                editEntries[i] = entry;
                EditorGUILayout.EndHorizontal();
            }

            EditorGUILayout.Space();

            if (GUILayout.Button("Apply Selected", GUILayout.Height(35)))
            {
                ApplySelected();
            }
        }

        EditorGUILayout.EndScrollView();
    }

    void ScanEditedTiles()
    {
        editEntries.Clear();
        string fullPath = Path.Combine(Application.dataPath, editFolder.Replace("Assets/", ""));

        if (!Directory.Exists(fullPath))
        {
            Debug.LogWarning($"[TileEditApplier] Edit folder not found: {fullPath}");
            return;
        }

        // Each subfolder = tile_id, each sub-subfolder = version
        foreach (string tileDir in Directory.GetDirectories(fullPath))
        {
            string tileId = Path.GetFileName(tileDir);
            int latestVersion = 0;
            string latestFolder = "";

            foreach (string verDir in Directory.GetDirectories(tileDir))
            {
                string verName = Path.GetFileName(verDir);
                if (verName.StartsWith("v") && int.TryParse(verName.Substring(1), out int ver))
                {
                    if (ver > latestVersion)
                    {
                        latestVersion = ver;
                        latestFolder = verDir;
                    }
                }
            }

            if (latestVersion == 0 || string.IsNullOrEmpty(latestFolder)) continue;

            // Find LOD and Collider files
            var lodFiles = new List<string>();
            string colliderFile = "";

            foreach (string file in Directory.GetFiles(latestFolder, "*.fbx"))
            {
                string name = Path.GetFileNameWithoutExtension(file);
                if (name.Contains("LOD"))
                    lodFiles.Add(file);
                else if (name.Contains("COLLIDER"))
                    colliderFile = file;
            }

            editEntries.Add(new EditEntry
            {
                tileId = tileId,
                version = latestVersion,
                folderPath = latestFolder,
                lodFiles = lodFiles.ToArray(),
                colliderFile = colliderFile,
                selected = true,
            });
        }

        Debug.Log($"[TileEditApplier] Found {editEntries.Count} edited tiles");
    }

    void ApplySelected()
    {
        int applied = 0;
        int errors = 0;

        foreach (var entry in editEntries)
        {
            if (!entry.selected) continue;

            try
            {
                ApplyEditedTile(entry);
                applied++;
            }
            catch (System.Exception e)
            {
                Debug.LogError($"[TileEditApplier] Failed to apply {entry.tileId}: {e.Message}");
                errors++;
            }
        }

        Debug.Log($"[TileEditApplier] Applied {applied} tiles, {errors} errors");

        // Refresh CityTileStreamer to pick up new edit versions
        if (applied > 0)
            RefreshStreamer();

        EditorUtility.DisplayDialog("Tile Edit Applier",
            $"Applied {applied} tiles.\nErrors: {errors}", "OK");
    }

    void ApplyEditedTile(EditEntry entry)
    {
        // Find existing tile GameObject in scene
        GameObject tileObj = FindTileInScene(entry.tileId);

        if (tileObj == null)
        {
            Debug.LogWarning($"[TileEditApplier] Tile {entry.tileId} not found in scene, creating new");
            tileObj = new GameObject(entry.tileId);
            tileObj.isStatic = setStaticFlags;
        }

        // Import FBX assets first
        ImportEditedAssets(entry);

        // Swap LOD meshes
        if (swapLODs && entry.lodFiles.Length > 0)
        {
            SwapLODGroup(tileObj, entry);
        }

        // Swap collider mesh
        if (swapCollider && !string.IsNullOrEmpty(entry.colliderFile))
        {
            SwapCollider(tileObj, entry);
        }

        // Set static flags
        if (setStaticFlags)
        {
            GameObjectUtility.SetStaticEditorFlags(tileObj,
                StaticEditorFlags.BatchingStatic |
                StaticEditorFlags.OcclusionStatic |
                StaticEditorFlags.OccludeeStatic |
                StaticEditorFlags.NavigationStatic);
        }

        EditorUtility.SetDirty(tileObj);
        Debug.Log($"[TileEditApplier] Applied {entry.tileId} v{entry.version}");
    }

    void ImportEditedAssets(EditEntry entry)
    {
        // Copy edited files to Assets folder for import
        string destFolder = Path.Combine(tileRootFolder, entry.tileId, $"v{entry.version}");
        string fullDest = Path.Combine(Application.dataPath, destFolder.Replace("Assets/", ""));
        Directory.CreateDirectory(fullDest);

        foreach (string lodFile in entry.lodFiles)
        {
            string destFile = Path.Combine(fullDest, Path.GetFileName(lodFile));
            if (!File.Exists(destFile))
                File.Copy(lodFile, destFile, true);
        }

        if (!string.IsNullOrEmpty(entry.colliderFile))
        {
            string destFile = Path.Combine(fullDest, Path.GetFileName(entry.colliderFile));
            if (!File.Exists(destFile))
                File.Copy(entry.colliderFile, destFile, true);
        }

        AssetDatabase.Refresh();
    }

    void SwapLODGroup(GameObject tileObj, EditEntry entry)
    {
        // Get or create LODGroup
        LODGroup lodGroup = tileObj.GetComponent<LODGroup>();
        if (lodGroup == null)
            lodGroup = tileObj.AddComponent<LODGroup>();

        // Remove existing LOD children
        for (int i = tileObj.transform.childCount - 1; i >= 0; i--)
        {
            var child = tileObj.transform.GetChild(i);
            if (child.name.Contains("LOD"))
                DestroyImmediate(child.gameObject);
        }

        // Create new LOD levels from imported FBX
        var lods = new List<LOD>();
        float[] transitions = { 0.6f, 0.3f, 0.1f }; // LOD transition distances

        System.Array.Sort(entry.lodFiles); // Ensure LOD0, LOD1, LOD2 order

        for (int i = 0; i < entry.lodFiles.Length; i++)
        {
            string assetPath = GetAssetPath(entry, entry.lodFiles[i]);
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);

            if (prefab == null)
            {
                Debug.LogWarning($"[TileEditApplier] Could not load LOD asset: {assetPath}");
                continue;
            }

            GameObject lodChild = Instantiate(prefab, tileObj.transform);
            lodChild.name = $"LOD{i}";
            lodChild.transform.localPosition = Vector3.zero;
            lodChild.transform.localRotation = Quaternion.identity;

            if (setStaticFlags)
                lodChild.isStatic = true;

            Renderer[] renderers = lodChild.GetComponentsInChildren<Renderer>();
            float threshold = i < transitions.Length ? transitions[i] : 0.01f;
            lods.Add(new LOD(threshold, renderers));
        }

        if (lods.Count > 0)
        {
            lodGroup.SetLODs(lods.ToArray());
            lodGroup.RecalculateBounds();
        }
    }

    void SwapCollider(GameObject tileObj, EditEntry entry)
    {
        // Get or create MeshCollider
        MeshCollider meshCol = tileObj.GetComponent<MeshCollider>();
        if (meshCol == null)
            meshCol = tileObj.AddComponent<MeshCollider>();

        // Load collider mesh from FBX
        string assetPath = GetAssetPath(entry, entry.colliderFile);
        Mesh colliderMesh = AssetDatabase.LoadAssetAtPath<Mesh>(assetPath);

        if (colliderMesh == null)
        {
            // Try loading from the FBX as a sub-asset
            GameObject fbxObj = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (fbxObj != null)
            {
                MeshFilter mf = fbxObj.GetComponentInChildren<MeshFilter>();
                if (mf != null) colliderMesh = mf.sharedMesh;
            }
        }

        if (colliderMesh != null)
        {
            meshCol.sharedMesh = colliderMesh;
            Debug.Log($"[TileEditApplier] Collider mesh set: {colliderMesh.triangles.Length / 3} tris");
        }
        else
        {
            Debug.LogWarning($"[TileEditApplier] Could not load collider mesh: {assetPath}");
        }

        // Set layer
        int layerIdx = LayerMask.NameToLayer(colliderLayer);
        if (layerIdx >= 0)
            tileObj.layer = layerIdx;
    }

    string GetAssetPath(EditEntry entry, string filePath)
    {
        string fileName = Path.GetFileName(filePath);
        return Path.Combine(tileRootFolder, entry.tileId, $"v{entry.version}", fileName)
            .Replace("\\", "/");
    }

    GameObject FindTileInScene(string tileId)
    {
        // Search by exact name first
        GameObject obj = GameObject.Find(tileId);
        if (obj != null) return obj;

        // Search by partial name match
        foreach (var go in FindObjectsByType<Transform>(FindObjectsSortMode.None))
        {
            if (go.name.Contains(tileId))
                return go.gameObject;
        }

        return null;
    }

    /// <summary>
    /// Notifies CityTileStreamer to refresh after tile edits are applied.
    /// </summary>
    void RefreshStreamer(string tileId = null)
    {
        var streamer = FindAnyObjectByType<CityTileStreamer>();
        if (streamer == null) return;

        if (!string.IsNullOrEmpty(tileId))
        {
            streamer.RefreshTile(tileId);
        }
        else
        {
            streamer.LoadActiveVersions();
            streamer.CollectTiles();
        }
        Debug.Log("[TileEditApplier] CityTileStreamer refreshed");
    }

    // ── NavMesh Rebuild ──────────────────────────────────────

    [MenuItem("Vibe3D/Rebuild NavMesh (Loaded Tiles)")]
    public static void RebuildNavMesh()
    {
        // Ensure all active tiles have NavigationStatic flag
        var streamer = FindAnyObjectByType<CityTileStreamer>();
        if (streamer != null)
        {
            var tileStatus = streamer.GetTileStatus();
            int marked = 0;
            foreach (var (tileId, isEdited, version, isActive) in tileStatus)
            {
                if (!isActive) continue;
                GameObject tileObj = GameObject.Find(tileId);
                if (tileObj == null) continue;

                // Set NavigationStatic on active tiles
                var flags = GameObjectUtility.GetStaticEditorFlags(tileObj);
                if ((flags & StaticEditorFlags.NavigationStatic) == 0)
                {
                    flags |= StaticEditorFlags.NavigationStatic;
                    GameObjectUtility.SetStaticEditorFlags(tileObj, flags);
                    marked++;
                }

                // Also set on children
                foreach (Transform child in tileObj.transform)
                {
                    var childFlags = GameObjectUtility.GetStaticEditorFlags(child.gameObject);
                    if ((childFlags & StaticEditorFlags.NavigationStatic) == 0)
                    {
                        childFlags |= StaticEditorFlags.NavigationStatic;
                        GameObjectUtility.SetStaticEditorFlags(child.gameObject, childFlags);
                    }
                }
            }

            if (marked > 0)
                Debug.Log($"[TileEditApplier] Marked {marked} tiles as NavigationStatic");
        }

        // Trigger NavMesh bake
        NavMeshBuilder.BuildNavMesh();
        Debug.Log("[TileEditApplier] NavMesh rebuild complete");
        EditorUtility.DisplayDialog("NavMesh Rebuild",
            "NavMesh has been rebuilt for all active tiles.", "OK");
    }

    // ── Layer Separation ──────────────────────────────────────

    [MenuItem("Vibe3D/Setup Edit Layer Hierarchy")]
    public static void SetupEditLayerHierarchy()
    {
        var streamer = FindAnyObjectByType<CityTileStreamer>();
        if (streamer == null)
        {
            EditorUtility.DisplayDialog("Error",
                "No CityTileStreamer found in scene.", "OK");
            return;
        }

        Transform root = streamer.transform;

        // Create BaseLayer and EditLayer under streamer root if not existing
        Transform baseLayer = root.Find("BaseLayer");
        if (baseLayer == null)
        {
            var go = new GameObject("BaseLayer");
            go.transform.SetParent(root);
            go.transform.localPosition = Vector3.zero;
            baseLayer = go.transform;
        }

        Transform editLayer = root.Find("EditLayer");
        if (editLayer == null)
        {
            var go = new GameObject("EditLayer");
            go.transform.SetParent(root);
            go.transform.localPosition = Vector3.zero;
            editLayer = go.transform;
        }

        // Move existing tiles to BaseLayer (skip BaseLayer/EditLayer themselves)
        var toMove = new List<Transform>();
        foreach (Transform child in root)
        {
            if (child == baseLayer || child == editLayer) continue;
            toMove.Add(child);
        }

        foreach (var child in toMove)
        {
            child.SetParent(baseLayer);
        }

        // Assign to streamer
        streamer.baseLayerRoot = baseLayer;
        streamer.editLayerRoot = editLayer;
        EditorUtility.SetDirty(streamer);

        Debug.Log($"[TileEditApplier] Layer hierarchy setup: {toMove.Count} tiles moved to BaseLayer");
        EditorUtility.DisplayDialog("Layer Hierarchy",
            $"Setup complete.\nBaseLayer: {toMove.Count} tiles\nEditLayer: ready for edited tiles", "OK");
    }
}
