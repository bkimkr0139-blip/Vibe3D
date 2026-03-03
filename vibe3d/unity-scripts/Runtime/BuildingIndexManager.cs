// BuildingIndexManager.cs — Section 4.4
// Loads GeoBIM building data (JSONL or SQLite) and provides
// spatial queries for raycast→building mapping.

using UnityEngine;
using System.Collections.Generic;
using System.IO;
using System.Linq;

public class BuildingIndexManager : MonoBehaviour
{
    [Header("Data Source")]
    [Tooltip("Path to buildings.jsonl file")]
    public string jsonlPath = "geobim_db/buildings.jsonl";

    [Header("Settings")]
    public float searchRadius = 20f;

    // All loaded buildings
    private readonly List<BuildingRecord> _buildings = new();
    // Grid-based spatial index: cell → list of building indices
    private readonly Dictionary<Vector2Int, List<int>> _gridIndex = new();
    private float _gridCellSize = 50f;

    public int BuildingCount => _buildings.Count;

    void Start()
    {
        LoadFromJsonl(jsonlPath);
    }

    public void LoadFromJsonl(string path)
    {
        _buildings.Clear();
        _gridIndex.Clear();

        if (!File.Exists(path))
        {
            Debug.LogWarning($"[BuildingIndex] File not found: {path}");
            return;
        }

        string[] lines = File.ReadAllLines(path);
        foreach (string line in lines)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var b = JsonUtility.FromJson<BuildingRecord>(line);
            if (b != null && !string.IsNullOrEmpty(b.building_id))
            {
                int idx = _buildings.Count;
                _buildings.Add(b);

                // Add to spatial index
                Vector2Int cell = WorldToCell(b.centroid[0], b.centroid[2]);
                if (!_gridIndex.ContainsKey(cell))
                    _gridIndex[cell] = new List<int>();
                _gridIndex[cell].Add(idx);
            }
        }

        Debug.Log($"[BuildingIndex] Loaded {_buildings.Count} buildings, " +
                  $"{_gridIndex.Count} grid cells");
    }

    /// <summary>Find the building at a world position (2D point-in-polygon test).</summary>
    public BuildingRecord FindBuildingAtPoint(float worldX, float worldZ)
    {
        Vector2Int cell = WorldToCell(worldX, worldZ);

        // Search 3x3 neighborhood
        for (int dx = -1; dx <= 1; dx++)
        {
            for (int dz = -1; dz <= 1; dz++)
            {
                Vector2Int c = new(cell.x + dx, cell.y + dz);
                if (!_gridIndex.TryGetValue(c, out var indices)) continue;

                foreach (int idx in indices)
                {
                    var b = _buildings[idx];
                    if (PointInFootprint(worldX, worldZ, b.footprint))
                        return b;
                }
            }
        }
        return null;
    }

    /// <summary>Find building from a Raycast hit point.</summary>
    public BuildingRecord FindBuildingFromRaycast(RaycastHit hit)
    {
        return FindBuildingAtPoint(hit.point.x, hit.point.z);
    }

    /// <summary>Find buildings within radius of a point.</summary>
    public List<BuildingRecord> FindBuildingsNear(float x, float z, float radius)
    {
        var result = new List<BuildingRecord>();
        float r2 = radius * radius;

        int cellRadius = Mathf.CeilToInt(radius / _gridCellSize) + 1;
        Vector2Int center = WorldToCell(x, z);

        for (int dx = -cellRadius; dx <= cellRadius; dx++)
        {
            for (int dz = -cellRadius; dz <= cellRadius; dz++)
            {
                Vector2Int c = new(center.x + dx, center.y + dz);
                if (!_gridIndex.TryGetValue(c, out var indices)) continue;

                foreach (int idx in indices)
                {
                    var b = _buildings[idx];
                    float ddx = b.centroid[0] - x;
                    float ddz = b.centroid[2] - z;
                    if (ddx * ddx + ddz * ddz <= r2)
                        result.Add(b);
                }
            }
        }
        return result;
    }

    /// <summary>Get building by ID.</summary>
    public BuildingRecord GetBuilding(string buildingId)
    {
        return _buildings.FirstOrDefault(b => b.building_id == buildingId);
    }

    private Vector2Int WorldToCell(float x, float z)
    {
        return new Vector2Int(
            Mathf.FloorToInt(x / _gridCellSize),
            Mathf.FloorToInt(z / _gridCellSize)
        );
    }

    private static bool PointInFootprint(float x, float z, float[][] footprint)
    {
        if (footprint == null || footprint.Length < 3) return false;

        bool inside = false;
        int n = footprint.Length;
        for (int i = 0, j = n - 1; i < n; j = i++)
        {
            float xi = footprint[i][0], zi = footprint[i][1];
            float xj = footprint[j][0], zj = footprint[j][1];
            if (((zi > z) != (zj > z)) &&
                (x < (xj - xi) * (z - zi) / (zj - zi) + xi))
                inside = !inside;
        }
        return inside;
    }
}

[System.Serializable]
public class BuildingRecord
{
    public string building_id;
    public string tile_id;
    public float[] centroid;     // [x, y, z]
    public float height_min;
    public float height_max;
    public float height_avg;
    public float area_2d;
    public float volume_approx;
    public float confidence;
    public float[][] footprint;  // [[x,z], ...]
    public string[] tags;
}
