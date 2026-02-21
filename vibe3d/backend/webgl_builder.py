"""Vibe3D WebGL Viewer — Setup & Build plan generator.

Generates Unity MCP action plans for:
  1. Installing camera rig, C# viewer scripts, UI, and highlight material
  2. Triggering a WebGL build to a user-specified output path

The generated plans follow the standard Vibe3D approval flow:
  plan_ready → user approve → executor batches → MCP.
"""

from __future__ import annotations

from . import config

# ---------------------------------------------------------------------------
# C# Script Sources
# ---------------------------------------------------------------------------

ORBIT_PAN_ZOOM_CS = r"""using UnityEngine;
using System.Runtime.InteropServices;

/// <summary>
/// Orbit / Pan / Zoom camera controller — direct position computation.
/// Does NOT depend on parent-child hierarchy; works standalone on any GameObject.
/// WebGL-safe: jslib scroll bridge, touch support, FOV-based zoom.
/// </summary>
public class OrbitPanZoomController : MonoBehaviour
{
    [Header("Orbit")]
    public float rotateSpeed = 0.25f;
    public float minPitch = -80f;
    public float maxPitch = 80f;

    [Header("Zoom (FOV)")]
    public float zoomSpeed = 5f;
    public float minFov = 10f;
    public float maxFov = 90f;
    public float zoomSmooth = 8f;

    [Header("Pan")]
    public float panSpeed = 1f;

    Vector3 _pivot;
    float _yaw, _pitch, _dist;
    float _targetFov;
    Camera _cam;

    // Drag state — only track delta while actually dragging
    bool _dragging;
    int _dragBtn = -1;
    Vector3 _dragLast;

    // Touch pinch
    float _pinchDist0;

    // WebGL scroll bridge — SendMessage fallback (set from JavaScript)
    float _webglScroll;

    // Initial state for Reset
    Vector3 _initPivot;
    float _initYaw, _initPitch, _initDist, _initFov;

#if UNITY_WEBGL && !UNITY_EDITOR
    [DllImport("__Internal")]
    private static extern float WebGL_GetScrollDelta();
#endif

    void Start()
    {
        // Force sensible defaults — prevents MCP/automation from corrupting values
        rotateSpeed = 0.25f;
        zoomSpeed = 5f;
        minFov = 10f;
        maxFov = 90f;
        panSpeed = 1f;
        zoomSmooth = 8f;

        _cam = GetComponentInChildren<Camera>();
        if (_cam == null) _cam = Camera.main;
        if (_cam == null) { enabled = false; return; }

        // Derive pivot from where the camera is currently looking
        Vector3 fwd = _cam.transform.forward;
        Vector3 pos = _cam.transform.position;
        _dist = 40f;
        if (Physics.Raycast(pos, fwd, out RaycastHit hit, 500f))
            _dist = Mathf.Max(hit.distance, 1f);
        _pivot = pos + fwd * _dist;

        _targetFov = _cam.fieldOfView;

        // Extract yaw/pitch from camera->pivot direction
        Vector3 dir = (pos - _pivot).normalized;
        _pitch = Mathf.Asin(Mathf.Clamp(dir.y, -1f, 1f)) * Mathf.Rad2Deg;
        _yaw = Mathf.Atan2(dir.x, dir.z) * Mathf.Rad2Deg;

        _initPivot = _pivot;
        _initYaw = _yaw;
        _initPitch = _pitch;
        _initDist = _dist;
        _initFov = _targetFov;

        ApplyCamera();
    }

    void LateUpdate()
    {
        if (_cam == null) return;
        HandleMouse();
        HandleTouch();
        if (Input.GetKeyDown(KeyCode.R)) ResetView();

        // Smooth FOV interpolation
        _cam.fieldOfView = Mathf.Lerp(_cam.fieldOfView, _targetFov, Time.deltaTime * zoomSmooth);
        ApplyCamera();
    }

    void HandleMouse()
    {
        // ── Scroll zoom — FOV based, triple fallback ──
        // Source 1: Unity native Input (works in Editor, may work in WebGL)
        float scroll = Input.mouseScrollDelta.y;

        // Source 2: jslib bridge (WebGL only — reads window._webglScrollDelta)
#if UNITY_WEBGL && !UNITY_EDITOR
        try { scroll += WebGL_GetScrollDelta(); } catch {}
#endif

        // Source 3: SendMessage fallback (accumulated in _webglScroll)
        scroll += _webglScroll;
        _webglScroll = 0f;

        if (Mathf.Abs(scroll) > 0.001f)
        {
            _targetFov -= scroll * zoomSpeed;
            _targetFov = Mathf.Clamp(_targetFov, minFov, maxFov);
        }

        // ── Drag start ──
        if (!_dragging)
        {
            for (int i = 0; i < 3; i++)
            {
                if (Input.GetMouseButtonDown(i))
                {
                    _dragging = true;
                    _dragBtn = i;
                    _dragLast = Input.mousePosition;
                    return;
                }
            }
            return; // nothing pressed
        }

        // ── Drag end ──
        if (!Input.GetMouseButton(_dragBtn))
        {
            _dragging = false;
            _dragBtn = -1;
            return;
        }

        // ── Drag move ──
        Vector3 mouse = Input.mousePosition;
        Vector3 delta = mouse - _dragLast;
        _dragLast = mouse;

        bool shift = Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);

        if (_dragBtn == 0 && !shift) // Left-drag = Orbit
        {
            _yaw += delta.x * rotateSpeed;
            _pitch -= delta.y * rotateSpeed;
            _pitch = Mathf.Clamp(_pitch, minPitch, maxPitch);
        }
        else // Right / Middle / Shift+Left = Pan
        {
            float factor = _dist * panSpeed * 0.001f;
            _pivot += _cam.transform.right * delta.x * factor
                    - _cam.transform.up    * delta.y * factor;
        }
    }

    void HandleTouch()
    {
        int tc = Input.touchCount;
        if (tc == 1)
        {
            Touch t = Input.GetTouch(0);
            if (t.phase == TouchPhase.Moved)
            {
                _yaw += t.deltaPosition.x * rotateSpeed * 0.5f;
                _pitch -= t.deltaPosition.y * rotateSpeed * 0.5f;
                _pitch = Mathf.Clamp(_pitch, minPitch, maxPitch);
            }
        }
        else if (tc >= 2)
        {
            Touch t0 = Input.GetTouch(0);
            Touch t1 = Input.GetTouch(1);
            float pinch = (t0.position - t1.position).magnitude;

            if (t0.phase == TouchPhase.Moved || t1.phase == TouchPhase.Moved)
            {
                // Pinch zoom — FOV based
                if (_pinchDist0 > 0f)
                {
                    float ratio = _pinchDist0 / pinch;
                    _targetFov *= ratio;
                    _targetFov = Mathf.Clamp(_targetFov, minFov, maxFov);
                }
                _pinchDist0 = pinch;

                // Two-finger pan
                Vector3 avg = (t0.deltaPosition + t1.deltaPosition) * 0.5f;
                float f = _dist * panSpeed * 0.001f;
                _pivot += _cam.transform.right * avg.x * f
                        - _cam.transform.up    * avg.y * f;
            }
        }
        if (tc < 2) _pinchDist0 = 0f;
    }

    void ApplyCamera()
    {
        Quaternion rot = Quaternion.Euler(_pitch, _yaw, 0f);
        _cam.transform.position = _pivot + rot * (Vector3.back * _dist);
        _cam.transform.LookAt(_pivot, Vector3.up);
    }

    public void ResetView()
    {
        _pivot = _initPivot;
        _yaw = _initYaw;
        _pitch = _initPitch;
        _dist = _initDist;
        _targetFov = _initFov;
        _cam.fieldOfView = _initFov;
    }

    /// <summary>Called from JavaScript wheel event handler via SendMessage (fallback).</summary>
    public void OnWebGLScroll(float delta)
    {
        _webglScroll += delta;
    }

    /// <summary>Set the orbit pivot point (called by ObjectPickerAndFocus).</summary>
    public void SetPivot(Vector3 worldPos) { _pivot = worldPos; }
    public Vector3 GetPivot() { return _pivot; }
}
"""

OBJECT_PICKER_CS = r"""using UnityEngine;
using System.Collections;

/// <summary>
/// Click-to-select, highlight, double-click-to-focus with info display.
/// Uses Physics.Raycast first, falls back to Renderer.bounds for scenes without colliders.
/// WebGL-safe (no EventSystem, no Canvas).
/// </summary>
public class ObjectPickerAndFocus : MonoBehaviour
{
    [Header("Selection")]
    public LayerMask equipmentMask = ~0;
    public Color highlightColor = new Color(1f, 0.9f, 0.2f, 1f);

    [Header("Focus")]
    public float focusDuration = 0.6f;
    public float doubleClickThreshold = 0.35f;

    GameObject _selected;
    Color[] _origColors;
    Renderer[] _rends;
    float _lastClickTime;
    OrbitPanZoomController _orbit;
    Camera _cam;
    bool _focusing;
    Vector3 _mouseDown;
    const float CLICK_MOVE_THRESHOLD = 5f; // pixels — ignore drags as clicks

    // Info display
    GUIStyle _infoStyle;
    string _infoText;

    void Start()
    {
        _cam = GetComponent<Camera>();
        if (_cam == null) _cam = Camera.main;
        if (_cam == null) { enabled = false; return; }
        _orbit = FindFirstObjectByType<OrbitPanZoomController>();
    }

    void Update()
    {
        if (_cam == null) return;
        if (Input.GetKeyDown(KeyCode.Escape)) Deselect();
        if (Input.GetMouseButtonDown(0)) _mouseDown = Input.mousePosition;
        if (Input.GetMouseButtonUp(0) && !_focusing)
        {
            if ((Input.mousePosition - _mouseDown).magnitude < CLICK_MOVE_THRESHOLD)
                TryPick();
        }
    }

    void TryPick()
    {
        Ray ray = _cam.ScreenPointToRay(Input.mousePosition);

        // Method 1: Physics Raycast (requires colliders)
        if (Physics.Raycast(ray, out RaycastHit hit, 1000f, equipmentMask))
        {
            PickObject(hit.collider.gameObject);
            return;
        }

        // Method 2: Renderer bounds intersection (no colliders needed)
        float closestDist = float.MaxValue;
        Renderer closestRend = null;
        foreach (Renderer r in FindObjectsByType<Renderer>(FindObjectsSortMode.None))
        {
            if (r == null || !r.enabled || !r.gameObject.activeInHierarchy) continue;
            if (r.bounds.IntersectRay(ray, out float dist) && dist < closestDist)
            {
                closestDist = dist;
                closestRend = r;
            }
        }
        if (closestRend != null)
            PickObject(closestRend.gameObject);
    }

    void PickObject(GameObject go)
    {
        Transform t = go.transform;
        while (t.parent != null && t.parent.gameObject.layer == go.layer)
            t = t.parent;
        go = t.gameObject;

        float now = Time.time;
        bool dbl = _selected == go && now - _lastClickTime < doubleClickThreshold;
        _lastClickTime = now;

        Select(go);
        if (dbl) StartCoroutine(FocusOn(go));
    }

    void Select(GameObject obj)
    {
        RestoreColors();
        _selected = obj;
        _rends = obj.GetComponentsInChildren<Renderer>();
        _origColors = new Color[_rends.Length];
        for (int i = 0; i < _rends.Length; i++)
        {
            if (_rends[i] == null || _rends[i].sharedMaterial == null) continue;
            _origColors[i] = _rends[i].material.color;
            _rends[i].material.color = highlightColor;
        }
        UpdateInfoText(obj);
    }

    public void Deselect()
    {
        RestoreColors();
        _selected = null;
        _infoText = null;
    }

    void RestoreColors()
    {
        if (_rends == null) return;
        for (int i = 0; i < _rends.Length; i++)
        {
            if (_rends[i] != null && _rends[i].sharedMaterial != null)
                _rends[i].material.color = _origColors[i];
        }
        _rends = null;
        _origColors = null;
    }

    void UpdateInfoText(GameObject obj)
    {
        Vector3 pos = obj.transform.position;
        _infoText = obj.name;
        _infoText += string.Format("\nPosition: ({0:F1}, {1:F1}, {2:F1})", pos.x, pos.y, pos.z);

        Renderer[] renderers = obj.GetComponentsInChildren<Renderer>();
        if (renderers.Length > 0)
        {
            Bounds b = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
                if (renderers[i] != null) b.Encapsulate(renderers[i].bounds);
            _infoText += string.Format("\nSize: {0:F1} x {1:F1} x {2:F1}", b.size.x, b.size.y, b.size.z);
        }

        int childCount = obj.transform.childCount;
        if (childCount > 0)
            _infoText += "\nChildren: " + childCount;

        _infoText += "\n[DblClick: Focus | ESC: Deselect]";
    }

    void OnGUI()
    {
        if (_selected == null || string.IsNullOrEmpty(_infoText)) return;

        if (_infoStyle == null)
        {
            _infoStyle = new GUIStyle(GUI.skin.box);
            _infoStyle.fontSize = 13;
            _infoStyle.alignment = TextAnchor.UpperLeft;
            _infoStyle.normal.textColor = Color.white;
            _infoStyle.padding = new RectOffset(10, 10, 8, 8);
        }
        GUI.Box(new Rect(10, Screen.height - 130, 380, 120), _infoText, _infoStyle);
    }

    IEnumerator FocusOn(GameObject obj)
    {
        if (_orbit == null) yield break;
        _focusing = true;

        Bounds b = new Bounds(obj.transform.position, Vector3.zero);
        foreach (Renderer r in obj.GetComponentsInChildren<Renderer>())
            if (r != null) b.Encapsulate(r.bounds);

        Vector3 from = _orbit.GetPivot();
        Vector3 to = b.center;
        float elapsed = 0f;

        while (elapsed < focusDuration)
        {
            elapsed += Time.deltaTime;
            float s = Mathf.SmoothStep(0f, 1f, elapsed / focusDuration);
            _orbit.SetPivot(Vector3.Lerp(from, to, s));
            yield return null;
        }
        _orbit.SetPivot(to);
        _focusing = false;
    }
}
"""

VIEWER_UI_CS = r"""using UnityEngine;

/// <summary>
/// Minimal WebGL viewer UI — keyboard-only controls, no Canvas/Font dependency.
/// Avoids runtime UI creation that can crash in WebGL builds.
/// Attach to ViewerCanvas (kept for component compatibility).
/// </summary>
public class ViewerUIController : MonoBehaviour
{
    // This script intentionally does nothing that requires Canvas or Fonts.
    // Camera controls are handled by OrbitPanZoomController (mouse)
    // and ObjectPickerAndFocus (click/ESC).
    //
    // Controls (displayed via OnGUI):
    //   Left-drag  : Orbit
    //   Right-drag : Pan
    //   Scroll     : Zoom
    //   Click      : Select object
    //   Double-click: Focus object
    //   R          : Reset camera
    //   ESC        : Deselect

    GUIStyle _style;
    float _showUntil;

    void Start()
    {
        _showUntil = Time.time + 8f; // show help for 8 seconds
    }

    void OnGUI()
    {
        if (Time.time > _showUntil) return;
        if (_style == null)
        {
            _style = new GUIStyle(GUI.skin.box);
            _style.fontSize = 13;
            _style.alignment = TextAnchor.UpperLeft;
            _style.normal.textColor = Color.white;
            _style.padding = new RectOffset(8, 8, 6, 6);
        }
        string help = "Drag: Orbit | RightDrag: Pan | Scroll: Zoom\nClick: Select | DblClick: Focus | R: Reset | ESC: Deselect";
        GUI.Box(new Rect(10, 10, 440, 46), help, _style);
    }

    // Keep public API for backward compat (ObjectPickerAndFocus may call these)
    public void SetSelectedName(string name) { }
}
"""

WEBGL_BUILD_HELPER_CS = r"""#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

/// <summary>
/// One-click WebGL build with domain-reload-safe platform switch.
/// After build, patches index.html to add scroll/context-menu prevention
/// and full-viewport canvas for proper camera controls.
/// </summary>
[InitializeOnLoad]
public static class WebGLBuildHelper
{
    const string PREF_KEY = "Vibe3D_WebGL_BuildPath";
    const string PENDING_KEY = "Vibe3D_PendingWebGLBuild";

    static WebGLBuildHelper()
    {
        if (SessionState.GetBool(PENDING_KEY, false))
        {
            SessionState.EraseBool(PENDING_KEY);
            EditorApplication.delayCall += DoBuild;
        }
    }

    [MenuItem("Vibe3D/Build WebGL")]
    public static void BuildWebGL()
    {
        if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.WebGL)
        {
            Debug.Log("[Vibe3D] Switching to WebGL platform (domain reload will occur)...");
            SessionState.SetBool(PENDING_KEY, true);
            EditorUserBuildSettings.SwitchActiveBuildTarget(
                BuildTargetGroup.WebGL, BuildTarget.WebGL);
            return;
        }
        DoBuild();
    }

    static void DoBuild()
    {
        string path = EditorPrefs.GetString(PREF_KEY, "");
        if (string.IsNullOrEmpty(path))
            path = System.IO.Path.Combine(
                System.IO.Directory.GetParent(Application.dataPath).FullName,
                "WebGL_Build");

        Debug.Log($"[Vibe3D] WebGL build started -> {path}");

        try
        {
            PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;

            var scenes = new System.Collections.Generic.List<string>();
            foreach (var s in EditorBuildSettings.scenes)
                if (s.enabled) scenes.Add(s.path);
            if (scenes.Count == 0 && !string.IsNullOrEmpty(
                    UnityEngine.SceneManagement.SceneManager.GetActiveScene().path))
                scenes.Add(UnityEngine.SceneManagement.SceneManager.GetActiveScene().path);

            if (scenes.Count == 0)
            {
                Debug.LogError("[Vibe3D] WebGL build aborted: no scenes to build.");
                return;
            }

            Debug.Log($"[Vibe3D] Building {scenes.Count} scene(s): {string.Join(", ", scenes)}");

            var opts = new BuildPlayerOptions
            {
                scenes = scenes.ToArray(),
                locationPathName = path,
                target = BuildTarget.WebGL,
                options = BuildOptions.None,
            };
            var report = BuildPipeline.BuildPlayer(opts);

            if (report.summary.result == UnityEditor.Build.Reporting.BuildResult.Succeeded)
            {
                Debug.Log($"[Vibe3D] WebGL build succeeded: {path} ({report.summary.totalTime})");
                PatchIndexHtml(path);
            }
            else
                Debug.LogError($"[Vibe3D] WebGL build failed: {report.summary.result}");
        }
        catch (System.Exception ex)
        {
            Debug.LogError($"[Vibe3D] WebGL build exception: {ex.Message}\n{ex.StackTrace}");
        }
    }

    /// <summary>
    /// Replace the generated index.html with a version that has:
    /// - Full-viewport canvas (no fixed 1920x1080)
    /// - Scroll wheel event prevention (stops browser page scroll)
    /// - Right-click context menu prevention
    /// - Auto-focus canvas on interaction
    /// - Dark background
    /// </summary>
    static void PatchIndexHtml(string buildPath)
    {
        string indexPath = System.IO.Path.Combine(buildPath, "index.html");
        if (!System.IO.File.Exists(indexPath)) return;

        string productName = Application.productName;
        string html = $@"<!DOCTYPE html>
<html lang=""en"">
<head>
<meta charset=""utf-8"">
<meta name=""viewport"" content=""width=device-width,initial-scale=1"">
<title>{productName} — WebGL Viewer</title>
<link rel=""shortcut icon"" href=""TemplateData/favicon.ico"">
<style>
*{{margin:0;padding:0}}
html,body{{overflow:hidden;width:100%;height:100%;background:#1a1a2e}}
#unity-canvas{{width:100%;height:100%;display:block;outline:none}}
#unity-loading-bar{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);text-align:center}}
#unity-progress-bar-empty{{width:220px;height:6px;background:#333;border-radius:3px;margin:8px auto}}
#unity-progress-bar-full{{width:0%;height:100%;background:#4fc3f7;border-radius:3px;transition:width .1s}}
#unity-warning{{position:absolute;left:50%;top:5%;transform:translateX(-50%);z-index:10}}
</style>
</head>
<body>
<canvas id=""unity-canvas"" tabindex=""0""></canvas>
<div id=""unity-loading-bar"">
  <div id=""unity-progress-bar-empty""><div id=""unity-progress-bar-full""></div></div>
</div>
<div id=""unity-warning""></div>
<script>
var canvas=document.getElementById('unity-canvas');

// ── Scroll: jslib bridge + SendMessage fallback ──
canvas.addEventListener('wheel',function(e){{
  e.preventDefault();
  var d=e.deltaY;
  if(e.deltaMode===1)d*=33;
  else if(e.deltaMode===2)d*=window.innerHeight;
  d=d/-100;
  d=Math.max(-3,Math.min(3,d));
  window._webglScrollDelta=(window._webglScrollDelta||0)+d;
  if(window.unityInstance)window.unityInstance.SendMessage('CameraRig','OnWebGLScroll',d);
}},{{passive:false}});
canvas.addEventListener('contextmenu',function(e){{e.preventDefault();}});
canvas.addEventListener('mousedown',function(){{canvas.focus();}});
// Touch: prevent pull-to-refresh and pinch-zoom on the canvas
canvas.addEventListener('touchstart',function(e){{if(e.touches.length>1)e.preventDefault();}},{{passive:false}});
canvas.addEventListener('touchmove',function(e){{e.preventDefault();}},{{passive:false}});

function unityShowBanner(msg,type){{
  var w=document.getElementById('unity-warning');
  var d=document.createElement('div');d.innerHTML=msg;
  d.style='padding:8px;color:#fff;'+(type=='error'?'background:red':'background:#e65100');
  w.appendChild(d);
  if(type!='error')setTimeout(function(){{w.removeChild(d);}},5000);
}}

var config={{
  dataUrl:'Build/{productName}.data',
  frameworkUrl:'Build/{productName}.framework.js',
  codeUrl:'Build/{productName}.wasm',
  streamingAssetsUrl:'StreamingAssets',
  companyName:'DefaultCompany',
  productName:'{productName}',
  showBanner:unityShowBanner,
}};

// Fallback: try generic names if product-specific files don't exist
var loaderUrl='Build/{productName}.loader.js';
var script=document.createElement('script');
script.src=loaderUrl;
script.onerror=function(){{
  // Fallback to WebGL.loader.js
  var s2=document.createElement('script');
  s2.src='Build/WebGL.loader.js';
  s2.onload=function(){{boot({{
    dataUrl:'Build/WebGL.data',
    frameworkUrl:'Build/WebGL.framework.js',
    codeUrl:'Build/WebGL.wasm',
    streamingAssetsUrl:'StreamingAssets',
    companyName:'DefaultCompany',
    productName:'{productName}',
    showBanner:unityShowBanner,
  }});}};
  document.body.appendChild(s2);
}};
script.onload=function(){{boot(config);}};
document.body.appendChild(script);

function boot(cfg){{
  var bar=document.getElementById('unity-loading-bar');
  bar.style.display='block';
  createUnityInstance(canvas,cfg,function(p){{
    document.getElementById('unity-progress-bar-full').style.width=(100*p)+'%';
  }}).then(function(inst){{
    window.unityInstance=inst;
    bar.style.display='none';
    canvas.focus();
  }}).catch(function(msg){{alert(msg);}});
}}
</script>
</body>
</html>";

        System.IO.File.WriteAllText(indexPath, html, System.Text.Encoding.UTF8);
        Debug.Log($"[Vibe3D] Patched index.html with scroll/context-menu prevention");
    }

    [MenuItem("Vibe3D/Set WebGL Build Path")]
    public static void SetBuildPath()
    {
        string current = EditorPrefs.GetString(PREF_KEY, "");
        string path = EditorUtility.SaveFolderPanel("Select WebGL Build Output", current, "WebGL_Build");
        if (!string.IsNullOrEmpty(path))
        {
            EditorPrefs.SetString(PREF_KEY, path);
            Debug.Log($"[Vibe3D] WebGL build path set to: {path}");
        }
    }
}
#endif
"""


WEBGL_INPUT_JSLIB = r"""mergeInto(LibraryManager.library, {
    WebGL_GetScrollDelta: function() {
        var d = window._webglScrollDelta || 0;
        window._webglScrollDelta = 0;
        return d;
    }
});
"""


# ---------------------------------------------------------------------------
# Plan Generators
# ---------------------------------------------------------------------------

def generate_setup_plan(*, components_only: bool = False) -> dict:
    """Generate a multi-phase plan to install WebGL viewer into the Unity scene.

    Args:
        components_only: If True, skip scene object creation (CameraRig, Pivot,
            ViewerCanvas, layer) and only include scripts + components.
            Use when objects already exist but components are missing.

    Returns a plan dict compatible with plan_validator / executor.
    The executor handles batching via _split_by_dependency (creates → modifiers).
    """
    actions: list[dict] = []

    if not components_only:
        # ── Phase 1: Scene structure ──────────────────────────────
        actions.append({
            "type": "create_empty",
            "name": "CameraRig",
            "position": {"x": 0, "y": 0, "z": 0},
        })
        actions.append({
            "type": "create_empty",
            "name": "Pivot",
            "parent": "CameraRig",
            "position": {"x": 0, "y": 0, "z": 0},
        })
        # Re-parent Main Camera under Pivot and set local transform
        actions.append({
            "type": "modify_object",
            "target": "Main Camera",
            "parent": "Pivot",
            "position": {"x": 0, "y": 20, "z": -40},
            "rotation": {"x": 15, "y": 0, "z": 0},
        })
        # Canvas for runtime UI (ViewerUIController builds children at Start)
        actions.append({
            "type": "create_empty",
            "name": "ViewerCanvas",
        })
        # Equipment layer for object picking
        actions.append({
            "type": "add_layer",
            "layer_name": "Equipment",
        })

    # ── Phase 2: C# scripts + jslib plugin ───────────────────
    actions.append({
        "type": "create_script",
        "name": "WebGLInput",
        "path": "Assets/Plugins/WebGL/WebGLInput.jslib",
        "contents": WEBGL_INPUT_JSLIB,
    })
    actions.append({
        "type": "create_script",
        "name": "OrbitPanZoomController",
        "path": "Assets/Scripts/Viewer/OrbitPanZoomController.cs",
        "contents": ORBIT_PAN_ZOOM_CS,
    })
    actions.append({
        "type": "create_script",
        "name": "ObjectPickerAndFocus",
        "path": "Assets/Scripts/Viewer/ObjectPickerAndFocus.cs",
        "contents": OBJECT_PICKER_CS,
    })
    actions.append({
        "type": "create_script",
        "name": "ViewerUIController",
        "path": "Assets/Scripts/Viewer/ViewerUIController.cs",
        "contents": VIEWER_UI_CS,
    })

    # ── Phase 3: Asset refresh (compile scripts) ─────────────
    actions.append({
        "type": "refresh_assets",
        "scope": "all",
        "compile": "request",
    })

    # ── Phase 4: Component attachment + material ─────────────
    actions.append({
        "type": "add_component",
        "target": "CameraRig",
        "component_type": "OrbitPanZoomController",
    })
    actions.append({
        "type": "add_component",
        "target": "Main Camera",
        "component_type": "ObjectPickerAndFocus",
    })
    actions.append({
        "type": "add_component",
        "target": "ViewerCanvas",
        "component_type": "ViewerUIController",
    })
    # Highlight material (Emission yellow)
    actions.append({
        "type": "create_material",
        "name": "Highlight",
        "color": {"r": 1.0, "g": 0.9, "b": 0.2, "a": 1.0},
        "properties": {
            "_EmissionColor": {"r": 1.0, "g": 0.9, "b": 0.2, "a": 1.0},
        },
    })
    # Save scene
    actions.append({
        "type": "save_scene",
    })

    desc = (
        "WebGL 뷰어 컴포넌트 부착 (스크립트 재생성 + 부착)"
        if components_only
        else "WebGL Viewer 설치: CameraRig + 스크립트 3종 + UI + Highlight Material"
    )
    msg = (
        "스크립트 3종 재생성 및 컴포넌트 부착"
        if components_only
        else (
            "WebGL 뷰어를 설치합니다: CameraRig/Pivot 생성, "
            "카메라 컨트롤 스크립트 3종 생성 및 부착, "
            "Equipment 레이어 추가, Highlight 머티리얼 생성"
        )
    )
    return {
        "project": "My project",
        "scene": config.DEFAULT_SCENE,
        "description": desc,
        "confirmation_message": f"{msg} (총 {len(actions)}개 작업)",
        "actions": actions,
    }


def generate_build_plan(
    output_path: str,
    *,
    include_setup: bool = False,
    components_only: bool = False,
) -> dict:
    """Generate a plan that installs the build helper script and triggers WebGL build.

    Args:
        output_path: Absolute path for the WebGL build output.
        include_setup: If True, prepend the viewer setup before the build actions.
        components_only: Passed to generate_setup_plan — skip object creation,
            only re-create scripts and attach components.
    """
    actions: list[dict] = []

    # ── Optional: viewer setup ───────────────────────────────
    if include_setup:
        setup_plan = generate_setup_plan(components_only=components_only)
        actions.extend(setup_plan["actions"])

    # ── Build helper script ──────────────────────────────────
    build_cs = WEBGL_BUILD_HELPER_CS.replace(
        'const string PREF_KEY = "Vibe3D_WebGL_BuildPath";',
        f'const string PREF_KEY = "Vibe3D_WebGL_BuildPath";\n'
        f'    const string DEFAULT_PATH = @"{output_path}";',
    ).replace(
        'string path = EditorPrefs.GetString(PREF_KEY, "");',
        'string path = EditorPrefs.GetString(PREF_KEY, DEFAULT_PATH);',
    )

    actions.append({
        "type": "create_script",
        "name": "WebGLBuildHelper",
        "path": "Assets/Scripts/Editor/WebGLBuildHelper.cs",
        "contents": build_cs,
    })
    # Always refresh after WebGLBuildHelper.cs — even when setup included its
    # own refresh for viewer scripts, that refresh ran BEFORE this script was
    # created.  WebGLBuildHelper must be compiled before execute_menu.
    actions.append({
        "type": "refresh_assets",
        "scope": "all",
        "compile": "request",
    })
    actions.append({
        "type": "execute_menu",
        "menu_path": "Vibe3D/Build WebGL",
    })

    setup_note = "뷰어 설치(Setup) + " if include_setup else ""
    return {
        "project": "My project",
        "scene": config.DEFAULT_SCENE,
        "description": f"WebGL 빌드 → {output_path}",
        "confirmation_message": (
            f"{setup_note}WebGL 빌드를 실행합니다.\n"
            f"출력 경로: {output_path}\n"
            + (
                "CameraRig/Pivot 생성, 카메라 컨트롤 스크립트 3종 설치, "
                "Equipment 레이어 추가 후 빌드합니다.\n"
                if include_setup else ""
            )
            + f"(총 {len(actions)}개 작업)"
        ),
        "actions": actions,
    }
