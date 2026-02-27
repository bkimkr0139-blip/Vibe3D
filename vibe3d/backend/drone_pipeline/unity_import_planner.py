"""Unity Import & Scene Build planner for Drone2Twin pipeline.

Generates MCP action plans that automate:
  - Asset import settings (AssetPostprocessor)
  - LOD group generation
  - Collider proxy creation
  - Tiling + Addressables group setup
  - Streaming loader for runtime

Follows the same pattern as webgl_builder.py: C# scripts embedded as
Python strings, assembled into action plans for the MCP executor.
"""

import logging
from pathlib import Path
from typing import Optional

from .. import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# C# Scripts — embedded as Python strings
# ══════════════════════════════════════════════════════════════


ASSET_POSTPROCESSOR_CS = r'''using UnityEngine;
using UnityEditor;

/// <summary>
/// Vibe3D Drone2Twin — auto-configure 3D model import settings.
/// Runs automatically when GLB/FBX/OBJ assets are imported into Assets/DroneImport/.
/// </summary>
public class Vibe3DAssetPostprocessor : AssetPostprocessor
{
    void OnPreprocessModel()
    {
        // Only apply to DroneImport assets
        if (!assetPath.StartsWith("Assets/DroneImport/"))
            return;

        ModelImporter importer = assetImporter as ModelImporter;
        if (importer == null) return;

        // Scale: meters (1:1)
        importer.globalScale = 1f;
        importer.useFileUnits = true;

        // Normals & Tangents
        importer.importNormals = ModelImporterNormals.Calculate;
        importer.normalCalculationMode = ModelImporterNormalCalculationMode.AreaAndAngleWeighted;
        importer.importTangents = ModelImporterTangents.CalculateMikk;

        // Lightmap UV generation (for static backgrounds)
        importer.generateSecondaryUV = true;

        // Memory optimization: disable Read/Write unless needed for runtime mesh access
        importer.isReadable = false;

        // Mesh compression
        importer.meshCompression = ModelImporterMeshCompression.Medium;

        // Animation: disable if this is a static environment mesh
        importer.importAnimation = false;
        importer.animationType = ModelImporterAnimationType.None;

        Debug.Log($"[Vibe3D] Asset postprocessor applied to: {assetPath}");
    }

    void OnPreprocessTexture()
    {
        if (!assetPath.StartsWith("Assets/DroneImport/"))
            return;

        TextureImporter importer = assetImporter as TextureImporter;
        if (importer == null) return;

        // Max texture size: 2048 (balance quality/memory for WebGL)
        importer.maxTextureSize = 2048;

        // Compression: high quality for WebGL
        importer.textureCompression = TextureImporterCompression.CompressedHQ;

        // Generate mipmaps for distance rendering
        importer.mipmapEnabled = true;

        Debug.Log($"[Vibe3D] Texture postprocessor applied to: {assetPath}");
    }
}
'''


LOD_GENERATOR_CS = r'''using UnityEngine;
using UnityEditor;
using System.Linq;

/// <summary>
/// Vibe3D Drone2Twin — auto-generate LODGroup + collider proxies.
/// Menu: Vibe3D/GenerateLODs
/// </summary>
public class Vibe3DLODGenerator
{
    // LOD transition ratios (screen height percentage)
    const float LOD0_RATIO = 1.0f;    // 100% — full detail
    const float LOD1_RATIO = 0.35f;   // 35% — medium detail
    const float LOD2_RATIO = 0.10f;   // 10% — low detail
    const float CULL_RATIO = 0.01f;   // 1% — culled

    [MenuItem("Vibe3D/GenerateLODs")]
    public static void GenerateLODs()
    {
        // Find all imported DroneImport objects in scene
        var rootObjects = UnityEngine.SceneManagement.SceneManager
            .GetActiveScene().GetRootGameObjects();

        int lodCount = 0;
        int colliderCount = 0;

        foreach (var root in rootObjects)
        {
            // Process objects from DroneImport
            var renderers = root.GetComponentsInChildren<MeshRenderer>();
            foreach (var renderer in renderers)
            {
                var go = renderer.gameObject;

                // Skip if already has LODGroup
                if (go.GetComponent<LODGroup>() != null)
                    continue;

                var meshFilter = go.GetComponent<MeshFilter>();
                if (meshFilter == null || meshFilter.sharedMesh == null)
                    continue;

                // Create LODGroup with single LOD (mesh already has LOD level in name)
                // If mesh_lod0, mesh_lod1, mesh_lod2 exist as siblings, group them
                string baseName = go.name.Replace("_lod0", "").Replace("_lod1", "").Replace("_lod2", "");

                var siblings = go.transform.parent != null
                    ? Enumerable.Range(0, go.transform.parent.childCount)
                        .Select(i => go.transform.parent.GetChild(i).gameObject)
                        .Where(s => s.name.StartsWith(baseName) && s.name.Contains("lod"))
                        .OrderBy(s => s.name)
                        .ToArray()
                    : new GameObject[] { go };

                if (siblings.Length >= 2)
                {
                    // Create LODGroup on parent or first object
                    var lodGroup = siblings[0].AddComponent<LODGroup>();
                    var lods = new LOD[siblings.Length + 1]; // +1 for cull

                    float[] ratios = { LOD0_RATIO, LOD1_RATIO, LOD2_RATIO };
                    for (int i = 0; i < siblings.Length && i < 3; i++)
                    {
                        var r = siblings[i].GetComponent<Renderer>();
                        lods[i] = new LOD(ratios[i], r != null ? new Renderer[] { r } : new Renderer[0]);
                    }
                    // Cull LOD
                    lods[siblings.Length] = new LOD(CULL_RATIO, new Renderer[0]);

                    lodGroup.SetLODs(lods);
                    lodGroup.RecalculateBounds();
                    lodCount++;
                }

                // Add collider proxy (box collider instead of expensive MeshCollider)
                if (go.GetComponent<Collider>() == null)
                {
                    var bounds = renderer.bounds;
                    if (bounds.size.magnitude > 0.01f)
                    {
                        var box = go.AddComponent<BoxCollider>();
                        // BoxCollider auto-fits to mesh bounds
                        colliderCount++;
                    }
                }
            }
        }

        Debug.Log($"[Vibe3D] LOD generation complete: {lodCount} LODGroups, {colliderCount} colliders");
        EditorUtility.DisplayDialog("Vibe3D", $"LOD 생성 완료\n{lodCount} LODGroups\n{colliderCount} Colliders", "OK");
    }
}
'''


TILE_SETUP_CS = r'''using UnityEngine;
using UnityEditor;
using System.Collections.Generic;
using System.Linq;
#if UNITY_2019_1_OR_NEWER && ADDRESSABLES_AVAILABLE
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;
using UnityEditor.AddressableAssets.Settings.GroupSchemas;
#endif

/// <summary>
/// Vibe3D Drone2Twin — auto-setup tiling + Addressables groups.
/// Menu: Vibe3D/SetupTiles
/// </summary>
public class Vibe3DTileSetup
{
    [MenuItem("Vibe3D/SetupTiles")]
    public static void SetupTiles()
    {
        var rootObjects = UnityEngine.SceneManagement.SceneManager
            .GetActiveScene().GetRootGameObjects();

        // Group objects by zone (using naming convention or spatial partitioning)
        var zones = new Dictionary<string, List<GameObject>>();

        foreach (var root in rootObjects)
        {
            string zoneName = InferZone(root);
            if (!zones.ContainsKey(zoneName))
                zones[zoneName] = new List<GameObject>();
            zones[zoneName].Add(root);
        }

        int zoneCount = 0;

        foreach (var kvp in zones)
        {
            string zoneName = kvp.Key;
            var objects = kvp.Value;

            // Create zone container if it doesn't exist
            var zoneGO = GameObject.Find($"Zone_{zoneName}");
            if (zoneGO == null)
            {
                zoneGO = new GameObject($"Zone_{zoneName}");
                zoneGO.isStatic = true;
            }

            // Reparent objects into zone
            foreach (var obj in objects)
            {
                if (obj != zoneGO && obj.transform.parent == null)
                {
                    obj.transform.SetParent(zoneGO.transform);
                }
            }

            zoneCount++;
        }

        // Mark static for occlusion culling & lightmap baking
        foreach (var root in rootObjects)
        {
            SetStaticRecursive(root);
        }

#if UNITY_2019_1_OR_NEWER && ADDRESSABLES_AVAILABLE
        SetupAddressables(zones.Keys.ToArray());
#else
        Debug.LogWarning("[Vibe3D] Addressables package not found. Install com.unity.addressables for streaming support.");
#endif

        Debug.Log($"[Vibe3D] Tile setup complete: {zoneCount} zones");
        EditorUtility.DisplayDialog("Vibe3D", $"타일 설정 완료\n{zoneCount} zones", "OK");
    }

    static string InferZone(GameObject go)
    {
        string name = go.name.ToLower();

        // Try to detect zone from naming patterns
        if (name.Contains("floor") || name.Contains("ground"))
            return "Ground";
        if (name.Contains("roof") || name.Contains("ceiling"))
            return "Roof";
        if (name.Contains("pipe") || name.Contains("duct"))
            return "Piping";
        if (name.Contains("equipment") || name.Contains("vessel") || name.Contains("tank"))
            return "Equipment";
        if (name.Contains("structure") || name.Contains("frame") || name.Contains("column"))
            return "Structure";
        if (name.Contains("exterior") || name.Contains("wall"))
            return "Exterior";

        // Spatial: use grid position
        var pos = go.transform.position;
        int gx = Mathf.FloorToInt(pos.x / 50f);
        int gz = Mathf.FloorToInt(pos.z / 50f);
        return $"Grid_{gx}_{gz}";
    }

    static void SetStaticRecursive(GameObject go)
    {
        go.isStatic = true;
        for (int i = 0; i < go.transform.childCount; i++)
            SetStaticRecursive(go.transform.GetChild(i).gameObject);
    }

#if UNITY_2019_1_OR_NEWER && ADDRESSABLES_AVAILABLE
    static void SetupAddressables(string[] zoneNames)
    {
        var settings = AddressableAssetSettingsDefaultObject.Settings;
        if (settings == null)
        {
            settings = AddressableAssetSettingsDefaultObject.GetSettings(true);
        }

        foreach (string zone in zoneNames)
        {
            string groupName = $"Vibe3D_Zone_{zone}";
            var group = settings.FindGroup(groupName);
            if (group == null)
            {
                group = settings.CreateGroup(groupName, false, false, true,
                    null, typeof(BundledAssetGroupSchema));
            }

            // Add label
            settings.AddLabel($"Zone_{zone}");
        }

        Debug.Log($"[Vibe3D] Addressables: {zoneNames.Length} groups created");
    }
#endif
}
'''


STREAMING_LOADER_CS = r'''using UnityEngine;
using System.Collections.Generic;
#if ADDRESSABLES_AVAILABLE
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;
#endif

/// <summary>
/// Vibe3D Drone2Twin — runtime streaming loader.
/// Loads/unloads zone tiles based on camera distance.
/// Attach to the main camera or a dedicated manager object.
/// </summary>
public class Vibe3DStreamingLoader : MonoBehaviour
{
    [Header("Streaming Settings")]
    public float loadDistance = 100f;
    public float unloadDistance = 150f;
    public float checkInterval = 1f;

    private float _nextCheck;
    private Dictionary<string, bool> _loadedZones = new Dictionary<string, bool>();
    private Camera _mainCamera;

    void Start()
    {
        _mainCamera = Camera.main;
        if (_mainCamera == null)
            _mainCamera = FindObjectOfType<Camera>();
    }

    void Update()
    {
        if (Time.time < _nextCheck || _mainCamera == null)
            return;
        _nextCheck = Time.time + checkInterval;

        CheckZones();
    }

    void CheckZones()
    {
        var camPos = _mainCamera.transform.position;

        // Find all Zone_ root objects
        var rootObjects = UnityEngine.SceneManagement.SceneManager
            .GetActiveScene().GetRootGameObjects();

        foreach (var root in rootObjects)
        {
            if (!root.name.StartsWith("Zone_"))
                continue;

            float dist = Vector3.Distance(camPos, root.transform.position);

            if (dist < loadDistance)
            {
                if (!root.activeSelf)
                {
                    root.SetActive(true);
                    Debug.Log($"[Vibe3D Streaming] Loaded: {root.name}");
                }
            }
            else if (dist > unloadDistance)
            {
                if (root.activeSelf)
                {
                    root.SetActive(false);
                    Debug.Log($"[Vibe3D Streaming] Unloaded: {root.name}");
                }
            }
        }
    }
}
'''


CITYTILE_POSTPROCESSOR_CS = r'''using UnityEngine;
using UnityEditor;

/// <summary>
/// Vibe3D Drone2Twin — auto-configure OBJ city tile import settings.
/// Runs when OBJ assets are imported into Assets/CityTiles/.
/// </summary>
public class Vibe3DCityTilePostprocessor : AssetPostprocessor
{
    void OnPreprocessModel()
    {
        if (!assetPath.StartsWith("Assets/CityTiles/"))
            return;

        ModelImporter importer = assetImporter as ModelImporter;
        if (importer == null) return;

        // Scale: 1:1 meters, use file units (Skyline projects in meters)
        importer.globalScale = 1f;
        importer.useFileUnits = true;

        // Normals: calculate (OBJ may not have normals)
        importer.importNormals = ModelImporterNormals.Calculate;
        importer.normalCalculationMode = ModelImporterNormalCalculationMode.AreaAndAngleWeighted;

        // Mesh compression for large city tiles
        importer.meshCompression = ModelImporterMeshCompression.Medium;

        // No animation for static city tiles
        importer.importAnimation = false;
        importer.animationType = ModelImporterAnimationType.None;

        // Memory: not readable at runtime
        importer.isReadable = false;

        // Material: import via material description (auto MTL recognition)
        importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;

        Debug.Log($"[Vibe3D] CityTile postprocessor applied to: {assetPath}");
    }

    void OnPreprocessTexture()
    {
        if (!assetPath.StartsWith("Assets/CityTiles/"))
            return;

        TextureImporter importer = assetImporter as TextureImporter;
        if (importer == null) return;

        // City tiles: 4096 max for quality aerial textures
        importer.maxTextureSize = 4096;

        // High quality compression
        importer.textureCompression = TextureImporterCompression.CompressedHQ;

        // Mipmaps for distance rendering
        importer.mipmapEnabled = true;

        Debug.Log($"[Vibe3D] CityTile texture postprocessor applied to: {assetPath}");
    }
}
'''


# ══════════════════════════════════════════════════════════════
# Plan generators
# ══════════════════════════════════════════════════════════════


def generate_import_plan(
    glb_paths: list[str],
    *,
    tile_config: Optional[dict] = None,
    include_lod: bool = True,
    include_tiles: bool = True,
    include_streaming: bool = True,
) -> dict:
    """Generate MCP action plan for Unity import + LOD + tiling.

    Args:
        glb_paths: List of GLB/FBX file paths to import.
        tile_config: Optional tiling configuration override.
        include_lod: Whether to generate LODs.
        include_tiles: Whether to setup tiling + Addressables.
        include_streaming: Whether to add runtime streaming loader.

    Returns:
        Unity action plan dict compatible with Vibe3D executor.
    """
    actions: list[dict] = []

    # ── 1. AssetPostprocessor (auto-configure import settings) ──
    actions.append({
        "type": "create_script",
        "name": "Vibe3DAssetPostprocessor",
        "path": "Assets/Scripts/Editor/Vibe3DAssetPostprocessor.cs",
        "contents": ASSET_POSTPROCESSOR_CS,
    })

    # ── 2. LOD Generator script ──
    if include_lod:
        actions.append({
            "type": "create_script",
            "name": "Vibe3DLODGenerator",
            "path": "Assets/Scripts/Editor/Vibe3DLODGenerator.cs",
            "contents": LOD_GENERATOR_CS,
        })

    # ── 3. Tile Setup script ──
    if include_tiles:
        actions.append({
            "type": "create_script",
            "name": "Vibe3DTileSetup",
            "path": "Assets/Scripts/Editor/Vibe3DTileSetup.cs",
            "contents": TILE_SETUP_CS,
        })

    # ── 4. Streaming Loader (runtime) ──
    if include_streaming:
        actions.append({
            "type": "create_script",
            "name": "Vibe3DStreamingLoader",
            "path": "Assets/Scripts/Vibe3DStreamingLoader.cs",
            "contents": STREAMING_LOADER_CS,
        })

    # ── 5. Refresh assets (compile all scripts) ──
    actions.append({
        "type": "refresh_assets",
        "scope": "all",
        "compile": "request",
    })

    # ── 6. Import each GLB/FBX file ──
    for glb in glb_paths:
        name = Path(glb).stem
        ext = Path(glb).suffix
        actions.append({
            "type": "import_asset",
            "source_path": glb,
            "target_path": f"Assets/DroneImport/{name}{ext}",
        })

    # ── 7. Refresh after import ──
    if glb_paths:
        actions.append({
            "type": "refresh_assets",
            "scope": "all",
            "compile": "request",
        })

    # ── 8. Generate LODs ──
    if include_lod:
        actions.append({
            "type": "execute_menu",
            "menu_path": "Vibe3D/GenerateLODs",
        })

    # ── 9. Setup tiles + Addressables ──
    if include_tiles:
        actions.append({
            "type": "execute_menu",
            "menu_path": "Vibe3D/SetupTiles",
        })

    # ── 10. Save scene ──
    actions.append({
        "type": "save_scene",
    })

    # Build summary
    parts = []
    parts.append(f"GLB {len(glb_paths)}개 Import")
    if include_lod:
        parts.append("LOD 자동 생성")
    if include_tiles:
        parts.append("타일링/Addressables 설정")
    if include_streaming:
        parts.append("스트리밍 로더 설치")
    summary = " + ".join(parts)

    return {
        "project": "My project",
        "scene": config.DEFAULT_SCENE,
        "description": f"Drone2Twin Unity Import: {summary}",
        "confirmation_message": (
            f"{summary}을 실행합니다.\n"
            f"대상 파일: {', '.join(Path(p).name for p in glb_paths[:5])}"
            + (f" 외 {len(glb_paths) - 5}개" if len(glb_paths) > 5 else "")
            + f"\n(총 {len(actions)}개 작업)"
        ),
        "actions": actions,
    }


def generate_setup_only_plan(
    *,
    include_lod: bool = True,
    include_tiles: bool = True,
    include_streaming: bool = True,
) -> dict:
    """Generate plan that only installs editor scripts (no import)."""
    return generate_import_plan(
        [],
        include_lod=include_lod,
        include_tiles=include_tiles,
        include_streaming=include_streaming,
    )


def generate_obj_tile_import_plan(
    tile_info: dict,
    *,
    is_first_tile: bool = False,
) -> dict:
    """Generate MCP action plan for importing a single OBJ city tile.

    Args:
        tile_info: OBJTileInfo dict with obj_path, mtl_path, texture_paths.
        is_first_tile: If True, also creates the CityTile postprocessor script.

    Returns:
        Unity action plan dict compatible with Vibe3D executor.
    """
    actions: list[dict] = []
    tile_name = tile_info.get("name", "UnknownTile")
    target_folder = f"Assets/CityTiles/{tile_name}"

    # First tile: install postprocessor script + compile
    if is_first_tile:
        actions.append({
            "type": "create_script",
            "name": "Vibe3DCityTilePostprocessor",
            "path": "Assets/Scripts/Editor/Vibe3DCityTilePostprocessor.cs",
            "contents": CITYTILE_POSTPROCESSOR_CS,
        })
        actions.append({
            "type": "refresh_assets",
            "scope": "all",
            "compile": "request",
        })

    # Import OBJ file
    obj_path = tile_info.get("obj_path", "")
    if obj_path:
        obj_name = Path(obj_path).name
        actions.append({
            "type": "import_asset",
            "source_path": obj_path,
            "target_path": f"{target_folder}/{obj_name}",
        })

    # Import MTL file (same folder so Unity can auto-link)
    mtl_path = tile_info.get("mtl_path", "")
    if mtl_path:
        mtl_name = Path(mtl_path).name
        actions.append({
            "type": "import_asset",
            "source_path": mtl_path,
            "target_path": f"{target_folder}/{mtl_name}",
        })

    # Import texture files
    for tex_path in tile_info.get("texture_paths", []):
        tex_name = Path(tex_path).name
        actions.append({
            "type": "import_asset",
            "source_path": tex_path,
            "target_path": f"{target_folder}/{tex_name}",
        })

    # Refresh after import
    actions.append({
        "type": "refresh_assets",
        "scope": "assets",
        "mode": "force",
    })

    return {
        "project": "My project",
        "scene": config.DEFAULT_SCENE,
        "description": f"CityTile Import: {tile_name}",
        "confirmation_message": (
            f"OBJ 타일 '{tile_name}' 임포트\n"
            f"({tile_info.get('size_mb', 0):.1f} MB, "
            f"{len(tile_info.get('texture_paths', []))} textures)"
        ),
        "actions": actions,
    }
