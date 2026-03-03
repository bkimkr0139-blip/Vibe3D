using System.Collections.Generic;
using System.IO;
using UnityEngine;

/// <summary>
/// Distance-based tile streaming for CityTile photogrammetry.
/// Attach to the CityTiles_Root GameObject.
/// Enables/disables tiles based on camera distance with hysteresis to prevent flicker.
/// Supports edit-version awareness: loads edited tile meshes from tiles_edit/ when available.
/// </summary>
public class CityTileStreamer : MonoBehaviour
{
    [Header("Distance Thresholds")]
    [Tooltip("Tiles within this distance are activated")]
    public float enableDistance = 450f;

    [Tooltip("Tiles beyond this distance are deactivated (hysteresis gap prevents flicker)")]
    public float disableDistance = 550f;

    [Header("Performance")]
    [Tooltip("Maximum tile state changes per frame")]
    public int maxChangesPerFrame = 2;

    [Tooltip("Seconds between distance checks (0.1 = 10 checks/sec)")]
    public float checkInterval = 0.1f;

    [Header("Camera")]
    [Tooltip("Camera to measure distance from. If null, uses Camera.main")]
    public Camera targetCamera;

    [Header("Edit Versions")]
    [Tooltip("Path to active_versions.json relative to project data folder")]
    public string activeVersionsPath = "";

    [Tooltip("Root folder containing tiles_edit/ subfolders (relative to Assets/)")]
    public string tilesEditFolder = "CityTiles/tiles_edit";

    [Tooltip("Automatically reload active_versions.json when file changes")]
    public bool autoReloadVersions = true;

    [Header("Layer Separation")]
    [Tooltip("Parent transform for base (unedited) tiles. If null, uses this transform.")]
    public Transform baseLayerRoot;

    [Tooltip("Parent transform for edited tiles. If null, uses this transform.")]
    public Transform editLayerRoot;

    [Header("Debug")]
    [Tooltip("Show distance gizmos in Scene View")]
    public bool showGizmos = true;

    // Public status (for UI)
    public int ActiveTileCount { get; private set; }
    public int InactiveTileCount { get; private set; }
    public int EditedTileCount { get; private set; }

    private struct TileInfo
    {
        public Transform transform;
        public Vector3 center; // cached world-space center
        public bool isActive;
        public string tileId;
        public bool isEdited; // true if using edited version
        public int editVersion; // 0 = raw/unedited
    }

    private List<TileInfo> _tiles = new List<TileInfo>();
    private float _nextCheckTime;
    private int _roundRobinIdx; // for frame-budget cycling

    // Edit version tracking
    private Dictionary<string, int> _activeVersions = new Dictionary<string, int>();
    private float _versionsFileLastCheck;
    private float _versionsCheckInterval = 5f; // check file every 5 seconds
    private long _versionsFileLastWrite;

    void Start()
    {
        LoadActiveVersions();
        CollectTiles();
        if (targetCamera == null)
            targetCamera = Camera.main;
    }

    void OnEnable()
    {
        LoadActiveVersions();
        CollectTiles();
    }

    /// <summary>
    /// Loads active_versions.json to determine which tiles have edited versions.
    /// Format: {"tile_0012_0007": 3, "tile_0013_0008": 1}
    /// </summary>
    public void LoadActiveVersions()
    {
        _activeVersions.Clear();

        string path = ResolveVersionsPath();
        if (string.IsNullOrEmpty(path) || !File.Exists(path))
        {
            Debug.Log("[CityTileStreamer] No active_versions.json found, using raw tiles only");
            return;
        }

        try
        {
            string json = File.ReadAllText(path);
            // Simple JSON parsing without external dependencies
            // Format: {"tile_id": version_number, ...}
            json = json.Trim().TrimStart('{').TrimEnd('}');
            if (string.IsNullOrEmpty(json)) return;

            string[] pairs = json.Split(',');
            foreach (string pair in pairs)
            {
                string[] kv = pair.Split(':');
                if (kv.Length != 2) continue;

                string key = kv[0].Trim().Trim('"');
                string val = kv[1].Trim();

                if (int.TryParse(val, out int version) && version > 0)
                {
                    _activeVersions[key] = version;
                }
            }

            var fi = new FileInfo(path);
            _versionsFileLastWrite = fi.LastWriteTime.Ticks;

            Debug.Log($"[CityTileStreamer] Loaded {_activeVersions.Count} active edit versions");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"[CityTileStreamer] Failed to load active_versions.json: {e.Message}");
        }
    }

    string ResolveVersionsPath()
    {
        // Try explicit path first
        if (!string.IsNullOrEmpty(activeVersionsPath))
        {
            if (File.Exists(activeVersionsPath)) return activeVersionsPath;
            string combined = Path.Combine(Application.dataPath, activeVersionsPath);
            if (File.Exists(combined)) return combined;
        }

        // Try standard locations
        string[] candidates = {
            Path.Combine(Application.dataPath, tilesEditFolder, "active_versions.json"),
            Path.Combine(Application.dataPath, "CityTiles", "active_versions.json"),
            Path.Combine(Application.dataPath, "..", "tiles_edit", "active_versions.json"),
        };

        foreach (string c in candidates)
        {
            if (File.Exists(c)) return c;
        }

        return "";
    }

    /// <summary>
    /// Checks if a tile has an active edited version.
    /// </summary>
    public bool HasEditedVersion(string tileId)
    {
        return _activeVersions.ContainsKey(tileId) && _activeVersions[tileId] > 0;
    }

    /// <summary>
    /// Gets the active edit version for a tile, or 0 if using raw.
    /// </summary>
    public int GetEditVersion(string tileId)
    {
        return _activeVersions.TryGetValue(tileId, out int v) ? v : 0;
    }

    /// <summary>
    /// Scans direct children as tile objects from both base and edit layers.
    /// </summary>
    public void CollectTiles()
    {
        _tiles.Clear();

        // Collect from base layer root (or self if not set)
        CollectFromRoot(baseLayerRoot != null ? baseLayerRoot : transform, false);

        // Collect from edit layer root if separate
        if (editLayerRoot != null && editLayerRoot != baseLayerRoot && editLayerRoot != transform)
        {
            CollectFromRoot(editLayerRoot, true);
        }

        UpdateCounts();
        Debug.Log($"[CityTileStreamer] Collected {_tiles.Count} tiles ({EditedTileCount} edited)");
    }

    void CollectFromRoot(Transform root, bool forceEditFlag)
    {
        foreach (Transform child in root)
        {
            // Skip non-tile objects (lights, helpers)
            if (child.GetComponentInChildren<MeshRenderer>() == null &&
                child.GetComponentInChildren<MeshFilter>() == null)
                continue;

            // Calculate center from renderer bounds or transform position
            Vector3 center = child.position;
            Renderer rend = child.GetComponentInChildren<Renderer>();
            if (rend != null)
                center = rend.bounds.center;

            string tileId = child.name;
            bool isEdited = forceEditFlag || HasEditedVersion(tileId);
            int editVer = GetEditVersion(tileId);

            _tiles.Add(new TileInfo
            {
                transform = child,
                center = center,
                isActive = child.gameObject.activeSelf,
                tileId = tileId,
                isEdited = isEdited,
                editVersion = editVer,
            });
        }
    }

    void Update()
    {
        // Auto-reload active_versions.json when file changes
        if (autoReloadVersions && Time.time > _versionsFileLastCheck + _versionsCheckInterval)
        {
            _versionsFileLastCheck = Time.time;
            CheckVersionsFileChanged();
        }

        if (Time.time < _nextCheckTime) return;
        _nextCheckTime = Time.time + checkInterval;

        if (targetCamera == null)
        {
            targetCamera = Camera.main;
            if (targetCamera == null) return;
        }

        Vector3 camPos = targetCamera.transform.position;
        int changes = 0;
        int count = _tiles.Count;
        if (count == 0) return;

        // Round-robin: process tiles starting from where we left off last frame
        for (int i = 0; i < count && changes < maxChangesPerFrame; i++)
        {
            int idx = (_roundRobinIdx + i) % count;
            TileInfo tile = _tiles[idx];

            if (tile.transform == null) continue;

            float dist = Vector3.Distance(camPos, tile.center);

            if (tile.isActive && dist > disableDistance)
            {
                // Deactivate
                tile.transform.gameObject.SetActive(false);
                tile.isActive = false;
                _tiles[idx] = tile;
                changes++;
            }
            else if (!tile.isActive && dist < enableDistance)
            {
                // Activate
                tile.transform.gameObject.SetActive(true);
                tile.isActive = true;
                _tiles[idx] = tile;
                changes++;
            }
        }

        _roundRobinIdx = (_roundRobinIdx + maxChangesPerFrame) % Mathf.Max(1, count);

        if (changes > 0) UpdateCounts();
    }

    void CheckVersionsFileChanged()
    {
        string path = ResolveVersionsPath();
        if (string.IsNullOrEmpty(path) || !File.Exists(path)) return;

        try
        {
            var fi = new FileInfo(path);
            if (fi.LastWriteTime.Ticks != _versionsFileLastWrite)
            {
                Debug.Log("[CityTileStreamer] active_versions.json changed, reloading...");
                LoadActiveVersions();
                CollectTiles();
            }
        }
        catch { /* ignore file access errors during check */ }
    }

    void UpdateCounts()
    {
        int active = 0, inactive = 0, edited = 0;
        foreach (var tile in _tiles)
        {
            if (tile.isActive) active++;
            else inactive++;
            if (tile.isEdited) edited++;
        }
        ActiveTileCount = active;
        InactiveTileCount = inactive;
        EditedTileCount = edited;
    }

    /// <summary>
    /// Forces a specific tile to reload (e.g. after applying an edit).
    /// Call from editor scripts or runtime hotswap.
    /// </summary>
    public void RefreshTile(string tileId)
    {
        LoadActiveVersions();
        for (int i = 0; i < _tiles.Count; i++)
        {
            var tile = _tiles[i];
            if (tile.tileId == tileId)
            {
                tile.isEdited = HasEditedVersion(tileId);
                tile.editVersion = GetEditVersion(tileId);
                _tiles[i] = tile;
                Debug.Log($"[CityTileStreamer] Refreshed tile {tileId} (edited={tile.isEdited}, v{tile.editVersion})");
                break;
            }
        }
        UpdateCounts();
    }

    /// <summary>
    /// Returns info about all tiles and their edit status.
    /// </summary>
    public List<(string tileId, bool isEdited, int version, bool isActive)> GetTileStatus()
    {
        var result = new List<(string, bool, int, bool)>();
        foreach (var tile in _tiles)
        {
            result.Add((tile.tileId, tile.isEdited, tile.editVersion, tile.isActive));
        }
        return result;
    }

    // ── Gizmos ──────────────────────────────────────────────────

    void OnDrawGizmosSelected()
    {
        if (!showGizmos) return;

        Vector3 center = transform.position;

        // Green: enable zone
        Gizmos.color = new Color(0f, 1f, 0f, 0.08f);
        Gizmos.DrawWireSphere(center, enableDistance);

        // Yellow: hysteresis zone
        Gizmos.color = new Color(1f, 1f, 0f, 0.08f);
        Gizmos.DrawWireSphere(center, (enableDistance + disableDistance) / 2f);

        // Red: disable zone
        Gizmos.color = new Color(1f, 0f, 0f, 0.08f);
        Gizmos.DrawWireSphere(center, disableDistance);

        // Draw tile markers — orange for edited, green/red for active/inactive
        foreach (var tile in _tiles)
        {
            if (tile.transform == null) continue;
            if (tile.isEdited)
                Gizmos.color = tile.isActive ? new Color(1f, 0.65f, 0f) : new Color(0.6f, 0.4f, 0f); // orange
            else
                Gizmos.color = tile.isActive ? Color.green : Color.red;
            Gizmos.DrawWireCube(tile.center, Vector3.one * 5f);
        }
    }
}
