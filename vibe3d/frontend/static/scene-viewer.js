// Vibe3D — Three.js 3D Scene Viewer (ES Module)
// Renders Unity scene objects from MCP hierarchy data with interactive controls.
// Supports object selection, drag-to-move with TransformControls, and Unity sync.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';

class SceneViewer {
    constructor() {
        this.renderer = null;
        this.scene = null;
        this.camera = null;
        this.controls = null;
        this.transformControls = null;
        this.container = null;
        this.meshMap = new Map(); // name → mesh
        this.selectedMesh = null;
        this.selectionOutline = null;
        this.outlineMat = new THREE.MeshBasicMaterial({
            color: 0x7c6cf0, wireframe: true, transparent: true, opacity: 0.5,
        });
        this.raycaster = new THREE.Raycaster();
        this.pointer = new THREE.Vector2();
        this.animId = null;
        this._initialized = false;
        this._onResize = this.resize.bind(this);
        this._onClick = this._handleClick.bind(this);
        this.onSelect = null; // callback(name)
        this.onMove = null;   // callback(name, unityPosition) — called after drag
        this._moveMode = false; // toggle between view and move mode
        this._dragStartPos = null; // position before drag (for undo detection)
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
        this.renderer.setClearColor(0x0a0b14);
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.2;
        container.appendChild(this.renderer.domElement);

        // Scene
        this.scene = new THREE.Scene();
        this.scene.fog = new THREE.FogExp2(0x0a0b14, 0.008);

        // Camera
        this.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 500);
        this.camera.position.set(15, 12, 15);

        // Orbit Controls
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.08;
        this.controls.target.set(0, 1, 0);
        this.controls.minDistance = 1;
        this.controls.maxDistance = 200;
        this.controls.maxPolarAngle = Math.PI * 0.95;

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
        const ambient = new THREE.AmbientLight(0x404060, 0.5);
        this.scene.add(ambient);

        const dirLight = new THREE.DirectionalLight(0xfff5e6, 1.2);
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

        const hemiLight = new THREE.HemisphereLight(0x8888cc, 0x444422, 0.4);
        this.scene.add(hemiLight);

        // Grid
        const grid = new THREE.GridHelper(80, 80, 0x3a3b65, 0x1c1d38);
        grid.position.y = -0.01;
        this.scene.add(grid);

        // Axes
        const axes = new THREE.AxesHelper(2);
        axes.position.set(-0.5, 0.01, -0.5);
        this.scene.add(axes);

        // Events
        window.addEventListener('resize', this._onResize);
        this.renderer.domElement.addEventListener('click', this._onClick);
        this.renderer.domElement.style.cursor = 'grab';

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
            const name = this.selectedMesh.userData.objectName;
            const newMesh = this.meshMap.get(name);
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
        mesh.userData.objectName = obj.name;
        mesh.userData.objectPath = obj.path || '';
        mesh.userData.tag = obj.tag || '';
        mesh.userData.type = obj.type || '';

        this.scene.add(mesh);
        this.meshMap.set(obj.name, mesh);

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
        if (n.includes('floor') || n.includes('ground')) return 'Cube';
        if (n.includes('plane')) return 'Plane';
        if (n.includes('sphere') || n.includes('ball') || n.includes('dome')) return 'Sphere';
        if (n.includes('cylinder') || n.includes('body') || n.includes('pipe') || n.includes('column') || n.includes('tube')) return 'Cylinder';
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
        const mesh = this.meshMap.get(name);
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

    selectObject(name) {
        if (this.selectionOutline) {
            this.scene.remove(this.selectionOutline);
            this.selectionOutline.geometry.dispose();
            this.selectionOutline = null;
        }

        const mesh = this.meshMap.get(name);
        if (!mesh) return;
        this.selectedMesh = mesh;

        const outGeo = mesh.geometry.clone();
        this.selectionOutline = new THREE.Mesh(outGeo, this.outlineMat);
        this.selectionOutline.position.copy(mesh.position);
        this.selectionOutline.rotation.copy(mesh.rotation);
        this.selectionOutline.scale.copy(mesh.scale).multiplyScalar(1.06);
        this.scene.add(this.selectionOutline);

        // Smooth look-at
        this.controls.target.lerp(mesh.position, 0.5);

        // In move mode, attach transform gizmo to selected object
        if (this._moveMode) {
            this.transformControls.attach(mesh);
            this.transformControls.visible = true;
            this.transformControls.enabled = true;
        }
    }

    _handleClick(event) {
        if (!this.renderer || !this.camera) return;

        // Don't process clicks on the transform gizmo itself
        if (this.transformControls && this.transformControls.dragging) return;

        const rect = this.renderer.domElement.getBoundingClientRect();
        this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.pointer, this.camera);
        const intersects = this.raycaster.intersectObjects(Array.from(this.meshMap.values()));

        if (intersects.length > 0) {
            const name = intersects[0].object.userData.objectName;
            if (name) {
                this.selectObject(name);
                if (this.onSelect) this.onSelect(name);
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

    dispose() {
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
        this.outlineMat.dispose();
        this._initialized = false;
    }
}

// Export as global for bridging with non-module scripts
const viewer = new SceneViewer();
window.sceneViewer = viewer;
export default viewer;
