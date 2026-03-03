// FloatingOriginManager.cs — Section 4.3
// Prevents large-coordinate floating-point jitter by periodically
// re-centering the world around the camera.

using UnityEngine;
using System.Collections.Generic;

public class FloatingOriginManager : MonoBehaviour
{
    [Header("Threshold")]
    [Tooltip("Distance from origin before re-centering")]
    public float shiftThreshold = 500f;

    [Header("Tracking")]
    public Transform targetCamera;

    // Cumulative world offset (add this to convert local→absolute coords)
    public Vector3d AbsoluteOffset { get; private set; }

    private readonly List<Transform> _rootObjects = new();

    void Start()
    {
        if (targetCamera == null)
            targetCamera = Camera.main?.transform;
        AbsoluteOffset = Vector3d.zero;
    }

    void LateUpdate()
    {
        if (targetCamera == null) return;

        Vector3 camPos = targetCamera.position;
        float dist = new Vector2(camPos.x, camPos.z).magnitude;

        if (dist < shiftThreshold) return;

        Vector3 delta = camPos;
        delta.y = 0; // only shift XZ

        // Shift all root GameObjects
        _rootObjects.Clear();
        for (int i = 0; i < transform.parent?.childCount; i++)
        {
            var child = transform.parent.GetChild(i);
            _rootObjects.Add(child);
        }
        // Fallback: shift scene roots
        if (_rootObjects.Count == 0)
        {
            foreach (GameObject go in UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects())
                _rootObjects.Add(go.transform);
        }

        foreach (var t in _rootObjects)
        {
            t.position -= delta;
        }

        // Update cumulative offset
        AbsoluteOffset = new Vector3d(
            AbsoluteOffset.x + delta.x,
            AbsoluteOffset.y,
            AbsoluteOffset.z + delta.z
        );

        Debug.Log($"[FloatingOrigin] Shifted by ({delta.x:F1}, {delta.z:F1}), " +
                  $"cumulative: ({AbsoluteOffset.x:F1}, {AbsoluteOffset.z:F1})");
    }

    /// <summary>Convert local (shifted) position to absolute world coordinates.</summary>
    public Vector3d LocalToAbsolute(Vector3 localPos)
    {
        return new Vector3d(
            localPos.x + AbsoluteOffset.x,
            localPos.y + AbsoluteOffset.y,
            localPos.z + AbsoluteOffset.z
        );
    }

    /// <summary>Convert absolute world coordinates to local (shifted) position.</summary>
    public Vector3 AbsoluteToLocal(Vector3d absolutePos)
    {
        return new Vector3(
            (float)(absolutePos.x - AbsoluteOffset.x),
            (float)(absolutePos.y - AbsoluteOffset.y),
            (float)(absolutePos.z - AbsoluteOffset.z)
        );
    }
}

/// <summary>Double-precision 3D vector for large-world coordinates.</summary>
[System.Serializable]
public struct Vector3d
{
    public double x, y, z;

    public Vector3d(double x, double y, double z)
    {
        this.x = x; this.y = y; this.z = z;
    }

    public static Vector3d zero => new(0, 0, 0);

    public override string ToString() => $"({x:F2}, {y:F2}, {z:F2})";
}
