// Vibe3D Unity Accelerator — Plan Visual Preview Component
// Card-based timeline view of plan actions as an alternative to raw JSON.

(function () {
    'use strict';

    // ── Action type icon mapping (HTML entities) ────────────────

    const ACTION_ICONS = {
        create_primitive: '&#9724;',       // filled square
        create_empty:     '&#9723;',       // empty square
        create_light:     '&#128161;',     // lightbulb
        apply_material:   '&#127912;',     // palette
        modify_object:    '&#9998;',       // pencil
        delete_object:    '&#128465;',     // trash
        duplicate_object: '&#128203;',     // clipboard
        screenshot:       '&#128247;',     // camera
        save_scene:       '&#128190;',     // floppy
    };

    const DEFAULT_ICON = '&#9654;';        // right-pointing triangle fallback

    // ── Utility ─────────────────────────────────────────────────

    function esc(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    function formatVec3(obj) {
        if (!obj) return null;
        var x = obj.x != null ? obj.x : (obj[0] != null ? obj[0] : null);
        var y = obj.y != null ? obj.y : (obj[1] != null ? obj[1] : null);
        var z = obj.z != null ? obj.z : (obj[2] != null ? obj[2] : null);
        if (x == null && y == null && z == null) return null;
        return '(' + (x || 0) + ',' + (y || 0) + ',' + (z || 0) + ')';
    }

    function formatColor(color) {
        if (!color) return null;
        if (typeof color === 'string') return color;
        if (color.r != null) {
            // Detect 0-1 vs 0-255 range
            var isNormalized = (color.r <= 1 && color.g <= 1 && color.b <= 1);
            if (isNormalized) {
                var r = Math.round(color.r * 255);
                var g = Math.round(color.g * 255);
                var b = Math.round(color.b * 255);
                return 'rgb(' + r + ',' + g + ',' + b + ')';
            }
            return 'rgb(' + color.r + ',' + color.g + ',' + color.b + ')';
        }
        return JSON.stringify(color);
    }

    // ── PlanVisualizer class ────────────────────────────────────

    function PlanVisualizer() {
        this._container = null;
    }

    /**
     * Set the DOM container element where the plan visualization will render.
     * @param {HTMLElement} containerEl
     */
    PlanVisualizer.prototype.setContainer = function (containerEl) {
        this._container = containerEl;
    };

    /**
     * Clear the plan visualization display.
     */
    PlanVisualizer.prototype.clear = function () {
        if (this._container) {
            this._container.innerHTML = '';
        }
    };

    /**
     * Render a plan object as a vertical list of visual action cards.
     * @param {Object} plan   - Plan object with an `actions` array.
     * @param {string} method - Generation method label (e.g. "template", "llm").
     */
    PlanVisualizer.prototype.render = function (plan, method) {
        if (!this._container) return;
        this.clear();

        var actions = (plan && plan.actions) ? plan.actions : [];

        if (actions.length === 0) {
            this._container.innerHTML =
                '<div class="plan-visual-empty">플랜에 작업이 없습니다</div>';
            return;
        }

        // Optional method header
        if (method) {
            var header = document.createElement('div');
            header.className = 'plan-visual-header';
            header.innerHTML =
                '<span class="plan-visual-method badge ' + esc(method === 'template' ? 'template' : 'llm') + '">' +
                esc(method) + '</span> ' +
                '<span class="plan-visual-count">' + actions.length + '개 작업</span>';
            this._container.appendChild(header);
        }

        // Timeline connector
        var timeline = document.createElement('div');
        timeline.className = 'plan-timeline';

        for (var i = 0; i < actions.length; i++) {
            var action = actions[i];
            var card = this._buildCard(action, i + 1);
            timeline.appendChild(card);
        }

        this._container.appendChild(timeline);
    };

    /**
     * Build a single action card element.
     * @param {Object} action - Action descriptor from the plan.
     * @param {number} num    - 1-based action number.
     * @returns {HTMLElement}
     */
    PlanVisualizer.prototype._buildCard = function (action, num) {
        var type = action.type || action.action || 'unknown';
        var target = this._resolveTarget(action);
        var icon = ACTION_ICONS[type] || DEFAULT_ICON;
        var props = this._extractProps(action);
        var status = action.status || action.result_status || null;

        var card = document.createElement('div');
        card.className = 'plan-card';

        // Status class
        if (status === 'success' || status === 'completed') {
            card.classList.add('plan-card-success');
        } else if (status === 'failed' || status === 'error') {
            card.classList.add('plan-card-failed');
        }

        // Number badge
        var numEl = document.createElement('div');
        numEl.className = 'plan-card-num';
        numEl.textContent = num;

        // Icon
        var iconEl = document.createElement('div');
        iconEl.className = 'plan-card-icon';
        iconEl.innerHTML = icon;

        // Body
        var body = document.createElement('div');
        body.className = 'plan-card-body';

        var typeEl = document.createElement('div');
        typeEl.className = 'plan-card-type';
        typeEl.textContent = type;

        var targetEl = document.createElement('div');
        targetEl.className = 'plan-card-target';
        targetEl.textContent = target;

        body.appendChild(typeEl);
        if (target) {
            body.appendChild(targetEl);
        }

        // Property badges
        if (props.length > 0) {
            var propsEl = document.createElement('div');
            propsEl.className = 'plan-card-props';
            for (var j = 0; j < props.length; j++) {
                var span = document.createElement('span');
                span.className = 'plan-prop';
                span.textContent = props[j];
                propsEl.appendChild(span);
            }
            body.appendChild(propsEl);
        }

        // Status indicator
        if (status) {
            var statusEl = document.createElement('div');
            statusEl.className = 'plan-card-status';
            var statusLabels = { success: '완료', completed: '완료', failed: '실패', error: '오류' };
            var statusLabel = statusLabels[status] || status;
            if (status === 'success' || status === 'completed') {
                statusEl.innerHTML = '<span class="plan-status-dot plan-status-success"></span> ' + esc(statusLabel);
            } else if (status === 'failed' || status === 'error') {
                statusEl.innerHTML = '<span class="plan-status-dot plan-status-failed"></span> ' + esc(statusLabel);
            } else {
                statusEl.innerHTML = '<span class="plan-status-dot"></span> ' + esc(statusLabel);
            }
            body.appendChild(statusEl);
        }

        card.appendChild(numEl);
        card.appendChild(iconEl);
        card.appendChild(body);

        return card;
    };

    /**
     * Resolve a human-readable target name from an action object.
     */
    PlanVisualizer.prototype._resolveTarget = function (action) {
        var name = action.name || action.target || action.object_name || '';
        var shape = action.shape || action.primitive_type || '';

        if (name && shape) {
            return name + ' (' + shape + ')';
        }
        return name || shape || '';
    };

    /**
     * Extract displayable property badges from an action.
     * Returns an array of short label strings.
     */
    PlanVisualizer.prototype._extractProps = function (action) {
        var props = [];

        // Position
        var pos = action.position || action.pos;
        var posStr = formatVec3(pos);
        if (posStr) props.push('위치' + posStr);

        // Scale
        var scale = action.scale;
        var scaleStr = formatVec3(scale);
        if (scaleStr) props.push('크기' + scaleStr);

        // Rotation
        var rot = action.rotation || action.rot;
        var rotStr = formatVec3(rot);
        if (rotStr) props.push('회전' + rotStr);

        // Color
        var colorVal = formatColor(action.color);
        if (colorVal) props.push('색상:' + colorVal);

        // Shape / primitive type (shown separately if not in target)
        // Already handled in target, skip here

        // Material
        if (action.material) {
            props.push('mat:' + (typeof action.material === 'string' ? action.material : action.material.name || 'custom'));
        }

        // Intensity (lights)
        if (action.intensity != null) {
            props.push('intensity:' + action.intensity);
        }

        // Range (lights)
        if (action.range != null) {
            props.push('range:' + action.range);
        }

        // Parent
        if (action.parent) {
            props.push('부모:' + action.parent);
        }

        return props;
    };

    // ── Tab switching for plan views ────────────────────────────

    /**
     * Switch between the three plan view modes: timeline, minimap, json.
     * Manages showing/hiding the corresponding tab content and active states.
     * @param {string} view - One of "timeline", "minimap", "json".
     */
    function switchPlanView(view) {
        var validViews = ['timeline', 'minimap', 'json'];
        if (validViews.indexOf(view) === -1) return;

        // Toggle tab button active states
        var tabBtns = document.querySelectorAll('.plan-view-tab-btn');
        for (var i = 0; i < tabBtns.length; i++) {
            var btn = tabBtns[i];
            if (btn.dataset.planView === view) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        }

        // Toggle tab content panels
        var panels = document.querySelectorAll('.plan-view-panel');
        for (var j = 0; j < panels.length; j++) {
            var panel = panels[j];
            if (panel.dataset.planView === view) {
                panel.classList.add('active');
                panel.style.display = '';
            } else {
                panel.classList.remove('active');
                panel.style.display = 'none';
            }
        }
    }

    // ── Inject component CSS ────────────────────────────────────
    // Self-contained styles so the component works even if external
    // CSS has not yet defined these classes.

    var styleEl = document.createElement('style');
    styleEl.textContent = [
        '/* Plan Visual Preview Component */',
        '',
        '.plan-visual-empty {',
        '    text-align: center;',
        '    color: var(--text-3, #6b6c82);',
        '    padding: 20px;',
        '    font-size: 12px;',
        '}',
        '',
        '.plan-visual-header {',
        '    display: flex;',
        '    align-items: center;',
        '    gap: 8px;',
        '    padding: 6px 0 8px;',
        '    font-size: 12px;',
        '    color: var(--text-2, #a0a1b5);',
        '}',
        '',
        '.plan-visual-count {',
        '    color: var(--text-3, #6b6c82);',
        '    font-size: 11px;',
        '}',
        '',
        '.plan-timeline {',
        '    display: flex;',
        '    flex-direction: column;',
        '    gap: 4px;',
        '    position: relative;',
        '    padding-left: 4px;',
        '}',
        '',
        '/* Vertical timeline connector line */',
        '.plan-timeline::before {',
        '    content: "";',
        '    position: absolute;',
        '    left: 17px;',
        '    top: 8px;',
        '    bottom: 8px;',
        '    width: 2px;',
        '    background: var(--border, #3a3b5a);',
        '    border-radius: 1px;',
        '    z-index: 0;',
        '}',
        '',
        '.plan-card {',
        '    display: flex;',
        '    align-items: flex-start;',
        '    gap: 8px;',
        '    padding: 8px 10px;',
        '    background: var(--bg-2, #222341);',
        '    border: 1px solid var(--border, #3a3b5a);',
        '    border-radius: 6px;',
        '    position: relative;',
        '    z-index: 1;',
        '    transition: background 0.15s ease, border-color 0.15s ease;',
        '}',
        '',
        '.plan-card:hover {',
        '    background: var(--bg-3, #2a2b4a);',
        '    border-color: var(--border-light, #4a4b6a);',
        '}',
        '',
        '.plan-card-success {',
        '    border-left: 3px solid var(--success, #00b894);',
        '}',
        '',
        '.plan-card-failed {',
        '    border-left: 3px solid var(--error, #e17055);',
        '}',
        '',
        '.plan-card-num {',
        '    width: 22px;',
        '    height: 22px;',
        '    border-radius: 50%;',
        '    background: var(--accent, #6c5ce7);',
        '    color: #fff;',
        '    font-size: 11px;',
        '    font-weight: 700;',
        '    display: flex;',
        '    align-items: center;',
        '    justify-content: center;',
        '    flex-shrink: 0;',
        '    line-height: 1;',
        '}',
        '',
        '.plan-card-icon {',
        '    font-size: 16px;',
        '    width: 22px;',
        '    text-align: center;',
        '    flex-shrink: 0;',
        '    padding-top: 1px;',
        '}',
        '',
        '.plan-card-body {',
        '    flex: 1;',
        '    min-width: 0;',
        '}',
        '',
        '.plan-card-type {',
        '    font-size: 12px;',
        '    font-weight: 600;',
        '    color: var(--text-1, #e8e9f0);',
        '    font-family: "Cascadia Code", "Consolas", monospace;',
        '}',
        '',
        '.plan-card-target {',
        '    font-size: 11px;',
        '    color: var(--text-2, #a0a1b5);',
        '    margin-top: 1px;',
        '    overflow: hidden;',
        '    text-overflow: ellipsis;',
        '    white-space: nowrap;',
        '}',
        '',
        '.plan-card-props {',
        '    display: flex;',
        '    flex-wrap: wrap;',
        '    gap: 4px;',
        '    margin-top: 4px;',
        '}',
        '',
        '.plan-prop {',
        '    display: inline-block;',
        '    padding: 1px 6px;',
        '    background: var(--bg-input, #181930);',
        '    border: 1px solid var(--border, #3a3b5a);',
        '    border-radius: 10px;',
        '    font-size: 10px;',
        '    color: var(--text-3, #6b6c82);',
        '    font-family: "Cascadia Code", "Consolas", monospace;',
        '    white-space: nowrap;',
        '}',
        '',
        '.plan-card-status {',
        '    display: flex;',
        '    align-items: center;',
        '    gap: 4px;',
        '    margin-top: 4px;',
        '    font-size: 10px;',
        '    color: var(--text-3, #6b6c82);',
        '}',
        '',
        '.plan-status-dot {',
        '    width: 6px;',
        '    height: 6px;',
        '    border-radius: 50%;',
        '    background: var(--text-3, #6b6c82);',
        '    display: inline-block;',
        '}',
        '',
        '.plan-status-success {',
        '    background: var(--success, #00b894);',
        '}',
        '',
        '.plan-status-failed {',
        '    background: var(--error, #e17055);',
        '}',
        '',
        '/* Plan view tab switcher */',
        '',
        '.plan-view-tabs {',
        '    display: flex;',
        '    gap: 2px;',
        '}',
        '',
        '.plan-view-tab-btn {',
        '    padding: 3px 8px;',
        '    background: transparent;',
        '    border: none;',
        '    border-bottom: 2px solid transparent;',
        '    color: var(--text-3, #6b6c82);',
        '    font-size: 10px;',
        '    cursor: pointer;',
        '    text-transform: uppercase;',
        '    letter-spacing: 0.04em;',
        '    font-weight: 600;',
        '    transition: all 0.15s ease;',
        '}',
        '',
        '.plan-view-tab-btn:hover {',
        '    color: var(--text-2, #a0a1b5);',
        '}',
        '',
        '.plan-view-tab-btn.active {',
        '    color: var(--accent, #6c5ce7);',
        '    border-bottom-color: var(--accent, #6c5ce7);',
        '}',
        '',
        '.plan-view-panel {',
        '    display: none;',
        '}',
        '',
        '.plan-view-panel.active {',
        '    display: block;',
        '}',
    ].join('\n');
    document.head.appendChild(styleEl);

    // ── Export to window ─────────────────────────────────────────

    window.PlanVisualizer = PlanVisualizer;
    window.switchPlanView = switchPlanView;

})();
