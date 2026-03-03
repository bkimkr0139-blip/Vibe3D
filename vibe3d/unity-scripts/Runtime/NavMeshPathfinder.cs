// NavMeshPathfinder.cs — Section 4.7
// NavMesh-based pathfinding: start/end click → path display → agent simulation.
// Requires NavMeshSurface baked on ColliderProxy meshes.

using UnityEngine;
using UnityEngine.AI;
using System.Collections.Generic;

public class NavMeshPathfinder : MonoBehaviour
{
    public enum NavState { Idle, SetStart, SetEnd, Navigating }

    [Header("Settings")]
    public LayerMask clickLayers = ~0;
    public float agentSpeed = 3.5f;
    public float agentRadius = 0.5f;
    public Color pathColor = new(0f, 1f, 0.5f, 0.8f);
    public Color startColor = new(0.2f, 1f, 0.2f);
    public Color endColor = new(1f, 0.2f, 0.2f);

    [Header("State")]
    public NavState state = NavState.Idle;

    private Vector3 _startPoint;
    private Vector3 _endPoint;
    private NavMeshPath _path;
    private LineRenderer _pathLine;
    private readonly List<GameObject> _markers = new();
    private GameObject _agent;
    private int _agentPathIndex;
    private Camera _cam;

    public float PathDistance { get; private set; }

    void Start()
    {
        _cam = Camera.main;
        _path = new NavMeshPath();
    }

    void Update()
    {
        if (_cam == null) return;

        // Click handling
        if (state == NavState.SetStart || state == NavState.SetEnd)
        {
            if (Input.GetMouseButtonDown(0))
            {
                Ray ray = _cam.ScreenPointToRay(Input.mousePosition);
                if (Physics.Raycast(ray, out RaycastHit hit, 1000f, clickLayers))
                {
                    if (state == NavState.SetStart)
                    {
                        _startPoint = hit.point;
                        SpawnMarker(_startPoint, startColor, "NavStart");
                        state = NavState.SetEnd;
                        Debug.Log($"[NavMesh] Start: {_startPoint}");
                    }
                    else
                    {
                        _endPoint = hit.point;
                        SpawnMarker(_endPoint, endColor, "NavEnd");
                        CalculatePath();
                    }
                }
            }
        }

        // Agent movement
        if (state == NavState.Navigating && _agent != null && _path.corners.Length > 0)
        {
            if (_agentPathIndex < _path.corners.Length)
            {
                Vector3 target = _path.corners[_agentPathIndex];
                _agent.transform.position = Vector3.MoveTowards(
                    _agent.transform.position, target, agentSpeed * Time.deltaTime);
                _agent.transform.LookAt(target);

                if (Vector3.Distance(_agent.transform.position, target) < 0.1f)
                    _agentPathIndex++;
            }
            else
            {
                state = NavState.Idle;
                Debug.Log("[NavMesh] Agent reached destination");
            }
        }

        // Escape to cancel
        if (Input.GetKeyDown(KeyCode.Escape))
        {
            Reset();
        }
    }

    /// <summary>Start pathfinding mode.</summary>
    public void StartPathfinding()
    {
        Reset();
        state = NavState.SetStart;
        Debug.Log("[NavMesh] Click start point");
    }

    private void CalculatePath()
    {
        // Find nearest NavMesh points
        NavMeshHit startHit, endHit;
        if (!NavMesh.SamplePosition(_startPoint, out startHit, 10f, NavMesh.AllAreas))
        {
            Debug.LogWarning("[NavMesh] Start point not on NavMesh");
            state = NavState.Idle;
            return;
        }
        if (!NavMesh.SamplePosition(_endPoint, out endHit, 10f, NavMesh.AllAreas))
        {
            Debug.LogWarning("[NavMesh] End point not on NavMesh");
            state = NavState.Idle;
            return;
        }

        if (NavMesh.CalculatePath(startHit.position, endHit.position, NavMesh.AllAreas, _path))
        {
            if (_path.status == NavMeshPathStatus.PathComplete ||
                _path.status == NavMeshPathStatus.PathPartial)
            {
                DrawPath();
                PathDistance = CalculatePathDistance();
                Debug.Log($"[NavMesh] Path found: {PathDistance:F1}m, " +
                         $"{_path.corners.Length} corners, status={_path.status}");

                // Spawn agent
                SpawnAgent(startHit.position);
                state = NavState.Navigating;
            }
            else
            {
                Debug.LogWarning("[NavMesh] No valid path found");
                state = NavState.Idle;
            }
        }
    }

    private void DrawPath()
    {
        if (_pathLine != null) Destroy(_pathLine.gameObject);

        var go = new GameObject("__navmesh_path");
        _pathLine = go.AddComponent<LineRenderer>();
        _pathLine.positionCount = _path.corners.Length;
        _pathLine.SetPositions(_path.corners);
        _pathLine.startWidth = _pathLine.endWidth = 0.15f;
        _pathLine.material = new Material(Shader.Find("Sprites/Default")) { color = pathColor };
        _pathLine.startColor = _pathLine.endColor = pathColor;
    }

    private float CalculatePathDistance()
    {
        float dist = 0;
        for (int i = 1; i < _path.corners.Length; i++)
            dist += Vector3.Distance(_path.corners[i - 1], _path.corners[i]);
        return dist;
    }

    private void SpawnAgent(Vector3 position)
    {
        if (_agent != null) Destroy(_agent);
        _agent = GameObject.CreatePrimitive(PrimitiveType.Capsule);
        _agent.name = "__navmesh_agent";
        _agent.transform.position = position;
        _agent.transform.localScale = new Vector3(agentRadius * 2, 1f, agentRadius * 2);
        _agent.GetComponent<Renderer>().material.color = new Color(0f, 0.8f, 1f, 0.8f);
        Destroy(_agent.GetComponent<Collider>());
        _agentPathIndex = 0;
    }

    private void SpawnMarker(Vector3 pos, Color color, string name)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        go.transform.position = pos;
        go.transform.localScale = Vector3.one * 0.5f;
        go.GetComponent<Renderer>().material.color = color;
        Destroy(go.GetComponent<Collider>());
        go.name = name;
        _markers.Add(go);
    }

    public void Reset()
    {
        state = NavState.Idle;
        PathDistance = 0;
        foreach (var m in _markers) if (m) Destroy(m);
        _markers.Clear();
        if (_pathLine != null) Destroy(_pathLine.gameObject);
        if (_agent != null) Destroy(_agent);
    }
}
