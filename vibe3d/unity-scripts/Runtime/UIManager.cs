// UIManager.cs — Section 2.2
// Central UI controller: tool mode toggle, search panel, property display.
// Manages interaction between all analysis tools.

using UnityEngine;
using System.Collections.Generic;

public class UIManager : MonoBehaviour
{
    public enum ToolMode { Select, Measure_Distance, Measure_Height, Measure_Area, NavPath, Visibility }

    [Header("Tool State")]
    public ToolMode currentMode = ToolMode.Select;

    [Header("References")]
    public BuildingIndexManager buildingIndex;
    public MeasurementManager measurement;
    public NavMeshPathfinder navPathfinder;
    public VisibilityAnalyzer visibility;
    public SelectionHighlightManager selection;

    [Header("UI Settings")]
    public KeyCode selectKey = KeyCode.Alpha1;
    public KeyCode distanceKey = KeyCode.Alpha2;
    public KeyCode heightKey = KeyCode.Alpha3;
    public KeyCode areaKey = KeyCode.Alpha4;
    public KeyCode navKey = KeyCode.Alpha5;
    public KeyCode visKey = KeyCode.Alpha6;
    public KeyCode escKey = KeyCode.Escape;

    [Header("Search")]
    public string searchQuery = "";

    private Camera _cam;

    void Start()
    {
        _cam = Camera.main;
        SetMode(ToolMode.Select);
    }

    void Update()
    {
        HandleHotkeys();
        HandleSelection();
    }

    void HandleHotkeys()
    {
        if (Input.GetKeyDown(selectKey)) SetMode(ToolMode.Select);
        else if (Input.GetKeyDown(distanceKey)) SetMode(ToolMode.Measure_Distance);
        else if (Input.GetKeyDown(heightKey)) SetMode(ToolMode.Measure_Height);
        else if (Input.GetKeyDown(areaKey)) SetMode(ToolMode.Measure_Area);
        else if (Input.GetKeyDown(navKey)) SetMode(ToolMode.NavPath);
        else if (Input.GetKeyDown(visKey)) SetMode(ToolMode.Visibility);
        else if (Input.GetKeyDown(escKey)) SetMode(ToolMode.Select);
    }

    void HandleSelection()
    {
        if (currentMode != ToolMode.Select) return;
        if (!Input.GetMouseButtonDown(0) || _cam == null) return;

        Ray ray = _cam.ScreenPointToRay(Input.mousePosition);
        if (Physics.Raycast(ray, out RaycastHit hit, 1000f))
        {
            if (buildingIndex != null)
            {
                var building = buildingIndex.FindBuildingFromRaycast(hit);
                if (building != null && selection != null)
                {
                    selection.SelectBuilding(building);
                    Debug.Log($"[UI] Selected: {building.building_id} ({building.height_max:F1}m)");
                }
            }
        }
    }

    public void SetMode(ToolMode mode)
    {
        currentMode = mode;

        // Deactivate all sub-tools
        if (measurement != null)
        {
            measurement.currentMode = mode switch
            {
                ToolMode.Measure_Distance => MeasurementManager.MeasureMode.Distance,
                ToolMode.Measure_Height => MeasurementManager.MeasureMode.Height,
                ToolMode.Measure_Area => MeasurementManager.MeasureMode.Area,
                _ => MeasurementManager.MeasureMode.None,
            };
        }

        if (navPathfinder != null)
        {
            if (mode == ToolMode.NavPath)
                navPathfinder.StartPathfinding();
            else if (mode != ToolMode.NavPath)
                navPathfinder.state = NavMeshPathfinder.NavState.Idle;
        }

        if (visibility != null && mode == ToolMode.Visibility)
        {
            visibility.StartAnalysis();
        }

        Debug.Log($"[UI] Mode: {mode}");
    }

    /// <summary>Search buildings by query string.</summary>
    public List<BuildingRecord> SearchBuildings(string query)
    {
        searchQuery = query;
        if (buildingIndex == null || string.IsNullOrEmpty(query))
            return new List<BuildingRecord>();

        var results = new List<BuildingRecord>();
        // Simple ID/tag search
        for (int i = 0; i < buildingIndex.BuildingCount; i++)
        {
            var b = buildingIndex.GetBuilding(query);
            if (b != null && !results.Contains(b))
                results.Add(b);
        }
        return results;
    }
}
