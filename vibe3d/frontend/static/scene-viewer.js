// Vibe3D — Three.js 3D Scene Viewer (ES Module)
// Renders Unity scene objects from MCP hierarchy data with interactive controls.
// Supports object selection, drag-to-move with TransformControls, and Unity sync.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { MTLLoader } from 'three/addons/loaders/MTLLoader.js';

class SceneViewer {
    constructor() {
        this.renderer = null;
        this.scene = null;
        this.camera = null;
        this.controls = null;
        this.transformControls = null;
        this.container = null;
        this.meshMap = new Map(); // uid (path) → mesh
        this.selectedMesh = null;
        this.selectionOutline = null;
        this.outlineMat = new THREE.MeshBasicMaterial({
            color: 0x3b8eea, wireframe: true, transparent: true, opacity: 0.5,
        });
        this.raycaster = new THREE.Raycaster();
        this.pointer = new THREE.Vector2();
        this.animId = null;
        this._initialized = false;
        this._onResize = this.resize.bind(this);
        this._onClick = this._handleClick.bind(this);
        this._onPointerDown = this._handlePointerDown.bind(this);
        this._pointerDownPos = null; // track mousedown for drag detection
        this.onSelect = null; // callback(name, uid)
        this.onMove = null;   // callback(name, unityPosition) — called after drag
        this._moveMode = false; // toggle between view and move mode
        this._dragStartPos = null; // position before drag (for undo detection)
        this._tileGroup = null;    // Group for OBJ city tiles
        this._tileLoadProgress = { loaded: 0, total: 0 };
        this.onTileProgress = null; // callback(loaded, total)
        this._lodTiles = new Map(); // name → { lod: THREE.LOD, levels: {lod0,lod1,lod2} }
        this._lodMemoryTimer = null; // periodic LOD0 memory cleanup
        // GeoBIM
        this._footprintGroup = null;  // Group for building footprint overlays
        this._measureGroup = null;    // Group for measurement lines/labels
        this._measureMode = null;     // 'distance' | 'height' | 'area' | null
        this._measurePoints = [];     // clicked points for current measurement
        this._measureResults = [];    // completed measurement overlays
        this.onBuildingClick = null;   // callback(buildingId)
        this.onMeasure = null;        // callback(mode, result)
        this._buildingFootprints = []; // cached footprint data
        // NavMesh / Pathfinding
        this._navGroup = null;        // Group for nav path overlays
        this.onNavClick = null;       // callback(point:{x,z})
        // Visibility heatmap
        this._visGroup = null;        // Group for visibility heatmap
        // BBox highlight
        this._bboxGroup = null;       // Group for building bbox wireframe + height label
        // Floating Origin
        this._originOffset = { x: 0, z: 0 };
        this._floatingOriginThreshold = 500.0;
    }

    get initialized() { return this._initialized; }
    get moveMode() { return this._moveMode; }

    init(container) {
        if (this._initialized) {
            this.resize();
            return;
        }
        this.container = container;
        const w = container.clientWidth || 400;
        const h = container.clientHeight || 300;

        // Renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
        this.renderer.setSize(w, h);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setClearColor(0x222222);
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.6;
        container.appendChild(this.renderer.domElement);

        // Scene
        this.scene = new THREE.Scene();
        this.scene.fog = new THREE.FogExp2(0x222222, 0.008);

        // Camera
        this.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 500);
        this.camera.position.set(15, 12, 15);

        // Orbit Controls
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.12;
        this.controls.rotateSpeed = 0.4;
        this.controls.panSpeed = 0.4;
        this.controls.zoomSpeed = 0.6;
        this.controls.target.set(0, 1, 0);
        this.controls.minDistance = 0.5;
        this.controls.maxDistance = 200;
        this.controls.maxPolarAngle = Math.PI * 0.95;
        this.controls.screenSpacePanning = true;

        // Transform Controls (for drag-to-move)
        this.transformControls = new TransformControls(this.camera, this.renderer.domElement);
        this.transformControls.setMode('translate');
        this.transformControls.setSize(0.8);
        this.transformControls.visible = false;
        this.transformControls.enabled = false;
        this.scene.add(this.transformControls);

        // Disable orbit while dragging transform gizmo
        this.transformControls.addEventListener('dragging-changed', (event) => {
            this.controls.enabled = !event.value;
            if (event.value) {
                // Drag started — save position
                const obj = this.transformControls.object;
                if (obj) this._dragStartPos = obj.position.clone();
            } else {
                // Drag ended — sync to Unity
                this._onDragEnd();
            }
        });

        // Lights
        const ambient = new THREE.AmbientLight(0xffffff, 0.9);
        this.scene.add(ambient);

        const dirLight = new THREE.DirectionalLight(0xffffff, 1.8);
        dirLight.position.set(10, 20, 10);
        dirLight.castShadow = true;
        dirLight.shadow.mapSize.set(2048, 2048);
        dirLight.shadow.camera.near = 0.5;
        dirLight.shadow.camera.far = 80;
        dirLight.shadow.camera.left = -30;
        dirLight.shadow.camera.right = 30;
        dirLight.shadow.camera.top = 30;
        dirLight.shadow.camera.bottom = -30;
        this.scene.add(dirLight);

        const backLight = new THREE.DirectionalLight(0xffffff, 0.6);
        backLight.position.set(-8, 12, -8);
        this.scene.add(backLight);

        const hemiLight = new THREE.HemisphereLight(0xddeeff, 0x808060, 0.7);
        this.scene.add(hemiLight);

        // Grid
        const grid = new THREE.GridHelper(80, 80, 0x555555, 0x333333);
        grid.position.y = -0.01;
        this.scene.add(grid);

        // Axes
        const axes = new THREE.AxesHelper(2);
        axes.position.set(-0.5, 0.01, -0.5);
        this.scene.add(axes);

        // Events
        window.addEventListener('resize', this._onResize);
        this.renderer.domElement.addEventListener('pointerdown', this._onPointerDown);
        this.renderer.domElement.addEventListener('click', this._onClick);
        this.renderer.domElement.addEventListener('dblclick', () => {
            if (this._measureMode === 'area' && this._measurePoints.length >= 3) {
                this._completeMeasureArea();
            }
        });
        this.renderer.domElement.style.cursor = 'grab';

        // Prevent context menu on right-click (needed for right-drag panning)
        this.renderer.domElement.addEventListener('contextmenu', (e) => e.preventDefault());

        this._initialized = true;
        this._animate();
    }

    resize() {
        if (!this.container || !this.renderer) return;
        const w = this.container.clientWidth;
        const h = this.container.clientHeight;
        if (w <= 0 || h <= 0) return;
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(w, h);
    }

    _animate() {
        this.animId = requestAnimationFrame(() => this._animate());
        if (this.controls) this.controls.update();
        this._checkFloatingOrigin();
        if (this.renderer && this.scene && this.camera) {
            this.renderer.render(this.scene, this.camera);
        }
    }

    // ── Move Mode Toggle ────────────────────────────────────

    /**
     * Toggle move mode on/off.
     * In move mode, clicking an object attaches the translate gizmo.
     * Dragging the gizmo moves the object and syncs to Unity on release.
     */
    setMoveMode(enabled) {
        this._moveMode = enabled;
        if (!enabled) {
            this.transformControls.detach();
            this.transformControls.visible = false;
            this.transformControls.enabled = false;
            this.renderer.domElement.style.cursor = 'grab';
        } else {
            // If an object is already selected, attach gizmo
            if (this.selectedMesh) {
                this.transformControls.attach(this.selectedMesh);
                this.transformControls.visible = true;
                this.transformControls.enabled = true;
            }
            this.renderer.domElement.style.cursor = 'crosshair';
        }
    }

    toggleMoveMode() {
        this.setMoveMode(!this._moveMode);
        return this._moveMode;
    }

    // ── Drag end → sync to Unity ────────────────────────────

    _onDragEnd() {
        const obj = this.transformControls.object;
        if (!obj) return;

        const name = obj.userData.objectName;
        if (!name) return;

        // Check if position actually changed
        if (this._dragStartPos && obj.position.distanceTo(this._dragStartPos) < 0.001) {
            return; // No meaningful movement
        }

        // Update selection outline position
        if (this.selectionOutline) {
            this.selectionOutline.position.copy(obj.position);
        }

        // Convert Three.js position → Unity position (negate Z)
        const unityPos = {
            x: parseFloat(obj.position.x.toFixed(4)),
            y: parseFloat(obj.position.y.toFixed(4)),
            z: parseFloat((-obj.position.z).toFixed(4)),
        };

        console.log(`[SceneViewer] Moved "${name}" to Unity pos:`, unityPos);

        // Notify callback (app.js handles the API call)
        if (this.onMove) {
            this.onMove(name, unityPos);
        }
    }

    // ── Load scene from API ────────────────────────────────

    async loadFromAPI() {
        const isReload = this.meshMap.size > 0;
        try {
            const resp = await fetch(`${window.location.origin}/api/scene/3d-data`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            this.loadScene(data, isReload);
            return data;
        } catch (e) {
            console.warn('[SceneViewer] loadFromAPI failed:', e);
            return null;
        }
    }

    /**
     * Load scene data. On first load, sets camera from suggestion or fit.
     * On subsequent reloads, preserves current camera position/zoom/direction.
     */
    loadScene(data, preserveCamera = false) {
        const hadObjects = this.meshMap.size > 0;
        // Detach transform controls before clearing
        if (this.transformControls) {
            this.transformControls.detach();
        }
        this.clearObjects();
        const objects = data.objects || [];
        for (const obj of objects) {
            this._addObject(obj);
        }

        // Only reset camera on first load — preserve user's view on reloads
        if (!preserveCamera && !hadObjects) {
            if (data.camera_suggestion) {
                const cs = data.camera_suggestion;
                if (cs.position) this.camera.position.set(cs.position[0], cs.position[1], -cs.position[2]);
                if (cs.target) this.controls.target.set(cs.target[0], cs.target[1], -cs.target[2]);
            } else if (objects.length > 0) {
                this._fitCamera();
            }
        }
        this.controls.update();

        // Re-attach transform controls if in move mode and object still exists
        if (this._moveMode && this.selectedMesh) {
            const uid = this.selectedMesh.userData.objectUid || this.selectedMesh.userData.objectName;
            const newMesh = this.meshMap.get(uid);
            if (newMesh) {
                this.selectedMesh = newMesh;
                this.transformControls.attach(newMesh);
                this.transformControls.visible = true;
                this.transformControls.enabled = true;
            }
        }
    }

    // ── Object creation ────────────────────────────────────

    _addObject(obj) {
        const geo = this._createGeo(obj);
        if (!geo) return;

        const c = obj.color || this._inferColor(obj.name);
        const metallic = this._isMetallic(obj.name);
        const isLight = (obj.primitive || this._inferPrimitive(obj.name)) === 'Light';

        const mat = isLight
            ? new THREE.MeshBasicMaterial({ color: new THREE.Color(c.r, c.g, c.b) })
            : new THREE.MeshStandardMaterial({
                color: new THREE.Color(c.r, c.g, c.b),
                metalness: metallic ? 0.7 : 0.1,
                roughness: metallic ? 0.3 : 0.7,
            });

        const mesh = new THREE.Mesh(geo, mat);
        const p = obj.position || { x: 0, y: 0, z: 0 };
        // Unity LH → Three.js RH: negate Z
        mesh.position.set(p.x || 0, p.y || 0, -(p.z || 0));

        const r = obj.rotation || { x: 0, y: 0, z: 0 };
        // Unity LH → Three.js RH: negate X and Y rotation
        mesh.rotation.order = 'YXZ';
        mesh.rotation.set(
            -(r.x || 0) * Math.PI / 180,
            -(r.y || 0) * Math.PI / 180,
            (r.z || 0) * Math.PI / 180,
        );

        const s = obj.scale || { x: 1, y: 1, z: 1 };
        mesh.scale.set(s.x || 1, s.y || 1, s.z || 1);

        mesh.castShadow = !isLight;
        mesh.receiveShadow = !isLight;
        const uid = obj.path || obj.name;
        mesh.userData.objectName = obj.name;
        mesh.userData.objectPath = obj.path || '';
        mesh.userData.objectUid = uid;
        mesh.userData.tag = obj.tag || '';
        mesh.userData.type = obj.type || '';

        this.scene.add(mesh);
        this.meshMap.set(uid, mesh);

        // Light helper — add a point light at light positions
        if (isLight) {
            const pl = new THREE.PointLight(0xfff5e0, 0.6, 15);
            pl.position.copy(mesh.position);
            this.scene.add(pl);
        }
    }

    _createGeo(obj) {
        const prim = obj.primitive || this._inferPrimitive(obj.name);
        switch (prim) {
            case 'Plane':
                return new THREE.BoxGeometry(1, 0.02, 1);
            case 'Sphere':
                return new THREE.SphereGeometry(0.5, 24, 16);
            case 'Cylinder':
                // Unity default cylinder: height=2, radius=0.5
                return new THREE.CylinderGeometry(0.5, 0.5, 2, 24);
            case 'Capsule':
                // Unity default capsule: height=2, radius=0.5
                return new THREE.CapsuleGeometry(0.5, 1.0, 8, 16);
            case 'Cone':
                return new THREE.ConeGeometry(0.5, 1, 24);
            case 'Light':
                return new THREE.SphereGeometry(0.12, 8, 6);
            case 'Empty':
                return null;
            case 'Cube':
            default:
                return new THREE.BoxGeometry(1, 1, 1);
        }
    }

    _inferPrimitive(name) {
        if (!name) return 'Cube';
        const n = name.toLowerCase();
        if (n.includes('floor') || n.includes('ground') || n.includes('platform') || n.includes('checker')) return 'Cube';
        if (n.includes('plane')) return 'Plane';
        if (n.includes('sphere') || n.includes('ball') || n.includes('dome') || n.includes('dishhead') || n.includes('dish_head')) return 'Sphere';
        if (n.includes('cylinder') || n.includes('body') || n.includes('pipe') || n.includes('column') || n.includes('tube') || n.includes('col_') || n.includes('jacket') || n.includes('tank') || n.includes('vessel') || n.includes('scrubber') || n.includes('receiver') || n.includes('drum') || n.includes('shaft') || n.includes('nozzle') || n.includes('inlet') || n.includes('outlet') || n.includes('header') || n.includes('exhaust')) return 'Cylinder';
        if (n.includes('capsule')) return 'Capsule';
        if (n.includes('cone')) return 'Cone';
        if (n.includes('light') || n.includes('lamp')) return 'Light';
        if (n === 'main camera' || n.includes('camera') || n.includes('eventsystem')) return 'Empty';
        return 'Cube';
    }

    _inferColor(name) {
        if (!name) return { r: 0.6, g: 0.6, b: 0.65 };
        const n = name.toLowerCase();
        if (n.includes('floor') || n.includes('ground')) return { r: 0.35, g: 0.36, b: 0.38 };
        if (n.includes('dome')) return { r: 0.78, g: 0.8, b: 0.83 };
        if (n.includes('body') || n.includes('tank') || n.includes('vessel')) return { r: 0.75, g: 0.77, b: 0.8 };
        if (n.includes('pipe') || n.includes('tube')) return { r: 0.5, g: 0.52, b: 0.55 };
        if (n.includes('valve')) return { r: 0.6, g: 0.3, b: 0.3 };
        if (n.includes('pump')) return { r: 0.3, g: 0.45, b: 0.6 };
        if (n.includes('light') || n.includes('lamp')) return { r: 1.0, g: 0.95, b: 0.6 };
        if (n.includes('wall')) return { r: 0.85, g: 0.85, b: 0.82 };
        if (n.includes('jacket') || n.includes('cooling')) return { r: 0.3, g: 0.5, b: 0.7 };
        if (n.includes('agitator') || n.includes('motor')) return { r: 0.4, g: 0.42, b: 0.45 };
        if (n.includes('platform') || n.includes('stair')) return { r: 0.5, g: 0.48, b: 0.42 };
        return { r: 0.6, g: 0.6, b: 0.65 };
    }

    _isMetallic(name) {
        if (!name) return false;
        const n = name.toLowerCase();
        return n.includes('tank') || n.includes('body') || n.includes('dome') ||
               n.includes('pipe') || n.includes('valve') || n.includes('vessel') ||
               n.includes('jacket') || n.includes('stainless') || n.includes('metal');
    }

    // ── Color update ────────────────────────────────────────

    /**
     * Update the color of a scene object by name.
     * @param {string} name - Object name (must exist in meshMap)
     * @param {{r:number, g:number, b:number}} color - RGB color (0-1 range)
     */
    updateObjectColor(name, color) {
        // Look up by uid (path) first, fallback to name search
        let mesh = this.meshMap.get(name);
        if (!mesh) {
            for (const m of this.meshMap.values()) {
                if (m.userData.objectName === name) { mesh = m; break; }
            }
        }
        if (!mesh) return false;
        mesh.material.color.setRGB(color.r, color.g, color.b);
        return true;
    }

    /**
     * Batch update colors from an executed plan's actions.
     * @param {Array} actions - Plan actions array
     */
    applyPlanColors(actions) {
        if (!actions) return;
        let updated = 0;
        for (const a of actions) {
            if (a.type === 'apply_material' && a.target && a.color) {
                if (this.updateObjectColor(a.target, a.color)) updated++;
            }
        }
        return updated;
    }

    // ── Selection ──────────────────────────────────────────

    selectObject(uid) {
        if (this.selectionOutline) {
            this.scene.remove(this.selectionOutline);
            this.selectionOutline.geometry.dispose();
            this.selectionOutline = null;
        }

        // Look up by uid (path) first, fallback to name search, then tile group
        let mesh = this.meshMap.get(uid);
        if (!mesh) {
            for (const m of this.meshMap.values()) {
                if (m.userData.objectName === uid) { mesh = m; break; }
            }
        }
        if (!mesh && this._tileGroup) {
            this._tileGroup.traverse(c => {
                if (!mesh && c.isMesh && (c.userData.objectUid === uid || c.userData.objectName === uid)) {
                    mesh = c;
                }
            });
        }
        if (!mesh) return;
        this.selectedMesh = mesh;

        const outGeo = mesh.geometry.clone();
        this.selectionOutline = new THREE.Mesh(outGeo, this.outlineMat);

        // For tile meshes (nested under parent groups), use world matrix
        if (mesh.userData.isTileMesh) {
            mesh.updateWorldMatrix(true, false);
            this.selectionOutline.applyMatrix4(mesh.matrixWorld);
            this.selectionOutline.scale.multiplyScalar(1.06);
        } else {
            this.selectionOutline.position.copy(mesh.position);
            this.selectionOutline.rotation.copy(mesh.rotation);
            this.selectionOutline.scale.copy(mesh.scale).multiplyScalar(1.06);
        }
        this.scene.add(this.selectionOutline);

        // Gentle focus shift — only nudge orbit target toward selected object
        const worldPos = new THREE.Vector3();
        mesh.getWorldPosition(worldPos);
        this.controls.target.lerp(worldPos, 0.15);

        // In move mode, attach transform gizmo to selected object
        if (this._moveMode) {
            this.transformControls.attach(mesh);
            this.transformControls.visible = true;
            this.transformControls.enabled = true;
        }
    }

    _handlePointerDown(event) {
        this._pointerDownPos = { x: event.clientX, y: event.clientY };
    }

    _handleClick(event) {
        if (!this.renderer || !this.camera) return;

        // Drag detection: ignore click if mouse moved more than 5px (was a rotate/pan drag)
        if (this._pointerDownPos) {
            const dx = event.clientX - this._pointerDownPos.x;
            const dy = event.clientY - this._pointerDownPos.y;
            if (dx * dx + dy * dy > 25) return; // 5px threshold squared
        }

        // Don't process clicks on the transform gizmo itself
        if (this.transformControls && this.transformControls.dragging) return;

        const rect = this.renderer.domElement.getBoundingClientRect();
        this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.pointer, this.camera);

        // Measurement mode — click on tile mesh or any object to get 3D point
        if (this._measureMode) {
            const allTargets = [];
            if (this._tileGroup) this._tileGroup.traverse(c => { if (c.isMesh) allTargets.push(c); });
            this.meshMap.forEach(m => allTargets.push(m));
            const hits = this.raycaster.intersectObjects(allTargets);
            if (hits.length > 0) {
                this._addMeasurePoint(hits[0].point.clone());
            }
            return;
        }

        // NavMesh mode — click on tile/ground to get a point
        if (this.onNavClick) {
            const allTargets = [];
            if (this._tileGroup) this._tileGroup.traverse(c => { if (c.isMesh) allTargets.push(c); });
            this.meshMap.forEach(m => allTargets.push(m));
            const hits = this.raycaster.intersectObjects(allTargets);
            if (hits.length > 0) {
                const pt = hits[0].point;
                // Convert to world XZ (negate Z for OBJ coords)
                this.onNavClick({ x: pt.x, z: -pt.z });
            }
            return;
        }

        // Check tile meshes for building footprint click
        if (this._tileGroup && this._buildingFootprints.length > 0) {
            const tileTargets = [];
            this._tileGroup.traverse(c => { if (c.isMesh) tileTargets.push(c); });
            const tileHits = this.raycaster.intersectObjects(tileTargets);
            if (tileHits.length > 0) {
                const pt = tileHits[0].point;
                const bldg = this._findBuildingAtPoint(pt.x, pt.z);
                if (bldg && this.onBuildingClick) {
                    this.onBuildingClick(bldg.id);
                    this._highlightFootprint(bldg.id);
                    return;
                }
            }
        }

        // Collect all selectable meshes: meshMap objects + tile group meshes
        const selectables = Array.from(this.meshMap.values());
        if (this._tileGroup) {
            this._tileGroup.traverse(c => {
                if (c.isMesh && c.userData.objectName) selectables.push(c);
            });
        }
        const intersects = this.raycaster.intersectObjects(selectables);

        if (intersects.length > 0) {
            const hit = intersects[0].object;
            const uid = hit.userData.objectUid || hit.userData.objectName;
            const name = hit.userData.objectName;
            if (uid) {
                this.selectObject(uid);
                if (this.onSelect) this.onSelect(name, uid);
            }
        } else if (this._moveMode) {
            // Clicking empty space in move mode — deselect
            this.transformControls.detach();
            this.transformControls.visible = false;
        }
    }

    // ── Camera fit ─────────────────────────────────────────

    _fitCamera() {
        if (this.meshMap.size === 0) return;
        const box = new THREE.Box3();
        for (const mesh of this.meshMap.values()) box.expandByObject(mesh);

        const center = new THREE.Vector3();
        box.getCenter(center);
        const size = new THREE.Vector3();
        box.getSize(size);

        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = this.camera.fov * (Math.PI / 180);
        let dist = (maxDim / 2) / Math.tan(fov / 2);
        dist = Math.max(dist * 1.5, 5);

        this.camera.position.set(
            center.x + dist * 0.6,
            center.y + dist * 0.5,
            center.z + dist * 0.6,
        );
        this.controls.target.copy(center);
    }

    // ── OBJ Tile Loading ─────────────────────────────────────

    /**
     * Load OBJ city tiles into the scene.
     * @param {Array} tiles - Array of tile info from /api/drone/citytiles
     */
    async loadOBJTiles(tiles) {
        // Remove existing tile group
        if (this._tileGroup) {
            this._tileGroup.traverse(child => {
                if (child.geometry) child.geometry.dispose();
                if (child.material) {
                    if (Array.isArray(child.material)) {
                        child.material.forEach(m => m.dispose());
                    } else {
                        child.material.dispose();
                    }
                }
            });
            this.scene.remove(this._tileGroup);
        }

        this._tileGroup = new THREE.Group();
        this._tileGroup.name = 'CityTiles';
        this.scene.add(this._tileGroup);

        // Adjust scene for large city tiles
        this.camera.far = 5000;
        this.camera.near = 0.5;
        this.camera.updateProjectionMatrix();
        this.controls.maxDistance = 3000;
        if (this.scene.fog) this.scene.fog.density = 0.0005;

        // Remove grid for city view (too small)
        this.scene.traverse(obj => {
            if (obj.isGridHelper) obj.visible = false;
        });

        // Add stronger lighting for photogrammetry
        const sunLight = new THREE.DirectionalLight(0xffffff, 2.5);
        sunLight.position.set(100, 200, 100);
        sunLight.name = '_tileSunLight';
        this._tileGroup.add(sunLight);

        const sunLight2 = new THREE.DirectionalLight(0xffffff, 1.0);
        sunLight2.position.set(-80, 150, -60);
        sunLight2.name = '_tileSunLight2';
        this._tileGroup.add(sunLight2);

        const fillLight = new THREE.AmbientLight(0xffffff, 1.2);
        fillLight.name = '_tileFillLight';
        this._tileGroup.add(fillLight);

        this._tileLoadProgress = { loaded: 0, total: tiles.length };

        const mtlLoader = new MTLLoader();
        const objLoader = new OBJLoader();

        for (const tile of tiles) {
            try {
                let materials = null;
                const baseUrl = tile.obj_url.substring(0, tile.obj_url.lastIndexOf('/') + 1);

                // Load MTL if available
                if (tile.mtl_url) {
                    try {
                        const mtlText = await fetch(tile.mtl_url).then(r => r.text());
                        materials = mtlLoader.parse(mtlText, baseUrl);
                        materials.preload();
                    } catch (e) {
                        console.warn(`[SceneViewer] MTL load failed for ${tile.name}:`, e);
                    }
                }

                // Load OBJ
                if (materials) {
                    objLoader.setMaterials(materials);
                }

                const objText = await fetch(tile.obj_url).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.text();
                });

                const obj = objLoader.parse(objText);
                obj.name = tile.name;

                // Coordinate system: OBJ files are in Unity LH coords
                // Three.js is RH — negate Z
                obj.scale.set(1, 1, -1);

                // Apply default material if MTL failed
                if (!materials) {
                    obj.traverse(child => {
                        if (child.isMesh) {
                            child.material = new THREE.MeshStandardMaterial({
                                color: 0x888888,
                                roughness: 0.8,
                                metalness: 0.1,
                                side: THREE.DoubleSide,
                            });
                        }
                    });
                }

                // Enable shadows + set userData for selection
                obj.traverse(child => {
                    if (child.isMesh) {
                        child.castShadow = true;
                        child.receiveShadow = true;
                        child.userData.objectName = tile.name;
                        child.userData.objectUid = `CityTiles_Root/${tile.name}/default`;
                        child.userData.objectPath = `CityTiles_Root/${tile.name}`;
                        child.userData.isTileMesh = true;
                    }
                });

                this._tileGroup.add(obj);

                this._tileLoadProgress.loaded++;
                if (this.onTileProgress) {
                    this.onTileProgress(this._tileLoadProgress.loaded, this._tileLoadProgress.total);
                }

                console.log(`[SceneViewer] Loaded tile: ${tile.name} (${this._tileLoadProgress.loaded}/${this._tileLoadProgress.total})`);
            } catch (e) {
                console.error(`[SceneViewer] Failed to load tile ${tile.name}:`, e);
                this._tileLoadProgress.loaded++;
            }
        }

        // Fit camera to tile bounds
        this._fitCameraToTiles();

        return this._tileLoadProgress;
    }

    /**
     * Fit camera to show all loaded tiles.
     */
    _fitCameraToTiles() {
        if (!this._tileGroup || this._tileGroup.children.length === 0) return;

        const box = new THREE.Box3();
        this._tileGroup.traverse(child => {
            if (child.isMesh) box.expandByObject(child);
        });

        if (box.isEmpty()) return;

        const center = new THREE.Vector3();
        box.getCenter(center);
        const size = new THREE.Vector3();
        box.getSize(size);

        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = this.camera.fov * (Math.PI / 180);
        let dist = (maxDim / 2) / Math.tan(fov / 2);
        dist = Math.max(dist * 0.8, 50);

        this.camera.position.set(
            center.x + dist * 0.4,
            center.y + dist * 0.3,
            center.z + dist * 0.5,
        );
        this.controls.target.copy(center);
        this.controls.update();

        console.log(`[SceneViewer] Tiles bounds: center=(${center.x.toFixed(0)}, ${center.y.toFixed(0)}, ${center.z.toFixed(0)}) size=(${size.x.toFixed(0)}x${size.y.toFixed(0)}x${size.z.toFixed(0)})`);
    }

    /**
     * Toggle tile visibility.
     */
    setTilesVisible(visible) {
        if (this._tileGroup) this._tileGroup.visible = visible;
    }

    get tilesLoaded() {
        return this._tileGroup && this._tileGroup.children.length > 3; // >3 because of lights
    }

    // ── LOD Progressive Tile Loading ─────────────────────────

    /**
     * Load city tiles with LOD support (progressive loading).
     * Phase 1: Load all LOD2 (lightweight) for fast initial view.
     * Phase 2: Upgrade camera-nearby tiles to LOD0 in background.
     * @param {Array} tiles - LOD metadata from /api/drone/citytiles-lod
     */
    async loadOBJTilesWithLOD(tiles) {
        // Reuse scene setup from loadOBJTiles
        this._prepareTileScene(tiles.length);

        const mtlLoader = new MTLLoader();
        const objLoader = new OBJLoader();

        // ── Phase 1: Load all LOD2 (fast overview) ──
        console.log('[SceneViewer] Phase 1: Loading LOD2 for all tiles...');
        this._tileLoadProgress = { loaded: 0, total: tiles.length, phase: 'lod2' };

        for (const tile of tiles) {
            try {
                const levels = tile.lod_levels || {};
                const lod2Info = levels.lod2 || levels.lod1 || levels.lod0;
                if (!lod2Info) continue;

                // Load MTL for textures
                let materials = null;
                if (tile.mtl_url) {
                    try {
                        const baseUrl = (levels.lod0?.url || '').substring(0, (levels.lod0?.url || '').lastIndexOf('/') + 1);
                        const mtlText = await fetch(tile.mtl_url).then(r => r.text());
                        materials = mtlLoader.parse(mtlText, baseUrl);
                        materials.preload();
                    } catch (e) {
                        // MTL optional
                    }
                }

                const lod2Obj = await this._loadOBJFromUrl(objLoader, lod2Info.url, tile.name, materials);
                if (!lod2Obj) continue;

                // Create THREE.LOD container
                const lodContainer = new THREE.LOD();
                lodContainer.name = tile.name;

                // LOD2 at distance 0 (only level so far)
                lodContainer.addLevel(lod2Obj, 0);

                this._tileGroup.add(lodContainer);
                this._lodTiles.set(tile.name, {
                    lod: lodContainer,
                    levels: { lod2: lod2Obj },
                    meta: tile,
                    materials: materials,
                });

                this._tileLoadProgress.loaded++;
                if (this.onTileProgress) {
                    this.onTileProgress(this._tileLoadProgress.loaded, this._tileLoadProgress.total);
                }
            } catch (e) {
                console.error(`[SceneViewer] LOD2 load failed for ${tile.name}:`, e);
                this._tileLoadProgress.loaded++;
            }
        }

        // Fit camera after Phase 1
        this._fitCameraToTiles();
        console.log(`[SceneViewer] Phase 1 complete: ${this._lodTiles.size} tiles loaded (LOD2)`);

        // ── Phase 2: Background upgrade nearby tiles to LOD0 ──
        this._startLODUpgradeLoop(objLoader);

        return this._tileLoadProgress;
    }

    /**
     * Shared scene setup for tile loading.
     */
    _prepareTileScene(tileCount) {
        // Remove existing tile group
        if (this._tileGroup) {
            this._tileGroup.traverse(child => {
                if (child.geometry) child.geometry.dispose();
                if (child.material) {
                    if (Array.isArray(child.material)) {
                        child.material.forEach(m => m.dispose());
                    } else if (child.material.dispose) {
                        child.material.dispose();
                    }
                }
            });
            this.scene.remove(this._tileGroup);
        }
        this._lodTiles.clear();

        this._tileGroup = new THREE.Group();
        this._tileGroup.name = 'CityTiles';
        this.scene.add(this._tileGroup);

        // Adjust scene for large city tiles
        this.camera.far = 5000;
        this.camera.near = 0.5;
        this.camera.updateProjectionMatrix();
        this.controls.maxDistance = 3000;
        if (this.scene.fog) this.scene.fog.density = 0.0005;

        // Remove grid for city view
        this.scene.traverse(obj => {
            if (obj.isGridHelper) obj.visible = false;
        });

        // Add stronger lighting for photogrammetry
        const sunLight = new THREE.DirectionalLight(0xffffff, 2.5);
        sunLight.position.set(100, 200, 100);
        sunLight.name = '_tileSunLight';
        this._tileGroup.add(sunLight);

        const sunLight2 = new THREE.DirectionalLight(0xffffff, 1.0);
        sunLight2.position.set(-80, 150, -60);
        sunLight2.name = '_tileSunLight2';
        this._tileGroup.add(sunLight2);

        const fillLight = new THREE.AmbientLight(0xffffff, 1.2);
        fillLight.name = '_tileFillLight';
        this._tileGroup.add(fillLight);
    }

    /**
     * Load an OBJ from URL, apply materials, configure for scene.
     * Returns the parsed Object3D or null on failure.
     */
    async _loadOBJFromUrl(objLoader, url, name, materials) {
        try {
            if (materials) objLoader.setMaterials(materials);

            const objText = await fetch(url).then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.text();
            });

            const obj = objLoader.parse(objText);
            obj.name = name;
            obj.scale.set(1, 1, -1); // Unity LH → Three.js RH

            if (!materials) {
                obj.traverse(child => {
                    if (child.isMesh) {
                        child.material = new THREE.MeshStandardMaterial({
                            color: 0x888888, roughness: 0.8, metalness: 0.1,
                            side: THREE.DoubleSide,
                        });
                    }
                });
            }

            obj.traverse(child => {
                if (child.isMesh) {
                    child.castShadow = true;
                    child.receiveShadow = true;
                    child.userData.objectName = name;
                    child.userData.objectUid = `CityTiles_Root/${name}/default`;
                    child.userData.objectPath = `CityTiles_Root/${name}`;
                    child.userData.isTileMesh = true;
                }
            });

            return obj;
        } catch (e) {
            console.error(`[SceneViewer] OBJ load failed: ${url}`, e);
            return null;
        }
    }

    /**
     * Background loop: upgrade nearby tiles to LOD0, dispose far LOD0.
     */
    _startLODUpgradeLoop(objLoader) {
        if (this._lodMemoryTimer) clearInterval(this._lodMemoryTimer);

        const LOD0_LOAD_DIST = 300;   // Load LOD0 when camera closer than this
        const LOD0_UNLOAD_DIST = 600; // Dispose LOD0 geometry when camera farther

        this._lodMemoryTimer = setInterval(async () => {
            if (!this.camera || !this._tileGroup) return;

            const camPos = this.camera.position;

            for (const [name, entry] of this._lodTiles) {
                const lodContainer = entry.lod;
                if (!lodContainer.parent) continue; // removed from scene

                // Compute distance from camera to tile center
                const box = new THREE.Box3().setFromObject(lodContainer);
                const center = new THREE.Vector3();
                box.getCenter(center);
                const dist = camPos.distanceTo(center);

                // Upgrade: load LOD0 for nearby tiles
                if (dist < LOD0_LOAD_DIST && !entry.levels.lod0 && entry.meta.lod_levels.lod0) {
                    console.log(`[SceneViewer] Upgrading ${name} to LOD0...`);
                    const lod0Obj = await this._loadOBJFromUrl(
                        objLoader,
                        entry.meta.lod_levels.lod0.url,
                        `${name}_LOD0`,
                        entry.materials
                    );
                    if (lod0Obj) {
                        // THREE.LOD: lower distance = higher detail
                        // Re-add levels: LOD0 at distance 0, LOD2 at distance 200
                        lodContainer.levels.length = 0; // clear
                        lodContainer.addLevel(lod0Obj, 0);
                        if (entry.levels.lod2) lodContainer.addLevel(entry.levels.lod2, 200);
                        entry.levels.lod0 = lod0Obj;
                        console.log(`[SceneViewer] ${name} upgraded to LOD0`);
                    }
                    break; // One upgrade per interval to avoid stalling
                }

                // Downgrade: dispose LOD0 geometry for far tiles
                if (dist > LOD0_UNLOAD_DIST && entry.levels.lod0) {
                    console.log(`[SceneViewer] Disposing LOD0 for ${name} (dist=${dist.toFixed(0)})`);
                    entry.levels.lod0.traverse(child => {
                        if (child.geometry) child.geometry.dispose();
                    });
                    lodContainer.remove(entry.levels.lod0);
                    entry.levels.lod0 = null;

                    // Re-set LOD2 as the only level
                    lodContainer.levels.length = 0;
                    if (entry.levels.lod2) lodContainer.addLevel(entry.levels.lod2, 0);
                }
            }
        }, 2000); // Check every 2 seconds
    }

    /**
     * Stop LOD background management.
     */
    _stopLODUpgradeLoop() {
        if (this._lodMemoryTimer) {
            clearInterval(this._lodMemoryTimer);
            this._lodMemoryTimer = null;
        }
    }

    // ── GeoBIM: Footprint Overlay ────────────────────────────

    loadFootprints(footprints) {
        this._buildingFootprints = footprints;
        if (this._footprintGroup) {
            this.scene.remove(this._footprintGroup);
            this._footprintGroup.traverse(c => { if (c.geometry) c.geometry.dispose(); });
        }
        this._footprintGroup = new THREE.Group();
        this._footprintGroup.name = '__geobim_footprints';

        const mat = new THREE.LineBasicMaterial({ color: 0x00ffcc, linewidth: 2, transparent: true, opacity: 0.8 });

        for (const fp of footprints) {
            if (!fp.footprint || fp.footprint.length < 3) continue;
            const pts = fp.footprint.map(p => new THREE.Vector3(p[0], 0.5, -p[1])); // Y-up, negate Z
            pts.push(pts[0]); // close loop
            const geo = new THREE.BufferGeometry().setFromPoints(pts);
            const line = new THREE.Line(geo, mat.clone());
            line.userData.buildingId = fp.id;
            line.userData.label = fp.label;
            this._footprintGroup.add(line);
        }

        this.scene.add(this._footprintGroup);
        console.log(`[SceneViewer] Loaded ${footprints.length} building footprints`);
    }

    _findBuildingAtPoint(x, z) {
        // z is in Three.js coords (negated from OBJ), convert back for footprint test
        const testZ = -z;
        for (const fp of this._buildingFootprints) {
            if (!fp.footprint || fp.footprint.length < 3) continue;
            if (this._pointInPolygon(x, testZ, fp.footprint)) return fp;
        }
        return null;
    }

    _pointInPolygon(x, z, polygon) {
        let inside = false;
        for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
            const xi = polygon[i][0], zi = polygon[i][1];
            const xj = polygon[j][0], zj = polygon[j][1];
            const intersect = ((zi > z) !== (zj > z)) && (x < (xj - xi) * (z - zi) / (zj - zi) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    }

    _highlightFootprint(buildingId) {
        if (!this._footprintGroup) return;
        this._footprintGroup.children.forEach(line => {
            const isTarget = line.userData.buildingId === buildingId;
            line.material.color.setHex(isTarget ? 0xffbe44 : 0x00ffcc);
            line.material.opacity = isTarget ? 1.0 : 0.8;
        });
    }

    // ── BBox Wireframe Highlight (Section 4.4/4.5) ─────────

    highlightBuildingBBox(building) {
        this.clearBuildingBBox();
        if (!building || !building.bbox_min || !building.bbox_max) return;

        this._bboxGroup = new THREE.Group();
        this._bboxGroup.name = '__building_bbox';

        const bmin = building.bbox_min;
        const bmax = building.bbox_max;

        // Create wireframe box from bbox_aabb (Unity coords → Three.js: negate Z)
        const boxGeo = new THREE.BoxGeometry(
            bmax[0] - bmin[0],
            bmax[1] - bmin[1],
            bmax[2] - bmin[2]
        );
        const edges = new THREE.EdgesGeometry(boxGeo);
        const lineMat = new THREE.LineBasicMaterial({
            color: 0xffbe44, linewidth: 2, transparent: true, opacity: 0.9,
        });
        const wireframe = new THREE.LineSegments(edges, lineMat);
        wireframe.position.set(
            (bmin[0] + bmax[0]) / 2,
            (bmin[1] + bmax[1]) / 2,
            -((bmin[2] + bmax[2]) / 2)  // negate Z
        );
        this._bboxGroup.add(wireframe);

        // Height label at top center
        const heightMax = building.height_max || building.height || 0;
        const topY = bmax[1];
        const labelPos = new THREE.Vector3(
            (bmin[0] + bmax[0]) / 2,
            topY + 1.5,
            -((bmin[2] + bmax[2]) / 2)
        );
        const labelText = `${building.label || 'Building'}\n${heightMax.toFixed(1)}m`;
        this._addBBoxLabel(labelPos, labelText);

        // Semi-transparent fill for top face
        const topGeo = new THREE.PlaneGeometry(bmax[0] - bmin[0], bmax[2] - bmin[2]);
        topGeo.rotateX(-Math.PI / 2);
        const topMat = new THREE.MeshBasicMaterial({
            color: 0xffbe44, transparent: true, opacity: 0.15, side: THREE.DoubleSide,
        });
        const topMesh = new THREE.Mesh(topGeo, topMat);
        topMesh.position.set(
            (bmin[0] + bmax[0]) / 2,
            topY,
            -((bmin[2] + bmax[2]) / 2)
        );
        this._bboxGroup.add(topMesh);

        this.scene.add(this._bboxGroup);
    }

    _addBBoxLabel(position, text) {
        const canvas = document.createElement('canvas');
        canvas.width = 256; canvas.height = 96;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = 'rgba(0,0,0,0.8)';
        ctx.roundRect(4, 4, 248, 88, 8);
        ctx.fill();
        ctx.strokeStyle = '#ffbe44';
        ctx.lineWidth = 2;
        ctx.roundRect(4, 4, 248, 88, 8);
        ctx.stroke();
        ctx.fillStyle = '#ffbe44';
        ctx.font = 'bold 22px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const lines = text.split('\n');
        lines.forEach((line, i) => {
            ctx.fillText(line, 128, 30 + i * 32);
        });

        const texture = new THREE.CanvasTexture(canvas);
        const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true });
        const sprite = new THREE.Sprite(spriteMat);
        sprite.position.copy(position);
        sprite.scale.set(5, 2, 1);
        this._bboxGroup.add(sprite);
    }

    clearBuildingBBox() {
        if (this._bboxGroup) {
            this.scene.remove(this._bboxGroup);
            this._bboxGroup.traverse(c => {
                if (c.geometry) c.geometry.dispose();
                if (c.material) {
                    if (c.material.map) c.material.map.dispose();
                    c.material.dispose();
                }
            });
            this._bboxGroup = null;
        }
    }

    clearFootprints() {
        if (this._footprintGroup) {
            this.scene.remove(this._footprintGroup);
            this._footprintGroup.traverse(c => { if (c.geometry) c.geometry.dispose(); });
            this._footprintGroup = null;
        }
        this._buildingFootprints = [];
    }

    setFootprintsVisible(visible) {
        if (this._footprintGroup) this._footprintGroup.visible = visible;
    }

    // ── Measurement Mode ──────────────────────────────────────

    setMeasureMode(mode) {
        this._measureMode = mode; // 'distance' | 'height' | 'area' | null
        this._measurePoints = [];
        if (mode) {
            this.renderer.domElement.style.cursor = 'crosshair';
        } else {
            this.renderer.domElement.style.cursor = this._moveMode ? 'crosshair' : 'grab';
        }
    }

    _addMeasurePoint(point) {
        this._measurePoints.push(point);
        this._drawMeasureMarker(point);

        const mode = this._measureMode;
        if (mode === 'distance' && this._measurePoints.length === 2) {
            this._completeMeasureDistance();
        } else if (mode === 'height' && this._measurePoints.length === 1) {
            this._completeMeasureHeight();
        } else if (mode === 'area' && this._measurePoints.length >= 3) {
            // Area: double-click or 6 points to close
            if (this._measurePoints.length >= 6) {
                this._completeMeasureArea();
            }
        }
    }

    completeMeasureArea() {
        if (this._measureMode === 'area' && this._measurePoints.length >= 3) {
            this._completeMeasureArea();
        }
    }

    _drawMeasureMarker(point) {
        if (!this._measureGroup) {
            this._measureGroup = new THREE.Group();
            this._measureGroup.name = '__measure_overlay';
            this.scene.add(this._measureGroup);
        }
        const geo = new THREE.SphereGeometry(0.3, 8, 8);
        const mat = new THREE.MeshBasicMaterial({ color: 0xff4444 });
        const sphere = new THREE.Mesh(geo, mat);
        sphere.position.copy(point);
        this._measureGroup.add(sphere);
    }

    _completeMeasureDistance() {
        const [a, b] = this._measurePoints;
        const dist = a.distanceTo(b);
        this._drawMeasureLine(a, b, `${dist.toFixed(2)}m`);
        if (this.onMeasure) this.onMeasure('distance', { distance: dist, points: [a, b] });
        this._measurePoints = [];
    }

    _completeMeasureHeight() {
        const p = this._measurePoints[0];
        // Height from ground (Y=0) to point
        const groundPt = new THREE.Vector3(p.x, 0, p.z);
        const height = Math.abs(p.y);
        this._drawMeasureLine(groundPt, p, `${height.toFixed(2)}m`);
        if (this.onMeasure) this.onMeasure('height', { height, point: p });
        this._measurePoints = [];
    }

    _completeMeasureArea() {
        const pts = this._measurePoints;
        // Calculate area using shoelace formula on XZ plane
        let area = 0;
        for (let i = 0; i < pts.length; i++) {
            const j = (i + 1) % pts.length;
            area += pts[i].x * pts[j].z;
            area -= pts[j].x * pts[i].z;
        }
        area = Math.abs(area) / 2;

        // Draw polygon outline
        const linePts = pts.map(p => p.clone());
        linePts.push(pts[0].clone());
        const geo = new THREE.BufferGeometry().setFromPoints(linePts);
        const mat = new THREE.LineBasicMaterial({ color: 0x00ff88, linewidth: 2 });
        const line = new THREE.Line(geo, mat);
        this._measureGroup.add(line);

        // Label at centroid
        const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
        const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
        const cz = pts.reduce((s, p) => s + p.z, 0) / pts.length;
        this._addMeasureLabel(new THREE.Vector3(cx, cy + 1, cz), `${area.toFixed(2)}m²`);

        if (this.onMeasure) this.onMeasure('area', { area, points: pts });
        this._measurePoints = [];
        this._measureMode = null;
    }

    _drawMeasureLine(a, b, label) {
        if (!this._measureGroup) {
            this._measureGroup = new THREE.Group();
            this._measureGroup.name = '__measure_overlay';
            this.scene.add(this._measureGroup);
        }
        const geo = new THREE.BufferGeometry().setFromPoints([a, b]);
        const mat = new THREE.LineBasicMaterial({ color: 0xff6600, linewidth: 2 });
        const line = new THREE.Line(geo, mat);
        this._measureGroup.add(line);

        const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
        mid.y += 0.5;
        this._addMeasureLabel(mid, label);
    }

    _addMeasureLabel(position, text) {
        // Use a sprite with canvas-rendered text
        const canvas = document.createElement('canvas');
        canvas.width = 256; canvas.height = 64;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = 'rgba(0,0,0,0.7)';
        ctx.roundRect(0, 0, 256, 64, 8);
        ctx.fill();
        ctx.fillStyle = '#00ffcc';
        ctx.font = 'bold 28px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, 128, 32);

        const texture = new THREE.CanvasTexture(canvas);
        const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true });
        const sprite = new THREE.Sprite(spriteMat);
        sprite.position.copy(position);
        sprite.scale.set(4, 1, 1);
        this._measureGroup.add(sprite);
    }

    clearMeasurements() {
        if (this._measureGroup) {
            this.scene.remove(this._measureGroup);
            this._measureGroup.traverse(c => {
                if (c.geometry) c.geometry.dispose();
                if (c.material) {
                    if (c.material.map) c.material.map.dispose();
                    c.material.dispose();
                }
            });
            this._measureGroup = null;
        }
        this._measurePoints = [];
        this._measureResults = [];
    }

    // ── NavMesh Path Visualization (Section 4.7) ───────────

    renderNavPath(pathPoints, color = 0x00ff88) {
        this.clearNavPath();
        if (!pathPoints || pathPoints.length < 2) return;

        this._navGroup = new THREE.Group();
        this._navGroup.name = '__nav_path';

        // Convert [x,z] path to 3D points (Y slightly above ground)
        const pts3d = pathPoints.map(p => new THREE.Vector3(p[0], 0.6, -p[1]));

        // Tube-like path using cylinder segments
        for (let i = 0; i < pts3d.length - 1; i++) {
            const a = pts3d[i], b = pts3d[i + 1];
            const dir = new THREE.Vector3().subVectors(b, a);
            const len = dir.length();
            if (len < 0.01) continue;

            const geo = new THREE.CylinderGeometry(0.15, 0.15, len, 6);
            geo.rotateX(Math.PI / 2);
            const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.8 });
            const cyl = new THREE.Mesh(geo, mat);
            cyl.position.copy(a).add(b).multiplyScalar(0.5);
            cyl.lookAt(b);
            this._navGroup.add(cyl);
        }

        // Start marker (green sphere)
        const startGeo = new THREE.SphereGeometry(0.5, 12, 12);
        const startMat = new THREE.MeshBasicMaterial({ color: 0x44ff44 });
        const startMesh = new THREE.Mesh(startGeo, startMat);
        startMesh.position.copy(pts3d[0]);
        this._navGroup.add(startMesh);

        // End marker (red sphere)
        const endGeo = new THREE.SphereGeometry(0.5, 12, 12);
        const endMat = new THREE.MeshBasicMaterial({ color: 0xff4444 });
        const endMesh = new THREE.Mesh(endGeo, endMat);
        endMesh.position.copy(pts3d[pts3d.length - 1]);
        this._navGroup.add(endMesh);

        // Distance label at midpoint
        const midIdx = Math.floor(pts3d.length / 2);
        let totalDist = 0;
        for (let i = 1; i < pts3d.length; i++) totalDist += pts3d[i].distanceTo(pts3d[i - 1]);
        const midPos = pts3d[midIdx].clone();
        midPos.y += 2;
        this._addMeasureLabel(midPos, `${totalDist.toFixed(1)}m`);

        this.scene.add(this._navGroup);
    }

    clearNavPath() {
        if (this._navGroup) {
            this.scene.remove(this._navGroup);
            this._navGroup.traverse(c => {
                if (c.geometry) c.geometry.dispose();
                if (c.material) {
                    if (c.material.map) c.material.map.dispose();
                    c.material.dispose();
                }
            });
            this._navGroup = null;
        }
    }

    // ── Visibility Heatmap (Section 4.8) ─────────────────

    renderVisibilityHeatmap(heatmapData, gridRes = 2.0) {
        this.clearVisibilityHeatmap();
        if (!heatmapData || heatmapData.length === 0) return;

        this._visGroup = new THREE.Group();
        this._visGroup.name = '__visibility_heatmap';

        const cellSize = gridRes * 0.9; // slight gap between cells
        const geo = new THREE.PlaneGeometry(cellSize, cellSize);
        geo.rotateX(-Math.PI / 2); // face up

        // Find max hit count for normalization
        const maxHits = Math.max(1, ...heatmapData.map(c => c.hit_count || 0));

        for (const cell of heatmapData) {
            let color, opacity;
            if (cell.visible) {
                // Green gradient based on hit count
                const t = (cell.hit_count || 1) / maxHits;
                color = new THREE.Color().setHSL(0.33 * t, 0.9, 0.5);
                opacity = 0.3 + 0.3 * t;
            } else {
                // Red for blind spots
                color = new THREE.Color(0xff2222);
                opacity = 0.25;
            }

            const mat = new THREE.MeshBasicMaterial({
                color, transparent: true, opacity, side: THREE.DoubleSide,
            });
            const mesh = new THREE.Mesh(geo.clone(), mat);
            mesh.position.set(cell.x, 0.2, -cell.z); // Y-up, negate Z
            this._visGroup.add(mesh);
        }

        this.scene.add(this._visGroup);
        console.log(`[SceneViewer] Visibility heatmap: ${heatmapData.length} cells`);
    }

    renderSensorMarkers(sensors) {
        if (!this._visGroup) {
            this._visGroup = new THREE.Group();
            this._visGroup.name = '__visibility_heatmap';
            this.scene.add(this._visGroup);
        }
        for (const s of sensors) {
            const pos = s.position || [0, 3, 0];
            const geo = new THREE.ConeGeometry(0.8, 1.5, 8);
            const mat = new THREE.MeshBasicMaterial({ color: 0xffaa00 });
            const cone = new THREE.Mesh(geo, mat);
            cone.position.set(pos[0], pos[1] + 0.75, -(pos[2] || 0));
            this._visGroup.add(cone);

            // FOV arc indicator
            const maxDist = s.max_distance || 100;
            const hfov = (s.hfov || 360) * Math.PI / 180;
            const arcGeo = new THREE.RingGeometry(maxDist * 0.1, maxDist, 32, 1, 0, hfov);
            arcGeo.rotateX(-Math.PI / 2);
            const arcMat = new THREE.MeshBasicMaterial({
                color: 0xffaa00, transparent: true, opacity: 0.15, side: THREE.DoubleSide
            });
            const arc = new THREE.Mesh(arcGeo, arcMat);
            arc.position.set(pos[0], 0.3, -(pos[2] || 0));
            const yawRad = (s.yaw || 0) * Math.PI / 180;
            arc.rotation.y = -yawRad + Math.PI / 2 - hfov / 2;
            this._visGroup.add(arc);
        }
    }

    clearVisibilityHeatmap() {
        if (this._visGroup) {
            this.scene.remove(this._visGroup);
            this._visGroup.traverse(c => {
                if (c.geometry) c.geometry.dispose();
                if (c.material) c.material.dispose();
            });
            this._visGroup = null;
        }
    }

    // ── Accessibility Heatmap (Section 4.7) ──────────────

    renderAccessibilityHeatmap(cells, gridRes = 1.0, maxTime = 300) {
        this.clearVisibilityHeatmap(); // reuse vis group
        if (!cells || cells.length === 0) return;

        this._visGroup = new THREE.Group();
        this._visGroup.name = '__accessibility_heatmap';

        const cellSize = gridRes * 0.9;
        const geo = new THREE.PlaneGeometry(cellSize, cellSize);
        geo.rotateX(-Math.PI / 2);

        for (const cell of cells) {
            // Color gradient: green (close) → yellow → red (far)
            const t = Math.min(cell.time_s / maxTime, 1.0);
            const color = new THREE.Color().setHSL(0.33 * (1 - t), 0.9, 0.45);
            const opacity = 0.2 + 0.3 * (1 - t);

            const mat = new THREE.MeshBasicMaterial({
                color, transparent: true, opacity, side: THREE.DoubleSide,
            });
            const mesh = new THREE.Mesh(geo.clone(), mat);
            mesh.position.set(cell.x, 0.15, -cell.z);
            this._visGroup.add(mesh);
        }

        // Start point marker
        if (cells.length > 0) {
            const start = cells.find(c => c.distance === 0) || cells[0];
            const sGeo = new THREE.SphereGeometry(0.6, 12, 12);
            const sMat = new THREE.MeshBasicMaterial({ color: 0x44ff44 });
            const sMesh = new THREE.Mesh(sGeo, sMat);
            sMesh.position.set(start.x, 1, -start.z);
            this._visGroup.add(sMesh);
        }

        this.scene.add(this._visGroup);
        console.log(`[SceneViewer] Accessibility heatmap: ${cells.length} reachable cells`);
    }

    // ── Floating Origin (Section 4.3) ────────────────────

    _checkFloatingOrigin() {
        if (!this.camera || !this._tileGroup) return;
        const cx = this.camera.position.x;
        const cz = this.camera.position.z;
        const dist = Math.sqrt(cx * cx + cz * cz);

        if (dist > this._floatingOriginThreshold) {
            const dx = -cx;
            const dz = -cz;
            // Shift all scene root children
            this.scene.children.forEach(child => {
                if (child.isCamera || child === this.transformControls) return;
                child.position.x += dx;
                child.position.z += dz;
            });
            // Shift camera + controls target
            this.camera.position.x += dx;
            this.camera.position.z += dz;
            this.controls.target.x += dx;
            this.controls.target.z += dz;
            // Track cumulative offset for coordinate conversion
            this._originOffset.x -= dx;
            this._originOffset.z -= dz;
            console.log(`[FloatingOrigin] Shifted by (${dx.toFixed(1)}, ${dz.toFixed(1)}), cumulative: (${this._originOffset.x.toFixed(1)}, ${this._originOffset.z.toFixed(1)})`);
        }
    }

    getWorldPosition(localX, localZ) {
        return { x: localX + this._originOffset.x, z: localZ + this._originOffset.z };
    }

    // ── Cleanup ────────────────────────────────────────────

    clearObjects() {
        for (const mesh of this.meshMap.values()) {
            mesh.geometry.dispose();
            if (mesh.material.dispose) mesh.material.dispose();
            this.scene.remove(mesh);
        }
        this.meshMap.clear();
        if (this.selectionOutline) {
            this.selectionOutline.geometry.dispose();
            this.scene.remove(this.selectionOutline);
            this.selectionOutline = null;
        }
        // Remove point lights added for light objects
        const toRemove = [];
        this.scene.traverse(obj => { if (obj.isPointLight) toRemove.push(obj); });
        toRemove.forEach(l => this.scene.remove(l));
    }

    highlightTile(tileId) {
        // Remove previous tile highlight
        if (this._tileHighlight) {
            this.scene.remove(this._tileHighlight);
            this._tileHighlight.geometry?.dispose();
            this._tileHighlight.material?.dispose();
            this._tileHighlight = null;
        }
        if (!tileId) return;

        // Find the tile object in scene by name match
        let target = null;
        this.scene.traverse(obj => {
            if (obj.isMesh && obj.name && obj.name.includes(tileId)) {
                target = obj;
            }
        });
        if (!target) return;

        // Create orange wireframe overlay
        const geo = target.geometry.clone();
        const mat = new THREE.MeshBasicMaterial({
            color: 0xf5a623, wireframe: true, transparent: true, opacity: 0.4,
        });
        const highlight = new THREE.Mesh(geo, mat);
        highlight.position.copy(target.position);
        highlight.rotation.copy(target.rotation);
        highlight.scale.copy(target.scale);
        highlight.raycast = () => {};
        this.scene.add(highlight);
        this._tileHighlight = highlight;
    }

    dispose() {
        this._stopLODUpgradeLoop();
        if (this.animId) { cancelAnimationFrame(this.animId); this.animId = null; }
        window.removeEventListener('resize', this._onResize);
        if (this.transformControls) {
            this.transformControls.detach();
            this.transformControls.dispose();
        }
        if (this.renderer) {
            this.renderer.domElement.removeEventListener('click', this._onClick);
            this.container?.removeChild(this.renderer.domElement);
            this.renderer.dispose();
            this.renderer = null;
        }
        this.clearObjects();
        this.clearFootprints();
        this.clearMeasurements();
        this.clearNavPath();
        this.clearVisibilityHeatmap();
        this.clearBuildingBBox();
        this.outlineMat.dispose();
        this._initialized = false;
    }
}

// Export as global for bridging with non-module scripts
const viewer = new SceneViewer();
window.sceneViewer = viewer;
export default viewer;
