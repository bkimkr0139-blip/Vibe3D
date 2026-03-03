// SelectionHighlightManager.cs — Section 4.5
// Building selection highlight: footprint outline + BBox wireframe + property panel.

using UnityEngine;
using System.Collections.Generic;

public class SelectionHighlightManager : MonoBehaviour
{
    [Header("Highlight Colors")]
    public Color footprintColor = new(1f, 0.75f, 0.27f, 0.9f);
    public Color bboxColor = new(1f, 0.75f, 0.27f, 0.6f);
    public Color heightLabelColor = new(1f, 0.9f, 0.5f);

    [Header("Settings")]
    public float footprintYOffset = 0.3f;
    public float lineWidth = 0.05f;

    private BuildingRecord _selectedBuilding;
    private readonly List<GameObject> _highlights = new();

    public BuildingRecord SelectedBuilding => _selectedBuilding;
    public bool HasSelection => _selectedBuilding != null;

    /// <summary>Select and highlight a building.</summary>
    public void SelectBuilding(BuildingRecord building)
    {
        ClearHighlights();
        _selectedBuilding = building;
        if (building == null) return;

        DrawFootprintOutline(building);
        DrawBBoxWireframe(building);
        DrawHeightLabel(building);
    }

    /// <summary>Clear all highlights.</summary>
    public void ClearHighlights()
    {
        foreach (var go in _highlights) if (go) Destroy(go);
        _highlights.Clear();
        _selectedBuilding = null;
    }

    private void DrawFootprintOutline(BuildingRecord b)
    {
        if (b.footprint == null || b.footprint.Length < 3) return;

        var lineGO = new GameObject("__sel_footprint");
        var lr = lineGO.AddComponent<LineRenderer>();

        Vector3[] points = new Vector3[b.footprint.Length + 1];
        for (int i = 0; i < b.footprint.Length; i++)
        {
            points[i] = new Vector3(b.footprint[i][0], footprintYOffset, b.footprint[i][1]);
        }
        points[b.footprint.Length] = points[0]; // close loop

        lr.positionCount = points.Length;
        lr.SetPositions(points);
        lr.startWidth = lr.endWidth = lineWidth;
        lr.material = new Material(Shader.Find("Sprites/Default")) { color = footprintColor };
        lr.startColor = lr.endColor = footprintColor;
        lr.loop = false;

        _highlights.Add(lineGO);
    }

    private void DrawBBoxWireframe(BuildingRecord b)
    {
        if (b.centroid == null || b.centroid.Length < 3) return;

        // Use AABB from height/footprint
        float halfW = Mathf.Sqrt(b.area_2d) * 0.5f;  // approximate
        float halfH = (b.height_max - b.height_min) * 0.5f;

        Vector3 center = new(b.centroid[0], (b.height_min + b.height_max) * 0.5f, b.centroid[2]);
        Vector3 size = new(halfW * 2, halfH * 2, halfW * 2);

        var cubeGO = new GameObject("__sel_bbox");
        var mf = cubeGO.AddComponent<MeshFilter>();
        var mr = cubeGO.AddComponent<MeshRenderer>();

        mf.mesh = CreateWireframeCubeMesh();
        mr.material = new Material(Shader.Find("Sprites/Default"))
        {
            color = bboxColor
        };
        mr.material.SetFloat("_Mode", 3); // Transparent

        cubeGO.transform.position = center;
        cubeGO.transform.localScale = size;

        _highlights.Add(cubeGO);
    }

    private void DrawHeightLabel(BuildingRecord b)
    {
        var labelGO = new GameObject("__sel_height_label");
        labelGO.transform.position = new Vector3(
            b.centroid[0], b.height_max + 1f, b.centroid[2]
        );

        var tm = labelGO.AddComponent<TextMesh>();
        tm.text = $"{b.building_id}\n{b.height_max:F1}m | {b.area_2d:F0}m²";
        tm.fontSize = 28;
        tm.characterSize = 0.15f;
        tm.alignment = TextAlignment.Center;
        tm.anchor = TextAnchor.LowerCenter;
        tm.color = heightLabelColor;

        // Billboard: always face camera
        var billboard = labelGO.AddComponent<BillboardLabel>();

        _highlights.Add(labelGO);
    }

    private static Mesh CreateWireframeCubeMesh()
    {
        // Simple cube mesh used for wireframe rendering
        var mesh = new Mesh();
        float s = 0.5f;
        mesh.vertices = new[]
        {
            new Vector3(-s, -s, -s), new Vector3(s, -s, -s),
            new Vector3(s, s, -s), new Vector3(-s, s, -s),
            new Vector3(-s, -s, s), new Vector3(s, -s, s),
            new Vector3(s, s, s), new Vector3(-s, s, s),
        };
        mesh.SetIndices(new[]
        {
            0,1, 1,2, 2,3, 3,0,  // front
            4,5, 5,6, 6,7, 7,4,  // back
            0,4, 1,5, 2,6, 3,7,  // sides
        }, MeshTopology.Lines, 0);
        return mesh;
    }
}

/// <summary>Simple billboard component — always faces main camera.</summary>
public class BillboardLabel : MonoBehaviour
{
    private Camera _cam;

    void Start() => _cam = Camera.main;

    void LateUpdate()
    {
        if (_cam == null) return;
        transform.rotation = Quaternion.LookRotation(
            transform.position - _cam.transform.position
        );
    }
}
