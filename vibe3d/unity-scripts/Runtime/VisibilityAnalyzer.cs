// VisibilityAnalyzer.cs — Section 4.8
// Sensor-based visibility / blind-spot analysis using Physics.Raycast.
// Supports multi-sensor, FOV-limited, and full-surround modes.
// Results are displayed as a color-coded ground grid.

using UnityEngine;
using System.Collections;
using System.Collections.Generic;

public class VisibilityAnalyzer : MonoBehaviour
{
    [Header("Sensor Parameters")]
    public List<SensorConfig> sensors = new();

    [Header("Analysis Grid")]
    public float gridResolution = 2f;
    public float analysisRadius = 100f;
    public LayerMask obstacleLayers = ~0;

    [Header("Visualization")]
    public Color visibleColor = new(0f, 0.8f, 0f, 0.3f);
    public Color blindColor = new(1f, 0f, 0f, 0.25f);
    public float cellYOffset = 0.15f;

    [Header("Performance")]
    [Tooltip("Rays per frame (higher = faster but more CPU)")]
    public int raysPerFrame = 500;

    private readonly List<GameObject> _visObjects = new();
    private bool _isRunning;

    public float CoverageRatio { get; private set; }
    public int VisibleCells { get; private set; }
    public int TotalCells { get; private set; }

    /// <summary>Start visibility analysis as a coroutine.</summary>
    public void StartAnalysis()
    {
        if (_isRunning)
        {
            Debug.LogWarning("[Visibility] Already running");
            return;
        }
        ClearVisualization();
        StartCoroutine(AnalyzeCoroutine());
    }

    private IEnumerator AnalyzeCoroutine()
    {
        _isRunning = true;

        if (sensors.Count == 0)
        {
            Debug.LogWarning("[Visibility] No sensors configured");
            _isRunning = false;
            yield break;
        }

        // Determine grid bounds from sensors
        float minX = float.MaxValue, minZ = float.MaxValue;
        float maxX = float.MinValue, maxZ = float.MinValue;
        foreach (var s in sensors)
        {
            Vector3 pos = s.worldPosition;
            float r = s.maxDistance;
            if (pos.x - r < minX) minX = pos.x - r;
            if (pos.z - r < minZ) minZ = pos.z - r;
            if (pos.x + r > maxX) maxX = pos.x + r;
            if (pos.z + r > maxZ) maxZ = pos.z + r;
        }

        int nx = Mathf.CeilToInt((maxX - minX) / gridResolution);
        int nz = Mathf.CeilToInt((maxZ - minZ) / gridResolution);
        TotalCells = nx * nz;
        VisibleCells = 0;

        Debug.Log($"[Visibility] Analyzing {TotalCells} cells ({nx}x{nz})...");

        int rayCount = 0;

        for (int gx = 0; gx < nx; gx++)
        {
            for (int gz = 0; gz < nz; gz++)
            {
                float wx = minX + gx * gridResolution + gridResolution * 0.5f;
                float wz = minZ + gz * gridResolution + gridResolution * 0.5f;
                Vector3 cellCenter = new(wx, cellYOffset, wz);

                bool isVisible = false;

                foreach (var sensor in sensors)
                {
                    Vector3 sensorPos = sensor.worldPosition;
                    sensorPos.y += sensor.height;

                    Vector3 toCell = cellCenter - sensorPos;
                    float dist = toCell.magnitude;

                    if (dist > sensor.maxDistance) continue;

                    // FOV check (horizontal)
                    if (sensor.hFOV < 360f)
                    {
                        float angle = Mathf.Atan2(toCell.z, toCell.x) * Mathf.Rad2Deg;
                        float diff = Mathf.DeltaAngle(angle, sensor.yaw);
                        if (Mathf.Abs(diff) > sensor.hFOV * 0.5f) continue;
                    }

                    // Raycast for occlusion
                    Vector3 dir = toCell.normalized;
                    if (!Physics.Raycast(sensorPos, dir, dist - 0.1f, obstacleLayers))
                    {
                        isVisible = true;
                        break;
                    }

                    rayCount++;
                    if (rayCount >= raysPerFrame)
                    {
                        rayCount = 0;
                        yield return null; // frame budget
                    }
                }

                // Spawn cell visualization
                SpawnCell(cellCenter, isVisible);
                if (isVisible) VisibleCells++;
            }
        }

        CoverageRatio = TotalCells > 0 ? (float)VisibleCells / TotalCells : 0f;
        _isRunning = false;

        Debug.Log($"[Visibility] Complete: coverage={CoverageRatio:P1}, " +
                  $"visible={VisibleCells}/{TotalCells}");
    }

    private void SpawnCell(Vector3 center, bool visible)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Quad);
        go.name = "__vis_cell";
        go.transform.position = center;
        go.transform.rotation = Quaternion.Euler(90, 0, 0); // face up
        go.transform.localScale = new Vector3(gridResolution * 0.9f, gridResolution * 0.9f, 1f);

        var mat = new Material(Shader.Find("Sprites/Default"));
        mat.color = visible ? visibleColor : blindColor;
        go.GetComponent<Renderer>().material = mat;
        Destroy(go.GetComponent<Collider>());

        _visObjects.Add(go);
    }

    public void ClearVisualization()
    {
        foreach (var go in _visObjects) if (go) Destroy(go);
        _visObjects.Clear();
        VisibleCells = 0;
        TotalCells = 0;
        CoverageRatio = 0;
    }

    /// <summary>Add a sensor at a world position.</summary>
    public void AddSensor(Vector3 position, float hFOV = 360f, float maxDist = 100f, float yaw = 0f)
    {
        sensors.Add(new SensorConfig
        {
            worldPosition = position,
            height = 3f,
            hFOV = hFOV,
            vFOV = 60f,
            yaw = yaw,
            maxDistance = maxDist,
        });
    }
}

[System.Serializable]
public class SensorConfig
{
    public Vector3 worldPosition;
    public float height = 3f;
    public float yaw = 0f;        // degrees, 0 = east (+X)
    public float pitch = 0f;      // degrees
    public float hFOV = 90f;      // horizontal FOV degrees
    public float vFOV = 60f;      // vertical FOV degrees
    public float maxDistance = 100f;
}
