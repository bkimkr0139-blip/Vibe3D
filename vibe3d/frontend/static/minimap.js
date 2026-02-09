// Vibe3D Unity Accelerator — 2D Minimap Canvas Component
// Top-down view of Unity scene: existing objects (gray) + new plan objects (accent)

(function () {
    'use strict';

    // ── Theme constants ──────────────────────────────────────────
    const COLORS = {
        background: '#12131e',
        grid:       '#2a2b4a',
        existing:   '#4a4b6a',
        accent:     '#6c5ce7',
        label:      '#a0a1b5',
        border:     '#3a3b5a',
    };

    const PADDING_RATIO = 0.10;     // 10% padding around scene
    const GRID_STEP_MIN_PX = 40;    // minimum pixels between grid lines
    const LABEL_FONT = '10px "Segoe UI", sans-serif';
    const LABEL_OFFSET_Y = -4;      // px above rectangle top

    // ── MinimapRenderer ──────────────────────────────────────────

    class MinimapRenderer {

        /**
         * @param {HTMLCanvasElement} [canvasEl] - optional canvas on construction
         */
        constructor(canvasEl) {
            this._canvas = null;
            this._ctx = null;

            // Viewport transform state (recalculated each render)
            this._scale = 1;
            this._offsetX = 0;
            this._offsetY = 0;

            // Cached scene data for hit-testing
            this._allItems = [];   // { obj, isNew, screenRect }

            // Callbacks
            this.onHover = null;   // (info | null) => void
            this.onClick = null;   // (info) => void

            // Bound listeners (so we can remove them)
            this._onMouseMove = this._handleMouseMove.bind(this);
            this._onMouseClick = this._handleMouseClick.bind(this);

            if (canvasEl) {
                this.setCanvas(canvasEl);
            }
        }

        // ── Public API ───────────────────────────────────────────

        /**
         * Attach (or re-attach) to a canvas element.
         * @param {HTMLCanvasElement} canvasEl
         */
        setCanvas(canvasEl) {
            // Detach old listeners
            if (this._canvas) {
                this._canvas.removeEventListener('mousemove', this._onMouseMove);
                this._canvas.removeEventListener('click', this._onMouseClick);
            }

            this._canvas = canvasEl;
            this._ctx = canvasEl.getContext('2d');

            // Attach new listeners
            this._canvas.addEventListener('mousemove', this._onMouseMove);
            this._canvas.addEventListener('click', this._onMouseClick);
        }

        /**
         * Render the minimap.
         *
         * Each object should have at minimum:
         *   { name, x, z, width?, depth? }
         * where x/z are world coordinates.  width and depth default to 1.
         *
         * @param {Object[]} newObjects      - objects to draw in accent color
         * @param {Object[]} existingObjects - objects to draw in gray
         * @param {{ minX, maxX, minZ, maxZ }|null} bounds - optional explicit bounds
         */
        render(newObjects, existingObjects, bounds) {
            const canvas = this._canvas;
            const ctx = this._ctx;
            if (!canvas || !ctx) return;

            // Sync internal resolution with CSS size (handle DPR)
            const dpr = window.devicePixelRatio || 1;
            const cssW = canvas.clientWidth;
            const cssH = canvas.clientHeight;
            if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
                canvas.width = cssW * dpr;
                canvas.height = cssH * dpr;
            }
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

            const w = cssW;
            const h = cssH;

            // ── 1. Compute world bounds ──────────────────────────
            const all = (existingObjects || []).concat(newObjects || []);
            const worldBounds = this._computeBounds(all, bounds);

            // ── 2. Compute viewport transform ────────────────────
            this._computeTransform(worldBounds, w, h);

            // ── 3. Clear ─────────────────────────────────────────
            ctx.fillStyle = COLORS.background;
            ctx.fillRect(0, 0, w, h);

            // ── 4. Grid ──────────────────────────────────────────
            this._drawGrid(ctx, worldBounds, w, h);

            // ── 5. Bounds border ─────────────────────────────────
            if (bounds) {
                this._drawBoundsBorder(ctx, bounds);
            }

            // ── 6. Objects ───────────────────────────────────────
            this._allItems = [];

            if (existingObjects) {
                for (const obj of existingObjects) {
                    this._drawObject(ctx, obj, COLORS.existing, false);
                }
            }
            // Draw new objects on top so they are always visible
            if (newObjects) {
                for (const obj of newObjects) {
                    this._drawObject(ctx, obj, COLORS.accent, true);
                }
            }
        }

        /**
         * Convert world coordinates (x, z) to screen pixels.
         * @param {number} wx
         * @param {number} wz
         * @returns {{ sx: number, sy: number }}
         */
        world2screen(wx, wz) {
            return {
                sx: (wx - this._offsetX) * this._scale,
                sy: (wz - this._offsetY) * this._scale,
            };
        }

        /**
         * Convert screen pixels to world coordinates (x, z).
         * @param {number} sx
         * @param {number} sy
         * @returns {{ wx: number, wz: number }}
         */
        screen2world(sx, sy) {
            return {
                wx: sx / this._scale + this._offsetX,
                wz: sy / this._scale + this._offsetY,
            };
        }

        // ── Internal: bounds & transform ─────────────────────────

        _computeBounds(objects, explicit) {
            let minX = Infinity, maxX = -Infinity;
            let minZ = Infinity, maxZ = -Infinity;

            if (explicit) {
                minX = explicit.minX;
                maxX = explicit.maxX;
                minZ = explicit.minZ;
                maxZ = explicit.maxZ;
            }

            for (const o of objects) {
                const hw = (o.width || 1) / 2;
                const hd = (o.depth || 1) / 2;
                const x = o.x || 0;
                const z = o.z || 0;
                if (x - hw < minX) minX = x - hw;
                if (x + hw > maxX) maxX = x + hw;
                if (z - hd < minZ) minZ = z - hd;
                if (z + hd > maxZ) maxZ = z + hd;
            }

            // Fallback when nothing is provided
            if (!isFinite(minX)) { minX = -10; maxX = 10; minZ = -10; maxZ = 10; }

            return { minX, maxX, minZ, maxZ };
        }

        _computeTransform(bounds, canvasW, canvasH) {
            const worldW = bounds.maxX - bounds.minX || 1;
            const worldH = bounds.maxZ - bounds.minZ || 1;

            const pad = PADDING_RATIO;
            const scaleX = canvasW / (worldW * (1 + 2 * pad));
            const scaleY = canvasH / (worldH * (1 + 2 * pad));
            this._scale = Math.min(scaleX, scaleY);

            // Center the scene in the canvas
            const visibleW = canvasW / this._scale;
            const visibleH = canvasH / this._scale;
            const centerX = (bounds.minX + bounds.maxX) / 2;
            const centerZ = (bounds.minZ + bounds.maxZ) / 2;

            this._offsetX = centerX - visibleW / 2;
            this._offsetY = centerZ - visibleH / 2;
        }

        // ── Internal: drawing helpers ────────────────────────────

        _drawGrid(ctx, bounds, canvasW, canvasH) {
            // Choose a nice grid step in world units
            const step = this._niceGridStep(canvasW);

            ctx.strokeStyle = COLORS.grid;
            ctx.lineWidth = 0.5;
            ctx.beginPath();

            // Vertical lines (along world X)
            const startX = Math.floor(bounds.minX / step) * step;
            for (let wx = startX; wx <= bounds.maxX + step; wx += step) {
                const { sx } = this.world2screen(wx, 0);
                if (sx < 0 || sx > canvasW) continue;
                ctx.moveTo(sx, 0);
                ctx.lineTo(sx, canvasH);
            }

            // Horizontal lines (along world Z)
            const startZ = Math.floor(bounds.minZ / step) * step;
            for (let wz = startZ; wz <= bounds.maxZ + step; wz += step) {
                const { sy } = this.world2screen(0, wz);
                if (sy < 0 || sy > canvasH) continue;
                ctx.moveTo(0, sy);
                ctx.lineTo(canvasW, sy);
            }

            ctx.stroke();
        }

        /**
         * Pick a "nice" world-space grid step so lines are never too dense.
         */
        _niceGridStep(canvasW) {
            const worldVisible = canvasW / this._scale;
            // We want at least GRID_STEP_MIN_PX between lines
            const rawStep = (GRID_STEP_MIN_PX / this._scale);
            // Round up to a "nice" number: 1, 2, 5, 10, 20, 50, ...
            const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
            const residual = rawStep / mag;
            let nice;
            if (residual <= 1) nice = 1;
            else if (residual <= 2) nice = 2;
            else if (residual <= 5) nice = 5;
            else nice = 10;
            return nice * mag;
        }

        _drawBoundsBorder(ctx, bounds) {
            const tl = this.world2screen(bounds.minX, bounds.minZ);
            const br = this.world2screen(bounds.maxX, bounds.maxZ);
            ctx.strokeStyle = COLORS.border;
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.strokeRect(tl.sx, tl.sy, br.sx - tl.sx, br.sy - tl.sy);
            ctx.setLineDash([]);
        }

        _drawObject(ctx, obj, color, isNew) {
            const ow = (obj.width || 1);
            const od = (obj.depth || 1);
            const x = obj.x || 0;
            const z = obj.z || 0;

            const tl = this.world2screen(x - ow / 2, z - od / 2);
            const br = this.world2screen(x + ow / 2, z + od / 2);

            const rx = tl.sx;
            const ry = tl.sy;
            const rw = br.sx - tl.sx;
            const rh = br.sy - tl.sy;

            // Ensure minimum visible size (at least 4px)
            const drawW = Math.max(rw, 4);
            const drawH = Math.max(rh, 4);
            const drawX = rw < 4 ? rx - (4 - rw) / 2 : rx;
            const drawY = rh < 4 ? ry - (4 - rh) / 2 : ry;

            // Fill
            ctx.fillStyle = color;
            ctx.globalAlpha = isNew ? 0.85 : 0.55;
            ctx.fillRect(drawX, drawY, drawW, drawH);

            // Stroke
            ctx.globalAlpha = 1.0;
            ctx.strokeStyle = color;
            ctx.lineWidth = isNew ? 1.5 : 0.75;
            ctx.strokeRect(drawX, drawY, drawW, drawH);

            // Label
            if (obj.name) {
                ctx.fillStyle = COLORS.label;
                ctx.font = LABEL_FONT;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'bottom';
                ctx.fillText(obj.name, drawX + drawW / 2, drawY + LABEL_OFFSET_Y);
            }

            // Cache screen rect for hit testing
            this._allItems.push({
                obj: obj,
                isNew: isNew,
                screenRect: { x: drawX, y: drawY, w: drawW, h: drawH },
            });
        }

        // ── Internal: interaction ────────────────────────────────

        _hitTest(sx, sy) {
            // Walk backwards so top-drawn items (new objects) match first
            for (let i = this._allItems.length - 1; i >= 0; i--) {
                const item = this._allItems[i];
                const r = item.screenRect;
                if (sx >= r.x && sx <= r.x + r.w && sy >= r.y && sy <= r.y + r.h) {
                    return item;
                }
            }
            return null;
        }

        _buildInfo(item, sx, sy) {
            const world = this.screen2world(sx, sy);
            return {
                object: item.obj,
                isNew: item.isNew,
                screenX: sx,
                screenY: sy,
                worldX: world.wx,
                worldZ: world.wz,
            };
        }

        _canvasCoords(e) {
            const rect = this._canvas.getBoundingClientRect();
            return {
                sx: e.clientX - rect.left,
                sy: e.clientY - rect.top,
            };
        }

        _handleMouseMove(e) {
            if (!this.onHover) return;
            const { sx, sy } = this._canvasCoords(e);
            const hit = this._hitTest(sx, sy);
            if (hit) {
                this._canvas.style.cursor = 'pointer';
                this.onHover(this._buildInfo(hit, sx, sy));
            } else {
                this._canvas.style.cursor = 'default';
                this.onHover(null);
            }
        }

        _handleMouseClick(e) {
            if (!this.onClick) return;
            const { sx, sy } = this._canvasCoords(e);
            const hit = this._hitTest(sx, sy);
            if (hit) {
                this.onClick(this._buildInfo(hit, sx, sy));
            } else {
                // Clicked empty space — still report world position
                const world = this.screen2world(sx, sy);
                this.onClick({
                    object: null,
                    isNew: false,
                    screenX: sx,
                    screenY: sy,
                    worldX: world.wx,
                    worldZ: world.wz,
                });
            }
        }
    }

    // ── Export globally ───────────────────────────────────────────
    window.MinimapRenderer = MinimapRenderer;

})();
