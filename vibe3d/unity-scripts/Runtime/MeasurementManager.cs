// MeasurementManager.cs — Section 4.6
// Distance, height, and area measurement tools for Unity PC app.

using UnityEngine;
using System.Collections.Generic;

public class MeasurementManager : MonoBehaviour
{
    public enum MeasureMode { None, Distance, Height, Area }

    [Header("Settings")]
    public LayerMask raycastLayers = ~0;
    public float maxRayDistance = 1000f;
    public Color distanceColor = new(1f, 0.4f, 0f);
    public Color heightColor = new(0.2f, 0.6f, 1f);
    public Color areaColor = new(0f, 1f, 0.5f);

    [Header("State")]
    public MeasureMode currentMode = MeasureMode.None;

    private readonly List<Vector3> _points = new();
    private readonly List<MeasureResult> _results = new();
    private readonly List<GameObject> _markers = new();
    private Camera _cam;

    public int ResultCount => _results.Count;

    void Start()
    {
        _cam = Camera.main;
    }

    void Update()
    {
        if (currentMode == MeasureMode.None || _cam == null) return;

        if (Input.GetMouseButtonDown(0))
        {
            Ray ray = _cam.ScreenPointToRay(Input.mousePosition);
            if (Physics.Raycast(ray, out RaycastHit hit, maxRayDistance, raycastLayers))
            {
                AddPoint(hit.point);
            }
        }

        // Double-click to close area polygon
        if (currentMode == MeasureMode.Area && _points.Count >= 3)
        {
            if (Input.GetMouseButtonDown(1)) // right-click to close
            {
                CompleteArea();
            }
        }

        // Escape to cancel
        if (Input.GetKeyDown(KeyCode.Escape))
        {
            CancelMeasurement();
        }
    }

    public void SetMode(MeasureMode mode)
    {
        currentMode = mode;
        _points.Clear();
        ClearMarkers();
    }

    private void AddPoint(Vector3 point)
    {
        _points.Add(point);
        SpawnMarker(point, currentMode == MeasureMode.Area ? areaColor : distanceColor);

        switch (currentMode)
        {
            case MeasureMode.Distance when _points.Count == 2:
                CompleteDistance();
                break;
            case MeasureMode.Height when _points.Count == 1:
                CompleteHeight();
                break;
        }
    }

    private void CompleteDistance()
    {
        Vector3 a = _points[0], b = _points[1];
        float dist = Vector3.Distance(a, b);
        DrawLine(a, b, distanceColor);
        DrawLabel((a + b) * 0.5f + Vector3.up * 0.5f, $"{dist:F2}m");

        _results.Add(new MeasureResult
        {
            type = "distance",
            value = dist,
            unit = "m",
            points = new[] { a, b },
        });

        Debug.Log($"[Measure] Distance: {dist:F2}m");
        _points.Clear();
    }

    private void CompleteHeight()
    {
        Vector3 p = _points[0];
        // Raycast down to find ground
        Vector3 groundPoint = p;
        if (Physics.Raycast(p + Vector3.up * 0.1f, Vector3.down, out RaycastHit hit, 500f, raycastLayers))
        {
            groundPoint = hit.point;
        }
        else
        {
            groundPoint = new Vector3(p.x, 0, p.z);
        }

        float height = Mathf.Abs(p.y - groundPoint.y);
        DrawLine(groundPoint, p, heightColor);
        DrawLabel((groundPoint + p) * 0.5f + Vector3.right * 0.5f, $"{height:F2}m");

        _results.Add(new MeasureResult
        {
            type = "height",
            value = height,
            unit = "m",
            points = new[] { groundPoint, p },
        });

        Debug.Log($"[Measure] Height: {height:F2}m");
        _points.Clear();
    }

    private void CompleteArea()
    {
        // Shoelace formula on XZ plane
        float area = 0;
        int n = _points.Count;
        for (int i = 0; i < n; i++)
        {
            int j = (i + 1) % n;
            area += _points[i].x * _points[j].z;
            area -= _points[j].x * _points[i].z;
        }
        area = Mathf.Abs(area) / 2f;

        // Draw polygon outline
        for (int i = 0; i < n; i++)
        {
            DrawLine(_points[i], _points[(i + 1) % n], areaColor);
        }

        // Centroid label
        Vector3 centroid = Vector3.zero;
        foreach (var p in _points) centroid += p;
        centroid /= n;
        DrawLabel(centroid + Vector3.up * 1f, $"{area:F1}m²");

        _results.Add(new MeasureResult
        {
            type = "area",
            value = area,
            unit = "m²",
            points = _points.ToArray(),
        });

        Debug.Log($"[Measure] Area: {area:F1}m²");
        _points.Clear();
        currentMode = MeasureMode.None;
    }

    private void CancelMeasurement()
    {
        _points.Clear();
        ClearMarkers();
        currentMode = MeasureMode.None;
    }

    private void SpawnMarker(Vector3 pos, Color color)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        go.transform.position = pos;
        go.transform.localScale = Vector3.one * 0.3f;
        go.GetComponent<Renderer>().material.color = color;
        Destroy(go.GetComponent<Collider>());
        go.name = "__measure_marker";
        _markers.Add(go);
    }

    private void DrawLine(Vector3 a, Vector3 b, Color color)
    {
        var go = new GameObject("__measure_line");
        var lr = go.AddComponent<LineRenderer>();
        lr.positionCount = 2;
        lr.SetPositions(new[] { a, b });
        lr.startWidth = lr.endWidth = 0.05f;
        lr.material = new Material(Shader.Find("Sprites/Default")) { color = color };
        _markers.Add(go);
    }

    private void DrawLabel(Vector3 pos, string text)
    {
        // Simple 3D text using TextMesh (for in-editor visibility)
        var go = new GameObject("__measure_label");
        go.transform.position = pos;
        var tm = go.AddComponent<TextMesh>();
        tm.text = text;
        tm.fontSize = 32;
        tm.characterSize = 0.15f;
        tm.alignment = TextAlignment.Center;
        tm.anchor = TextAnchor.MiddleCenter;
        tm.color = Color.white;
        _markers.Add(go);
    }

    private void ClearMarkers()
    {
        foreach (var m in _markers) if (m) Destroy(m);
        _markers.Clear();
    }

    public void ClearAll()
    {
        ClearMarkers();
        _results.Clear();
        _points.Clear();
        currentMode = MeasureMode.None;
    }

    /// <summary>Export results as JSON string.</summary>
    public string ExportJson()
    {
        var wrapper = new MeasureResultList { measurements = _results.ToArray() };
        return JsonUtility.ToJson(wrapper, true);
    }
}

[System.Serializable]
public class MeasureResult
{
    public string type;
    public float value;
    public string unit;
    public Vector3[] points;
}

[System.Serializable]
public class MeasureResultList
{
    public MeasureResult[] measurements;
}
