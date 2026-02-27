using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Distance-based tile streaming for CityTile photogrammetry.
/// Attach to the CityTiles_Root GameObject.
/// Enables/disables tiles based on camera distance with hysteresis to prevent flicker.
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

    [Header("Debug")]
    [Tooltip("Show distance gizmos in Scene View")]
    public bool showGizmos = true;

    // Public status (for UI)
    public int ActiveTileCount { get; private set; }
    public int InactiveTileCount { get; private set; }

    private struct TileInfo
    {
        public Transform transform;
        public Vector3 center; // cached world-space center
        public bool isActive;
    }

    private List<TileInfo> _tiles = new List<TileInfo>();
    private float _nextCheckTime;
    private int _roundRobinIdx; // for frame-budget cycling

    void Start()
    {
        CollectTiles();
        if (targetCamera == null)
            targetCamera = Camera.main;
    }

    void OnEnable()
    {
        CollectTiles();
    }

    /// <summary>
    /// Scans direct children as tile objects.
    /// </summary>
    public void CollectTiles()
    {
        _tiles.Clear();
        foreach (Transform child in transform)
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

            _tiles.Add(new TileInfo
            {
                transform = child,
                center = center,
                isActive = child.gameObject.activeSelf,
            });
        }

        UpdateCounts();
        Debug.Log($"[CityTileStreamer] Collected {_tiles.Count} tiles");
    }

    void Update()
    {
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

    void UpdateCounts()
    {
        int active = 0, inactive = 0;
        foreach (var tile in _tiles)
        {
            if (tile.isActive) active++;
            else inactive++;
        }
        ActiveTileCount = active;
        InactiveTileCount = inactive;
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

        // Draw tile markers
        foreach (var tile in _tiles)
        {
            if (tile.transform == null) continue;
            Gizmos.color = tile.isActive ? Color.green : Color.red;
            Gizmos.DrawWireCube(tile.center, Vector3.one * 5f);
        }
    }
}
