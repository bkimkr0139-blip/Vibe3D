// Vibe3D Unity Accelerator v3.0 — Frontend Application

const API = window.location.origin;
let ws = null;
let selectedObject = null;
let currentFilePath = '';
let commandHistoryList = [];
let commandHistoryIdx = -1;
let suggestUI = null;
let planVisualizer = null;
let minimapRenderer = null;
let sourcePicker = null;
let selectedFiles = new Set();
// Unified mode — no separate command/chat toggle
let sceneAutoRefresh = false;
let sceneRefreshTimer = null;
let _sceneObjects = {}; // name → {position, scale, path, primitive, color}
let currentComponentId = null;
let sceneViewMode = '3d'; // '3d' or 'screenshot'
let scene3dInitialized = false;
let _lastCompletedJobId = null; // Track last undoable job for quick undo

// ── Init ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    checkStatus();
    connectWebSocket();
    loadPresets();
    loadComponents();

    const input = document.getElementById('chatInput');
    input.addEventListener('keydown', handleInputKeys);
    input.addEventListener('input', autoResizeInput);

    // Ctrl+Z undo shortcut — works even when textarea is focused (if empty)
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'z') {
            const isTextInput = ['INPUT', 'TEXTAREA'].includes(e.target.tagName);
            // Let browser handle text undo if input has content
            if (isTextInput && e.target.value.length > 0) return;
            e.preventDefault();
            e.stopPropagation();
            // Blur text input to prevent browser text-undo interference
            if (isTextInput) e.target.blur();
            undoLast();
        }
        // W key — toggle move mode (when not typing)
        if (e.key === 'w' || e.key === 'W') {
            const isTextInput = ['INPUT', 'TEXTAREA'].includes(e.target.tagName);
            if (isTextInput) return;
            e.preventDefault();
            toggleMoveMode();
        }
    });

    // Load working dir, favorites, and drives
    fetch(`${API}/api/workdir`).then(r => r.json()).then(data => {
        currentFilePath = data.path || '';
        _pinnedDirs = (data.pinned || []).map(p => p.replace(/\\/g, '/'));
        loadFiles(currentFilePath);
        renderFavorites();
    }).catch(() => {});
    loadDrives();

    // Load command history
    fetch(`${API}/api/command-history`).then(r => r.json()).then(data => {
        commandHistoryList = data.commands || [];
    }).catch(() => {});

    setInterval(checkStatus, 15000);
    checkWebglStatus();

    // Initialize 3D viewer (default mode)
    setTimeout(() => setSceneViewMode('3d'), 300);

    // Initialize UI components
    if (typeof SuggestUI === 'function') {
        suggestUI = new SuggestUI();
        suggestUI.attach(
            document.getElementById('chatInput'),
            document.getElementById('suggestDropdown')
        );
    }

    if (typeof MinimapRenderer === 'function') {
        minimapRenderer = new MinimapRenderer(document.getElementById('planMinimap'));
        minimapRenderer.onClick = function(info) {
            if (info.object && info.object.name) {
                selectedObject = info.object.name;
                inspectObject(info.object.name);
            }
        };
    }

    if (window.SourcePicker) {
        sourcePicker = window.SourcePicker;
    }
});

// ── Input Handling ──────────────────────────────────────────

function handleInputKeys(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChat();
        return;
    }
    if (e.key === 'ArrowUp' && e.target.selectionStart === 0) {
        e.preventDefault();
        navigateHistory(1);
    }
    if (e.key === 'ArrowDown') {
        navigateHistory(-1);
    }
}

function autoResizeInput() {
    const el = document.getElementById('chatInput');
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 100) + 'px';
}

function navigateHistory(dir) {
    if (!commandHistoryList.length) return;
    commandHistoryIdx = Math.max(-1, Math.min(commandHistoryList.length - 1, commandHistoryIdx + dir));
    const input = document.getElementById('chatInput');
    input.value = commandHistoryIdx >= 0 ? commandHistoryList[commandHistoryIdx] : '';
}

function insertExample(el) {
    document.getElementById('chatInput').value = el.textContent;
    document.getElementById('chatInput').focus();
}

// setChatMode removed — unified AI mode handles both commands and questions

// ── Target Tag (object selection → command input) ────────────

let _targetObjectName = null;

function setTargetTag(name) {
    _targetObjectName = name;
    const tag = document.getElementById('targetTag');
    if (tag) {
        tag.textContent = name;
        tag.style.display = 'inline-flex';
        tag.title = `대상: ${name} (클릭하여 해제)`;
    }
    const input = document.getElementById('chatInput');
    input.placeholder = `"${name}"에 대한 명령을 입력하세요...`;
    input.focus();
}

function clearTargetTag() {
    _targetObjectName = null;
    const tag = document.getElementById('targetTag');
    if (tag) tag.style.display = 'none';
    const input = document.getElementById('chatInput');
    input.placeholder = '자연어 명령을 입력하세요... (Enter로 전송)';
}

// ── Status ──────────────────────────────────────────────────

async function checkStatus() {
    try {
        const data = await (await fetch(`${API}/api/status`)).json();
        updateStatusUI(data);
    } catch {
        updateStatusUI({ mcp_connected: false });
    }
}

function updateStatusUI(data) {
    const mcp = document.getElementById('mcpStatus');
    mcp.className = 'status-pill ' + (data.mcp_connected ? 'connected' : 'disconnected');

    const nlu = document.getElementById('nluStatus');
    if (nlu) nlu.className = 'status-pill ' + (data.nlu_available || data.has_api_key ? 'connected' : 'disconnected');

    document.getElementById('mcpUrlFooter').textContent = data.mcp_url || '-';
    document.getElementById('sessionFooter').textContent = data.session_id ? data.session_id.substring(0, 8) : '-';
    document.getElementById('jobCountFooter').textContent = data.jobs_completed || 0;
}

async function connectMCP() {
    const el = document.getElementById('mcpStatus');
    el.className = 'status-pill connecting';
    try {
        const resp = await fetch(`${API}/api/connect`, { method: 'POST' });
        if (resp.ok) checkStatus();
    } catch (e) {
        checkStatus();
        addChatMsg('system', `MCP connection failed: ${e.message}`);
    }
}

// ── WebSocket ───────────────────────────────────────────────

function connectWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onclose = () => setTimeout(connectWebSocket, 3000);
    ws.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            handleWS(msg.event, msg.data);
        } catch {}
    };
    setInterval(() => { if (ws?.readyState === 1) ws.send('ping'); }, 30000);
}

function handleWS(event, data) {
    if (event === 'mcp_status') checkStatus();
    if (event === 'job_start') {
        setFooterStatus('AI 분석 중...');
        resetExecProgress();
    }
    if (event === 'plan_generated') {
        updateMinimap(data.plan);
    }
    if (event === 'plan_preview') {
        setFooterStatus('실행 계획 확인 대기 중');
    }
    if (event === 'plan_approved') {
        setFooterStatus('실행 중...');
    }
    if (event === 'plan_rejected') {
        setFooterStatus('');
    }
    if (event === 'job_completed' || event === 'job_failed') {
        updateJob(data);
        setFooterStatus('');
        hideMinimap();
        if (data.status === 'completed' || data.status === 'partial') {
            // Track for quick undo if this job has an undo plan
            if (data.undo_available && data.job_id) {
                _lastCompletedJobId = data.job_id;
            }
            refreshSceneView();
            refreshHierarchy();
            // Start build status polling for WebGL builds
            if (data.method === 'webgl_build') {
                startWebglBuildPoll();
            }
        }
    }
    if (event === 'action_progress') {
        updateActionProgress(data.current, data.total, data.action_type, data.status);
    }
    if (event === 'stage_update') handleStageUpdate(data);
    if (event === 'composite_progress') handleCompositeProgress(data);
}

function setFooterStatus(text) {
    document.getElementById('footerStatus').textContent = text;
}

// ── Chat / Command Execution ────────────────────────────────

async function sendChat() {
    const input = document.getElementById('chatInput');
    const rawMessage = input.value.trim();
    if (!rawMessage) return;

    // Prepend target object name if a tag is active
    const message = _targetObjectName
        ? `"${_targetObjectName}" ${rawMessage}`
        : rawMessage;

    const btn = document.getElementById('chatSendBtn');
    btn.disabled = true;

    // Show user message in chat (display with tag prefix)
    addChatMsg('user', message);
    input.value = '';
    input.style.height = 'auto';
    clearTargetTag();

    // Track history
    commandHistoryList.unshift(message);
    if (commandHistoryList.length > 50) commandHistoryList.pop();
    commandHistoryIdx = -1;

    // Remove welcome message if present
    const welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    try {
        // Unified AI endpoint — handles both commands and questions
        const resp = await fetch(`${API}/api/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: message }),
        });
        const data = await resp.json();

        if (data.status === 'response') {
            // Conversational response (question answer)
            addChatMsg('assistant', data.message || 'No response');
        } else if (data.status === 'plan_ready') {
            // Show approval card — user must approve before execution
            showApprovalCard(data.job_id, data.plan, data.confirmation_message || data.message);
        } else if (data.status === 'failed' || data.status === 'validation_failed') {
            addChatMsg('system', data.message || 'Failed');
            if (data.suggestions?.length > 0) {
                const sugText = data.suggestions.map(s => s.label || s.command).join(', ');
                addChatMsg('assistant', `Suggestions: ${sugText}`);
            }
        } else {
            addChatMsg('system', data.message || data.status);
        }

        if (data.job_id) {
            addJob({
                job_id: data.job_id, command: message,
                status: data.status, detail: data.message,
            });
        }
    } catch (e) {
        addChatMsg('system', `Error: ${e.message}`);
        addJob({ command: message, status: 'failed', detail: e.message });
    } finally {
        btn.disabled = false;
    }
}

// ── Plan Approval Card ──────────────────────────────────────

// Store pending plans so we can apply visual updates after approval
const _pendingPlans = {};
// Persistent color overrides — survives scene reloads (frontend fallback)
const _colorOverrides = {}; // name → {r, g, b}

/**
 * Extract ALL color changes from plan actions into _colorOverrides.
 * Handles: apply_material, create_material+assign_material, set_renderer_color,
 * set_material_color, create_primitive/light with color, delete_object cleanup.
 */
function _extractColorOverrides(actions) {
    if (!actions) return;
    const materialColors = {}; // material name → color

    for (const a of actions) {
        // Remember material colors for later assign_material
        if (a.type === 'create_material' && a.name && a.color) {
            materialColors[a.name] = a.color;
        }
        // Direct color application
        if (a.type === 'apply_material' && a.target && a.color) {
            _colorOverrides[a.target] = a.color;
        }
        // Material assignment — apply remembered color
        if (a.type === 'assign_material' && a.target && a.material_path) {
            const matName = a.material_path.split('/').pop().replace('.mat', '');
            if (materialColors[matName]) {
                _colorOverrides[a.target] = materialColors[matName];
            }
        }
        // set_renderer_color / set_material_color
        if ((a.type === 'set_renderer_color' || a.type === 'set_material_color') && a.target && a.color) {
            _colorOverrides[a.target] = a.color;
        }
        // create_primitive with color
        if (a.type === 'create_primitive' && a.name && a.color) {
            _colorOverrides[a.name] = a.color;
        }
        // create_light with color
        if (a.type === 'create_light' && a.name && a.color) {
            _colorOverrides[a.name] = a.color;
        }
        // delete_object — remove stale override
        if (a.type === 'delete_object' && a.target) {
            delete _colorOverrides[a.target];
        }
    }
}

function showApprovalCard(jobId, plan, confirmationMessage) {
    _pendingPlans[jobId] = plan;
    const container = document.getElementById('chatMessages');
    const card = document.createElement('div');
    card.className = 'chat-msg approval-card';
    card.id = `approval-${jobId}`;

    const actions = plan?.actions || [];
    const method = plan?.method || '';

    let actionsHtml = '';
    if (actions.length > 0) {
        actionsHtml = '<div class="approval-actions">';
        const showCount = Math.min(actions.length, 6);
        for (let i = 0; i < showCount; i++) {
            const a = actions[i];
            const icon = getActionIcon(a.type);
            const target = a.name || a.target || '';
            actionsHtml += `<div class="approval-action-item">${icon} <b>${esc(a.type)}</b> ${esc(target)}</div>`;
        }
        if (actions.length > 6) {
            actionsHtml += `<div class="approval-action-item more">... 외 ${actions.length - 6}개 작업</div>`;
        }
        actionsHtml += '</div>';
    }

    card.innerHTML = `
        <div class="approval-header">실행 계획 확인</div>
        <div class="approval-message">${esc(confirmationMessage)}</div>
        ${actionsHtml}
        <div class="approval-meta">${actions.length}개 작업 | ${method || 'AI'}</div>
        <div class="approval-buttons">
            <button class="approval-btn approve" onclick="approvePlan('${jobId}', this)">승인 (실행)</button>
            <button class="approval-btn reject" onclick="rejectPlan('${jobId}', this)">취소</button>
        </div>
    `;

    container.appendChild(card);
    container.scrollTop = container.scrollHeight;
}

function getActionIcon(type) {
    const icons = {
        create_primitive: '+',
        create_light: '*',
        create_empty: '+',
        delete_object: 'x',
        modify_object: '~',
        apply_material: '#',
        move_relative: '>',
        duplicate_object: '++',
        screenshot: '@',
        save_scene: '!',
    };
    return icons[type] || '-';
}

async function approvePlan(jobId, btn) {
    // Disable buttons
    const card = document.getElementById(`approval-${jobId}`);
    if (!card) return;
    card.querySelectorAll('.approval-btn').forEach(b => b.disabled = true);
    btn.textContent = '실행 중...';

    try {
        const resp = await fetch(`${API}/api/command/${jobId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await resp.json();

        // Update the card
        card.classList.add('approved');
        const statusText = data.status === 'completed'
            ? `${data.message}`
            : `${data.status}: ${data.message}`;
        const undoHtml = (data.status === 'completed' && data.undo_available)
            ? `<button class="approval-btn undo" onclick="undoJob('${esc(jobId)}')">되돌리기</button>`
            : '';
        card.querySelector('.approval-buttons').innerHTML =
            `<div class="approval-result ${data.status === 'completed' ? 'success' : 'error'}">${esc(statusText)}</div>${undoHtml}`;

        // Track for quick undo (Ctrl+Z / toolbar button)
        if (data.status === 'completed' && data.undo_available) {
            _lastCompletedJobId = jobId;
        }

        // Update job and refresh scene
        updateJob({ job_id: jobId, status: data.status, ...data });
        if (data.status === 'completed') {
            // Extract color overrides from plan (use server response plan if available)
            const plan = data.plan || _pendingPlans[jobId];
            if (plan && plan.actions) {
                _extractColorOverrides(plan.actions);
            }
            delete _pendingPlans[jobId];
            hideMinimap();
            // Refresh scene view to reflect all changes (objects, positions, colors)
            refreshSceneView();
            refreshHierarchy();
        }
    } catch (e) {
        card.querySelector('.approval-buttons').innerHTML =
            `<div class="approval-result error">Error: ${esc(e.message)}</div>`;
    }
}

async function rejectPlan(jobId, btn) {
    const card = document.getElementById(`approval-${jobId}`);
    if (!card) return;

    try {
        await fetch(`${API}/api/command/${jobId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
    } catch {}

    card.classList.add('rejected');
    card.querySelector('.approval-buttons').innerHTML =
        '<div class="approval-result rejected-text">취소됨</div>';
    delete _pendingPlans[jobId];
    hideMinimap();
    updateJob({ job_id: jobId, status: 'rejected' });
}

// ── Chat Messages ───────────────────────────────────────────

function addChatMsg(role, text, data) {
    const container = document.getElementById('chatMessages');
    const div = document.createElement('div');

    if (role === 'plan') {
        div.className = 'chat-msg plan-msg';
        const actions = data?.plan?.actions || [];
        let html = `<div class="plan-summary">${esc(text)}</div>`;
        if (actions.length > 0) {
            html += '<ol class="plan-actions-list">';
            for (const a of actions.slice(0, 8)) {
                html += `<li>${esc(a.type || '')} — ${esc(a.name || a.target || '')}</li>`;
            }
            if (actions.length > 8) html += `<li>...and ${actions.length - 8} more</li>`;
            html += '</ol>';
        }
        div.innerHTML = html;
    } else {
        div.className = `chat-msg ${role}`;
        div.textContent = text;
    }

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function clearChat() {
    const container = document.getElementById('chatMessages');
    container.innerHTML = `
        <div class="chat-welcome">
            <p>Unity 작업을 자연어로 입력하세요. AI가 명령을 분석하고 실행 계획을 보여드립니다.</p>
            <div class="welcome-examples">
                <span class="example-chip" onclick="insertExample(this)">10m x 10m 바닥 만들어줘</span>
                <span class="example-chip" onclick="insertExample(this)">건물 외부 프레임 색상을 파란색으로</span>
                <span class="example-chip" onclick="insertExample(this)">씬에 오브젝트가 몇 개 있어?</span>
                <span class="example-chip" onclick="insertExample(this)">빨간색 큐브 3개 배치해줘</span>
            </div>
        </div>
    `;
    // Also clear NLU history
    fetch(`${API}/api/chat/clear`, { method: 'POST' }).catch(() => {});
}

function showPlanInChat(plan, method) {
    if (!plan || !plan.actions) return;
    const count = plan.actions.length;
    addChatMsg('plan', `Plan generated (${method}) — ${count} actions`, { plan });
}

// ── Scene Viewer ────────────────────────────────────────────

function setSceneViewMode(mode) {
    sceneViewMode = mode;
    document.querySelectorAll('.view-toggle-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.mode === mode)
    );

    const container3d = document.getElementById('scene3dContainer');
    const containerSS = document.getElementById('screenshotContainer');

    if (mode === '3d') {
        container3d.style.display = 'block';
        containerSS.style.display = 'none';
        init3DViewer();
    } else {
        container3d.style.display = 'none';
        containerSS.style.display = 'flex';
    }
}

function init3DViewer() {
    if (scene3dInitialized) {
        if (window.sceneViewer) window.sceneViewer.resize();
        return;
    }
    // Wait for the ES module to load and expose window.sceneViewer
    const tryInit = () => {
        if (!window.sceneViewer) {
            setTimeout(tryInit, 100);
            return;
        }
        const container = document.getElementById('scene3dContainer');
        if (!container) return;
        window.sceneViewer.init(container);
        window.sceneViewer.onSelect = (name) => {
            selectedObject = name;
            inspectObject(name);
            // Highlight in hierarchy
            document.querySelectorAll('.node-row.selected').forEach(el => el.classList.remove('selected'));
            document.querySelectorAll('.node-name').forEach(el => {
                if (el.textContent === name) el.closest('.node-row')?.classList.add('selected');
            });
            // Set target tag in command input
            setTargetTag(name);
            // Notify parent window (HeatOps Nav X) of equipment selection
            notifyEquipmentSelected(name);
        };
        // Drag-to-move callback — sync position to Unity via MCP
        window.sceneViewer.onMove = async (name, unityPos) => {
            try {
                const resp = await fetch(`${API}/api/object/action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'modify',
                        target: name,
                        position: [unityPos.x, unityPos.y, unityPos.z],
                    }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    addChatMsg('system', `"${name}" 이동 완료 → (${unityPos.x}, ${unityPos.y}, ${unityPos.z})`);
                } else {
                    addChatMsg('system', `이동 실패: ${data.detail || resp.statusText}`);
                }
            } catch (e) {
                addChatMsg('system', `이동 동기화 실패: ${e.message}`);
            }
        };
        scene3dInitialized = true;
        // Load scene data
        refresh3DView();
    };
    tryInit();
}

let _3dLoading = false;
async function refresh3DView() {
    if (!window.sceneViewer || !window.sceneViewer.initialized) return;
    if (_3dLoading) return;  // prevent overlapping requests
    _3dLoading = true;
    try {
        setFooterStatus('Loading 3D scene...');
        const data = await window.sceneViewer.loadFromAPI();
        if (data) {
            const count = (data.objects || []).length;
            if (count > 0) setFooterStatus(`3D: ${count} objects loaded`);
            // Cache scene objects for equipment selection events
            _sceneObjects = {};
            for (const obj of (data.objects || [])) {
                if (obj.name) _sceneObjects[obj.name] = obj;
            }
        }
        // Re-apply persistent color overrides after scene reload
        const overrideCount = Object.keys(_colorOverrides).length;
        if (overrideCount > 0 && window.sceneViewer) {
            let applied = 0;
            for (const [name, color] of Object.entries(_colorOverrides)) {
                if (window.sceneViewer.updateObjectColor(name, color)) applied++;
            }
            if (applied > 0) console.log(`[3D] Re-applied ${applied}/${overrideCount} color overrides`);
        }
    } finally {
        _3dLoading = false;
    }
}

async function refreshSceneView() {
    if (sceneViewMode === '3d') {
        refresh3DView();
        return;
    }
    try {
        // Trigger screenshot first
        await fetch(`${API}/api/screenshot`, { method: 'POST' });
        // Small delay then load
        setTimeout(async () => {
            const img = document.getElementById('sceneImage');
            const placeholder = document.getElementById('scenePlaceholder');
            img.src = `${API}/api/screenshots/latest?t=${Date.now()}`;
            img.style.display = 'block';
            if (placeholder) placeholder.style.display = 'none';
            img.onerror = () => {
                img.style.display = 'none';
                if (placeholder) placeholder.style.display = 'flex';
            };
        }, 500);
    } catch (e) {
        addChatMsg('system', `Screenshot failed: ${e.message}`);
    }
}

function toggleSceneAutoRefresh() {
    sceneAutoRefresh = !sceneAutoRefresh;
    const btn = document.getElementById('autoRefreshBtn');
    btn.style.color = sceneAutoRefresh ? 'var(--success)' : '';
    if (sceneAutoRefresh) {
        const interval = sceneViewMode === '3d' ? 30000 : 5000;
        sceneRefreshTimer = setInterval(refreshSceneView, interval);
    } else {
        clearInterval(sceneRefreshTimer);
    }
}

// ── Minimap ─────────────────────────────────────────────────

function hideMinimap() {
    const overlay = document.getElementById('minimapOverlay');
    if (overlay) overlay.style.display = 'none';
}

function updateMinimap(plan) {
    if (!minimapRenderer || !plan?.actions) return;
    const overlay = document.getElementById('minimapOverlay');
    const newObjects = [];
    for (const action of plan.actions) {
        const pos = action.position || action.pos;
        if (pos) {
            newObjects.push({
                name: action.name || action.target || '',
                x: pos.x || 0, z: pos.z || 0,
                width: action.scale?.x || 1, depth: action.scale?.z || 1,
            });
        }
    }
    if (newObjects.length > 0) {
        overlay.style.display = 'block';
        fetch(`${API}/api/scene/context`).then(r => r.json()).then(ctx => {
            const objects = ctx.objects || {};
            const existing = Object.values(objects).map(o => ({
                name: o.name || '', x: o.position?.x || 0, z: o.position?.z || 0,
                width: o.scale?.x || 1, depth: o.scale?.z || 1,
            }));
            minimapRenderer.render(newObjects, existing);
        }).catch(() => minimapRenderer.render(newObjects, []));
    }
}

// ── Panel Switching ─────────────────────────────────────────

function switchPanel(side, name) {
    const panel = side === 'left' ? document.getElementById('panelLeft') : document.getElementById('panelRight');
    panel.querySelectorAll('.ptab').forEach(t => t.classList.toggle('active', t.dataset.panel === name));
    panel.querySelectorAll('.panel-body').forEach(b => b.classList.toggle('active', b.id === `${side}-${name}`));
}

function switchJobTab(name) {
    document.querySelectorAll('.jtab').forEach(t => t.classList.toggle('active', t.textContent.toLowerCase() === name));
    document.querySelectorAll('.jtab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`jtab-${name}`).classList.add('active');
    if (name === 'console') refreshConsole();
}

// ── File Browser ────────────────────────────────────────────

let _pinnedDirs = [];
let _recentDirs = [];
let _favsCollapsed = false;

async function loadFiles(path) {
    if (!path) return;
    currentFilePath = path;
    selectedFiles.clear();
    updateSelectionBar();

    // Update address bar
    const pathInput = document.getElementById('filePathInput');
    if (pathInput) pathInput.value = path.replace(/\\/g, '/');

    // Track recent dirs (max 10, no duplicates)
    const normPath = path.replace(/\\/g, '/');
    _recentDirs = _recentDirs.filter(p => p !== normPath);
    _recentDirs.unshift(normPath);
    if (_recentDirs.length > 10) _recentDirs.pop();

    // Update pin button state
    updatePinButton();

    const listEl = document.getElementById('fileList');
    listEl.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';

    try {
        const data = await (await fetch(`${API}/api/files?path=${encodeURIComponent(path)}`)).json();
        listEl.innerHTML = '';

        for (const entry of data.entries) {
            const div = document.createElement('div');
            div.className = `file-item ${entry.is_dir ? 'folder' : ''}`;
            div.dataset.path = entry.path;

            const icon = entry.is_dir ? '&#128193;' :
                entry.category === '3d_model' ? '&#128302;' :
                entry.category === 'texture' ? '&#127912;' :
                entry.category === 'script' ? '&#128196;' : '&#128196;';

            const size = !entry.is_dir && entry.size ? formatSize(entry.size) : '';

            if (entry.is_dir) {
                div.innerHTML = `<span class="file-icon">${icon}</span><span class="file-name">${esc(entry.name)}</span>`;
                div.onclick = () => loadFiles(entry.path);
            } else {
                div.innerHTML = `
                    <input type="checkbox" class="file-checkbox" data-path="${esc(entry.path)}" onclick="event.stopPropagation()">
                    <span class="file-icon">${icon}</span>
                    <span class="file-name">${esc(entry.name)}</span>
                    <span class="file-meta">${size}</span>
                `;
                const cb = div.querySelector('.file-checkbox');
                cb.addEventListener('change', e => {
                    if (e.target.checked) selectedFiles.add(entry.path);
                    else selectedFiles.delete(entry.path);
                    div.classList.toggle('checked', e.target.checked);
                    updateSelectionBar();
                });
                div.onclick = e => {
                    if (e.target.classList.contains('file-checkbox')) return;
                    document.getElementById('chatInput').value = `Import ${entry.name} from ${entry.path}`;
                };

                if (sourcePicker && ['3d_model', 'texture', 'data', 'scene', 'prefab'].includes(entry.category)) {
                    sourcePicker.enhanceFileItem(div, entry.path);
                }
            }
            listEl.appendChild(div);
        }
        if (data.entries.length === 0) listEl.innerHTML = '<div class="empty-state"><p>Empty directory</p></div>';
    } catch (e) {
        listEl.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
    }
}

function updateSelectionBar() {
    const bar = document.getElementById('selectionBar');
    if (!bar) return;
    if (selectedFiles.size > 0) {
        bar.style.display = 'flex';
        document.getElementById('selCount').textContent = `${selectedFiles.size} selected`;
    } else {
        bar.style.display = 'none';
    }
}

function deselectAllFiles() {
    selectedFiles.clear();
    document.querySelectorAll('.file-checkbox').forEach(cb => {
        cb.checked = false;
        cb.closest('.file-item')?.classList.remove('checked');
    });
    updateSelectionBar();
}

function navigateUp() {
    if (!currentFilePath) return;
    const parts = currentFilePath.replace(/\\/g, '/').split('/');
    if (parts.length > 1) { parts.pop(); loadFiles(parts.join('/') || parts[0] + '/'); }
}

function navigateHome() {
    fetch(`${API}/api/workdir`).then(r => r.json()).then(data => {
        if (data.path) loadFiles(data.path);
    }).catch(() => {});
}

function navigateToPath(path) {
    path = (path || '').trim();
    if (!path) return;
    // Normalize: accept both \ and /
    path = path.replace(/\\/g, '/');
    loadFiles(path);
}

// ── Favorites / Bookmarks ───────────────────────────────────

async function loadFavorites() {
    try {
        const data = await (await fetch(`${API}/api/workdir`)).json();
        _pinnedDirs = (data.pinned || []).map(p => p.replace(/\\/g, '/'));
        renderFavorites();
        updatePinButton();
    } catch {}
}

async function loadDrives() {
    try {
        const data = await (await fetch(`${API}/api/files/drives`)).json();
        const el = document.getElementById('favDrives');
        if (!el || !data.drives) return;
        el.innerHTML = '';
        for (const d of data.drives) {
            const btn = document.createElement('button');
            btn.className = 'drive-btn';
            btn.textContent = `${d.letter}:`;
            btn.title = d.path;
            btn.onclick = () => loadFiles(d.path);
            el.appendChild(btn);
        }
    } catch {}
}

function renderFavorites() {
    const listEl = document.getElementById('favList');
    if (!listEl) return;
    listEl.innerHTML = '';

    if (_pinnedDirs.length === 0 && _recentDirs.length === 0) {
        listEl.innerHTML = '<div style="padding:4px 12px;font-size:10px;color:var(--text-3)">No bookmarks yet</div>';
        return;
    }

    const currentNorm = (currentFilePath || '').replace(/\\/g, '/');

    // Pinned dirs
    for (const p of _pinnedDirs) {
        const shortName = p.split('/').filter(Boolean).slice(-1)[0] || p;
        const isActive = p === currentNorm;
        const div = document.createElement('div');
        div.className = `fav-item${isActive ? ' active' : ''}`;
        div.innerHTML = `
            <span class="fav-item-icon">&#9733;</span>
            <span class="fav-item-name" title="${esc(p)}">${esc(shortName)}</span>
            <span class="fav-item-path">${esc(p.split('/').slice(0, -1).slice(-1)[0] || '')}</span>
            <span class="fav-unpin" onclick="event.stopPropagation(); unpinDir('${esc(p)}')" title="Remove">&times;</span>
        `;
        div.onclick = () => loadFiles(p);
        listEl.appendChild(div);
    }

    // Recent dirs (that aren't already pinned), max 5
    const unpinnedRecent = _recentDirs.filter(p => !_pinnedDirs.includes(p)).slice(0, 5);
    if (unpinnedRecent.length > 0) {
        const sep = document.createElement('div');
        sep.style.cssText = 'padding:2px 12px;font-size:9px;color:var(--text-3);border-top:1px solid rgba(255,255,255,0.04);margin-top:2px;';
        sep.textContent = 'Recent';
        listEl.appendChild(sep);

        for (const p of unpinnedRecent) {
            const shortName = p.split('/').filter(Boolean).slice(-1)[0] || p;
            const isActive = p === currentNorm;
            const div = document.createElement('div');
            div.className = `fav-item${isActive ? ' active' : ''}`;
            div.innerHTML = `
                <span class="fav-item-icon" style="opacity:0.4">&#128337;</span>
                <span class="fav-item-name" title="${esc(p)}">${esc(shortName)}</span>
                <span class="fav-item-path">${esc(p.split('/').slice(0, -1).slice(-1)[0] || '')}</span>
                <span class="fav-unpin" onclick="event.stopPropagation(); pinDir('${esc(p)}')" title="Pin" style="opacity:1;color:var(--text-3)">&#9734;</span>
            `;
            div.onclick = () => loadFiles(p);
            listEl.appendChild(div);
        }
    }
}

function toggleFavorites() {
    _favsCollapsed = !_favsCollapsed;
    const list = document.getElementById('favList');
    const drives = document.getElementById('favDrives');
    const toggle = document.getElementById('favToggle');
    if (list) list.classList.toggle('collapsed', _favsCollapsed);
    if (drives) drives.style.display = _favsCollapsed ? 'none' : '';
    if (toggle) toggle.classList.toggle('collapsed', _favsCollapsed);
}

function updatePinButton() {
    const btn = document.getElementById('pinCurrentBtn');
    if (!btn) return;
    const currentNorm = (currentFilePath || '').replace(/\\/g, '/');
    const isPinned = _pinnedDirs.includes(currentNorm);
    btn.innerHTML = isPinned ? '&#9733;' : '&#9734;';
    btn.classList.toggle('pinned', isPinned);
    btn.title = isPinned ? 'Remove bookmark' : 'Add bookmark';
}

async function togglePinCurrent() {
    const currentNorm = (currentFilePath || '').replace(/\\/g, '/');
    if (!currentNorm) return;
    const isPinned = _pinnedDirs.includes(currentNorm);
    if (isPinned) {
        await unpinDir(currentNorm);
    } else {
        await pinDir(currentNorm);
    }
}

async function pinDir(path) {
    try {
        const resp = await fetch(`${API}/api/workdir/pin`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        const data = await resp.json();
        _pinnedDirs = (data.pinned || []).map(p => p.replace(/\\/g, '/'));
        renderFavorites();
        updatePinButton();
    } catch {}
}

async function unpinDir(path) {
    try {
        const resp = await fetch(`${API}/api/workdir/unpin`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        const data = await resp.json();
        _pinnedDirs = (data.pinned || []).map(p => p.replace(/\\/g, '/'));
        renderFavorites();
        updatePinButton();
    } catch {}
}

async function compositeAnalyze() {
    if (selectedFiles.size === 0) return;
    const filePaths = Array.from(selectedFiles);
    addChatMsg('user', `Analyze ${filePaths.length} files`);

    try {
        const resp = await fetch(`${API}/api/source/composite-analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_paths: filePaths, generate_plan: true }),
        });
        const data = await resp.json();
        addChatMsg('system', data.summary || `Analyzed ${data.files?.length || 0} files`);
        if (data.composite_plan?.actions?.length > 0) {
            showPlanInChat(data.composite_plan, 'composite');
        }
    } catch (e) {
        addChatMsg('system', `Analysis error: ${e.message}`);
    }
}

// ── Drawing Viewer ──────────────────────────────────────────

let loadedDrawingPath = '';

function loadDrawing(event) {
    const file = event.target.files[0];
    if (!file) return;
    loadedDrawingPath = file.name;  // Will need server-side path
    const reader = new FileReader();
    reader.onload = (e) => {
        const img = document.getElementById('drawingImage');
        img.src = e.target.result;
        document.getElementById('drawingDrop').style.display = 'none';
        document.getElementById('drawingPreview').style.display = 'block';
    };
    reader.readAsDataURL(file);
}

async function analyzeDrawing() {
    if (!loadedDrawingPath) return;
    addChatMsg('system', `Analyzing drawing: ${loadedDrawingPath}...`);
    try {
        const resp = await fetch(`${API}/api/drawing/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_path: loadedDrawingPath }),
        });
        const data = await resp.json();
        const resultEl = document.getElementById('drawingResult');
        document.getElementById('drawingData').textContent = JSON.stringify(data.analysis, null, 2);
        resultEl.style.display = 'block';
        addChatMsg('assistant', `Drawing analysis complete. Found ${Object.keys(data.analysis || {}).length} categories.`);
    } catch (e) {
        addChatMsg('system', `Analysis failed: ${e.message}`);
    }
}

function clearDrawing() {
    document.getElementById('drawingDrop').style.display = 'flex';
    document.getElementById('drawingPreview').style.display = 'none';
    document.getElementById('drawingResult').style.display = 'none';
    loadedDrawingPath = '';
}

// ── Presets ──────────────────────────────────────────────────

let presetsData = [];
let currentPreset = null;

async function loadPresets() {
    try {
        const data = await (await fetch(`${API}/api/presets`)).json();
        presetsData = data.presets;
        renderPresets();
    } catch {}
}

function renderPresets() {
    const el = document.getElementById('presetList');
    el.innerHTML = '';
    const icons = { cube: '&#9724;', light: '&#128161;', palette: '&#127912;', scene: '&#127758;', factory: '&#127981;' };

    for (const group of presetsData) {
        const groupDiv = document.createElement('div');
        groupDiv.className = 'preset-group';
        groupDiv.innerHTML = `<div class="preset-group-title">${esc(group.category)}</div>`;

        for (const item of group.items) {
            const itemDiv = document.createElement('div');
            itemDiv.className = 'preset-item';
            itemDiv.innerHTML = `<span class="preset-icon">${icons[group.icon] || '&#9656;'}</span> ${esc(item.label)}`;

            if (Object.keys(item.params).length > 0) {
                itemDiv.onclick = () => showPresetDialog(item);
            } else {
                itemDiv.onclick = () => {
                    document.getElementById('chatInput').value = item.command;
                    document.getElementById('chatInput').focus();
                };
            }
            groupDiv.appendChild(itemDiv);
        }
        el.appendChild(groupDiv);
    }
}

function showPresetDialog(preset) {
    currentPreset = preset;
    document.getElementById('presetDialogTitle').textContent = preset.label;
    const paramsEl = document.getElementById('presetDialogParams');
    paramsEl.innerHTML = '';
    for (const [key, val] of Object.entries(preset.params)) {
        const field = document.createElement('div');
        field.className = 'param-field';
        field.innerHTML = `<label>${key}</label><input type="text" id="param-${key}" value="${esc(val)}">`;
        paramsEl.appendChild(field);
    }
    document.getElementById('presetDialog').style.display = 'flex';
}

function hidePresetDialog() {
    document.getElementById('presetDialog').style.display = 'none';
    currentPreset = null;
}

function applyPreset() {
    if (!currentPreset) return;
    let cmd = currentPreset.command;
    for (const key of Object.keys(currentPreset.params)) {
        const input = document.getElementById(`param-${key}`);
        if (input) cmd = cmd.replace(`{${key}}`, input.value);
    }
    document.getElementById('chatInput').value = cmd;
    document.getElementById('chatInput').focus();
    hidePresetDialog();
}

// ── Component Library ───────────────────────────────────────

async function loadComponents() {
    try {
        const data = await (await fetch(`${API}/api/components`)).json();
        renderComponents(data.categories);
    } catch {}
}

function renderComponents(categories) {
    const el = document.getElementById('componentLibrary');
    el.innerHTML = '';

    const catIcons = {
        'Vessels': '&#129516;', 'Valves': '&#128295;', 'Pumps': '&#9881;',
        'Heat Exchangers': '&#9832;', 'Safety': '&#9888;', 'Instruments': '&#128200;',
        'Piping': '&#9552;', 'Steam': '&#9729;',
    };

    for (const cat of categories) {
        const catDiv = document.createElement('div');
        catDiv.className = 'comp-category';
        catDiv.innerHTML = `<div class="comp-category-title">${catIcons[cat.name] || '&#9656;'} ${esc(cat.name)}</div>`;

        for (const tmpl of cat.templates) {
            const card = document.createElement('div');
            card.className = 'comp-card';
            card.innerHTML = `
                <div class="comp-icon">${catIcons[cat.name] || '&#9724;'}</div>
                <div class="comp-info">
                    <div class="comp-name">${esc(tmpl.name || tmpl.id)}</div>
                    <div class="comp-desc">${esc(tmpl.description || '')}</div>
                </div>
            `;
            card.onclick = () => showComponentModal(tmpl);
            catDiv.appendChild(card);
        }
        el.appendChild(catDiv);
    }

    if (categories.length === 0) {
        el.innerHTML = '<div class="empty-state"><p>No components available</p></div>';
    }
}

function showComponentModal(tmpl) {
    currentComponentId = tmpl.id;
    document.getElementById('compModalTitle').textContent = tmpl.name || tmpl.id;
    const body = document.getElementById('compModalBody');
    body.innerHTML = '';

    if (tmpl.description) {
        const desc = document.createElement('p');
        desc.style.cssText = 'font-size:11px;color:var(--text-2);margin-bottom:8px';
        desc.textContent = tmpl.description;
        body.appendChild(desc);
    }

    // Render parameter inputs
    if (tmpl.params) {
        const paramsDiv = document.createElement('div');
        paramsDiv.className = 'comp-params';
        for (const [key, def] of Object.entries(tmpl.params)) {
            const row = document.createElement('div');
            row.className = 'comp-param';
            row.innerHTML = `
                <label>${esc(key)}</label>
                <input type="text" id="comp-param-${key}" value="${esc(String(def.default !== undefined ? def.default : ''))}">
            `;
            paramsDiv.appendChild(row);
        }
        body.appendChild(paramsDiv);
    }

    document.getElementById('componentModal').style.display = 'flex';
}

function hideComponentModal() {
    document.getElementById('componentModal').style.display = 'none';
    currentComponentId = null;
}

async function instantiateComponent() {
    if (!currentComponentId) return;
    const params = {};
    document.querySelectorAll('[id^="comp-param-"]').forEach(input => {
        const key = input.id.replace('comp-param-', '');
        const val = input.value;
        params[key] = isNaN(val) ? val : parseFloat(val);
    });

    hideComponentModal();
    addChatMsg('user', `Create component: ${currentComponentId}`);

    try {
        const resp = await fetch(`${API}/api/components/instantiate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template_id: currentComponentId, params }),
        });
        const data = await resp.json();
        addChatMsg('system', `Component created: ${data.result?.success_count || 0}/${data.result?.total_actions || 0} actions`);
        addJob({
            job_id: data.job_id, command: `Component: ${currentComponentId}`,
            status: data.result?.status || 'completed',
            detail: `${data.result?.success_count || 0} actions`,
        });
        refreshSceneView();
        refreshHierarchy();
    } catch (e) {
        addChatMsg('system', `Component creation failed: ${e.message}`);
    }
}

// ── Hierarchy ───────────────────────────────────────────────

async function refreshHierarchy() {
    const tree = document.getElementById('hierarchyTree');
    tree.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';

    try {
        const resp = await fetch(`${API}/api/hierarchy?max_depth=4`);
        const data = await resp.json();
        tree.innerHTML = '';

        const content = data?.result?.content || [];
        for (const item of content) {
            if (item.type === 'text') {
                try {
                    const parsed = JSON.parse(item.text);
                    const hierarchy = parsed.hierarchy || parsed.data?.hierarchy;
                    if (hierarchy) { renderTreeNode(tree, hierarchy, 0); return; }
                } catch {
                    const pre = document.createElement('pre');
                    pre.style.cssText = 'color:var(--text-3);font-size:10px;padding:6px;white-space:pre-wrap;';
                    pre.textContent = item.text;
                    tree.appendChild(pre);
                    return;
                }
            }
        }
        tree.innerHTML = '<div class="empty-state"><p>No hierarchy data</p></div>';
    } catch (e) {
        tree.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
    }
}

function renderTreeNode(container, node, depth) {
    if (!node) return;
    const div = document.createElement('div');
    div.className = 'tree-node';

    const children = node.children || node.Children || [];
    const hasChildren = children.length > 0;
    const name = node.name || node.Name || '(root)';

    const row = document.createElement('div');
    row.className = 'node-row';
    row.innerHTML = `
        <span class="node-toggle">${hasChildren ? '&#9660;' : '&nbsp;'}</span>
        <span class="node-icon">${hasChildren ? '&#128193;' : '&#9726;'}</span>
        <span class="node-name">${esc(name)}</span>
        ${hasChildren ? `<span class="node-count">(${children.length})</span>` : ''}
    `;

    row.onclick = (e) => {
        e.stopPropagation();
        document.querySelectorAll('.node-row.selected').forEach(el => el.classList.remove('selected'));
        row.classList.add('selected');
        selectedObject = name;
        inspectObject(name);
        setTargetTag(name);
    };

    div.appendChild(row);

    if (hasChildren) {
        const childContainer = document.createElement('div');
        childContainer.className = 'tree-children';
        let expanded = depth < 1;
        childContainer.style.display = expanded ? 'block' : 'none';
        const toggle = row.querySelector('.node-toggle');
        toggle.style.transform = expanded ? '' : 'rotate(-90deg)';
        toggle.onclick = (e) => {
            e.stopPropagation();
            expanded = !expanded;
            childContainer.style.display = expanded ? 'block' : 'none';
            toggle.style.transform = expanded ? '' : 'rotate(-90deg)';
        };
        for (const child of children) renderTreeNode(childContainer, child, depth + 1);
        div.appendChild(childContainer);
    }
    container.appendChild(div);
}

function filterHierarchy() {
    const term = document.getElementById('hierarchySearch').value.toLowerCase();
    document.querySelectorAll('.tree-node .node-row').forEach(row => {
        const name = row.querySelector('.node-name')?.textContent.toLowerCase() || '';
        const node = row.parentElement;
        if (!term || name.includes(term)) {
            node.style.display = '';
            let parent = node.parentElement;
            while (parent && parent.classList.contains('tree-children')) {
                parent.style.display = 'block';
                parent = parent.parentElement?.parentElement;
            }
        } else {
            node.style.display = 'none';
        }
    });
}

// ── Inspector ───────────────────────────────────────────────

async function inspectObject(name) {
    const body = document.getElementById('inspectorBody');
    body.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';

    try {
        const resp = await fetch(`${API}/api/object/inspect?target=${encodeURIComponent(name)}&search_method=by_name`);
        const data = await resp.json();

        const content = data?.result?.content || [];
        let objInfo = null;
        for (const item of content) {
            if (item.type === 'text') {
                try {
                    const parsed = JSON.parse(item.text);
                    if (parsed.data?.results) objInfo = parsed.data.results[0];
                    else if (parsed.data) objInfo = parsed.data;
                    else objInfo = parsed;
                } catch {}
            }
        }

        if (!objInfo) { body.innerHTML = `<div class="empty-state"><p>"${esc(name)}" not found</p></div>`; return; }

        const t = objInfo.transform || {};
        const pos = t.position || t.localPosition || {};
        const rot = t.rotation || t.localRotation || {};
        const scl = t.scale || t.localScale || {};

        body.innerHTML = `
            <div style="font-weight:600;margin-bottom:4px;color:var(--accent);font-size:12px">${esc(objInfo.name || name)}</div>
            <div class="inspector-field">
                <span class="inspector-label">Pos</span>
                <div class="inspector-value">
                    <input id="insp-px" value="${(pos.x||0).toFixed(2)}">
                    <input id="insp-py" value="${(pos.y||0).toFixed(2)}">
                    <input id="insp-pz" value="${(pos.z||0).toFixed(2)}">
                </div>
            </div>
            <div class="inspector-field">
                <span class="inspector-label">Rot</span>
                <div class="inspector-value">
                    <input id="insp-rx" value="${(rot.x||0).toFixed(1)}">
                    <input id="insp-ry" value="${(rot.y||0).toFixed(1)}">
                    <input id="insp-rz" value="${(rot.z||0).toFixed(1)}">
                </div>
            </div>
            <div class="inspector-field">
                <span class="inspector-label">Scale</span>
                <div class="inspector-value">
                    <input id="insp-sx" value="${(scl.x||1).toFixed(2)}">
                    <input id="insp-sy" value="${(scl.y||1).toFixed(2)}">
                    <input id="insp-sz" value="${(scl.z||1).toFixed(2)}">
                </div>
            </div>
            <div class="inspector-actions">
                <button class="btn btn-xs btn-primary" onclick="applyInspectorTransform()">Apply</button>
                <button class="btn btn-xs" onclick="duplicateSelected()">Duplicate</button>
                <button class="btn btn-xs" style="color:var(--error)" onclick="deleteSelected()">Delete</button>
            </div>
        `;
    } catch (e) {
        body.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
    }
}

async function applyInspectorTransform() {
    if (!selectedObject) return;
    const pos = {
        x: parseFloat(document.getElementById('insp-px')?.value || 0),
        y: parseFloat(document.getElementById('insp-py')?.value || 0),
        z: parseFloat(document.getElementById('insp-pz')?.value || 0),
    };
    const rot = {
        x: parseFloat(document.getElementById('insp-rx')?.value || 0),
        y: parseFloat(document.getElementById('insp-ry')?.value || 0),
        z: parseFloat(document.getElementById('insp-rz')?.value || 0),
    };
    const scale = {
        x: parseFloat(document.getElementById('insp-sx')?.value || 1),
        y: parseFloat(document.getElementById('insp-sy')?.value || 1),
        z: parseFloat(document.getElementById('insp-sz')?.value || 1),
    };

    try {
        await fetch(`${API}/api/object/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: selectedObject, search_method: 'by_name', action: 'modify', position: pos, rotation: rot, scale }),
        });
        addChatMsg('system', `Modified ${selectedObject}`);
        refreshSceneView();
    } catch (e) {
        addChatMsg('system', `Modify failed: ${e.message}`);
    }
}

// ── Job Log ─────────────────────────────────────────────────

function addJob(entry) {
    const el = document.getElementById('jobLog');
    const empty = el.querySelector('.empty-state');
    if (empty) empty.remove();

    const cls = entry.status === 'completed' ? 'success'
        : entry.status === 'failed' || entry.status === 'validation_failed' ? 'failed'
        : entry.status === 'rejected' ? 'failed'
        : entry.status === 'plan_ready' ? 'executing'
        : entry.status === 'response' ? 'success'
        : entry.status === 'partial' ? 'partial' : 'executing';

    const label = { completed: 'OK', failed: 'FAIL', validation_failed: 'INVALID', partial: 'PART', executing: 'RUN', plan_ready: 'PLAN', rejected: 'SKIP', response: 'AI' }[entry.status] || entry.status;

    const div = document.createElement('div');
    div.className = `job-item ${cls}`;
    div.id = entry.job_id ? `job-${entry.job_id}` : '';
    const undoBtn = entry.undo_available && entry.job_id
        ? `<button class="undo-btn" onclick="event.stopPropagation(); undoJob('${esc(entry.job_id)}')">undo</button>`
        : '';
    div.innerHTML = `
        <div class="job-main">
            <div class="job-command">${esc(entry.command)}</div>
            <div class="job-detail">${esc(entry.detail || '')}</div>
        </div>
        <div class="job-meta">
            ${undoBtn}
            <span class="badge ${cls}">${label}</span>
        </div>
    `;
    el.insertBefore(div, el.firstChild);
    document.getElementById('jobCountFooter').textContent = el.querySelectorAll('.job-item').length;
}

function updateJob(data) {
    const existing = document.getElementById(`job-${data.job_id}`);
    if (existing) existing.remove();
    addJob({
        job_id: data.job_id, command: data.command || '(job)',
        status: data.status,
        detail: `${data.success || 0}/${data.total || 0} actions | ${data.duration_s || 0}s`,
        undo_available: data.undo_available || false,
        result: data,
    });
}

// Make globally accessible
window.addJob = addJob;
window.showPlan = showPlanInChat;

// ── Quick Actions ───────────────────────────────────────────

async function takeScreenshot() {
    try {
        await fetch(`${API}/api/screenshot`, { method: 'POST' });
        addChatMsg('system', 'Screenshot saved');
        refreshSceneView();
    } catch (e) {
        addChatMsg('system', `Screenshot failed: ${e.message}`);
    }
}

async function saveScene() {
    try {
        await fetch(`${API}/api/scene/save`, { method: 'POST' });
        addChatMsg('system', 'Scene saved');
    } catch (e) {
        addChatMsg('system', `Save failed: ${e.message}`);
    }
}

let _undoInProgress = false;

async function undoLast() {
    if (_undoInProgress) return; // prevent duplicate calls
    if (_lastCompletedJobId) {
        await undoJob(_lastCompletedJobId);
    } else {
        // Fallback: find the most recent undo button in job list
        const lastBtn = document.querySelector('.job-item .undo-btn');
        if (lastBtn) lastBtn.click();
        else addChatMsg('system', '되돌릴 수 있는 작업이 없습니다.');
    }
}

async function undoJob(jobId) {
    if (_undoInProgress) return;
    _undoInProgress = true;

    // Immediately clear to prevent duplicate calls
    if (_lastCompletedJobId === jobId) _lastCompletedJobId = null;

    addChatMsg('system', `작업 ${jobId} 되돌리는 중...`);
    try {
        const resp = await fetch(`${API}/api/undo/${jobId}`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            addChatMsg('system', `되돌리기 실패: ${err.detail || resp.statusText}`);
            return;
        }
        const data = await resp.json();
        const count = data.result?.success_count || 0;
        addChatMsg('system', `되돌리기 완료: ${count}개 작업이 복원되었습니다.`);

        // Remove undo button from approval card if exists
        const card = document.getElementById(`approval-${jobId}`);
        if (card) {
            const undoBtn = card.querySelector('.approval-btn.undo');
            if (undoBtn) undoBtn.remove();
        }

        // Remove undo button from job list as well
        const jobEl = document.getElementById(`job-${jobId}`);
        if (jobEl) {
            const undoBtn = jobEl.querySelector('.undo-btn');
            if (undoBtn) undoBtn.remove();
        }

        await refreshHierarchy();
        refreshSceneView();
    } catch (e) {
        addChatMsg('system', `되돌리기 실패: ${e.message}`);
    } finally {
        _undoInProgress = false;
    }
}

async function togglePlay() {
    // Send play/stop command via natural language
    document.getElementById('chatInput').value = 'Play mode toggle';
    sendChat();
}

// ── WebGL Viewer Setup & Build ──────────────────────────────

async function webglSetup() {
    const btn = document.getElementById('webglSetupBtn');
    if (btn) btn.disabled = true;
    addChatMsg('system', 'WebGL Viewer 설치 플랜을 생성 중...');
    try {
        const resp = await fetch(`${API}/api/webgl/setup`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            addChatMsg('system', `WebGL Setup 실패: ${data.detail || resp.statusText}`);
            return;
        }
        if (data.status === 'plan_ready' && data.plan) {
            showApprovalCard(data.job_id, data.plan, data.message || 'WebGL Viewer 설치');
        }
    } catch (e) {
        addChatMsg('system', `WebGL Setup 오류: ${e.message}`);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function webglBuild() {
    const defaultPath = 'C:\\Users\\User\\works\\WebGL';
    const outputPath = prompt('WebGL 빌드 출력 경로를 입력하세요:', defaultPath);
    if (!outputPath) return;

    const btn = document.getElementById('webglBuildBtn');
    if (btn) btn.disabled = true;
    addChatMsg('system', `WebGL 빌드 플랜 생성 중... → ${outputPath}`);
    try {
        const resp = await fetch(`${API}/api/webgl/build`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ output_path: outputPath }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            addChatMsg('system', `WebGL Build 실패: ${data.detail || resp.statusText}`);
            return;
        }
        if (data.status === 'plan_ready' && data.plan) {
            showApprovalCard(data.job_id, data.plan, data.message || 'WebGL 빌드');
        }
    } catch (e) {
        addChatMsg('system', `WebGL Build 오류: ${e.message}`);
    } finally {
        if (btn) btn.disabled = false;
    }
}

// Poll WebGL build status after build is triggered
let _webglBuildPollTimer = null;
function startWebglBuildPoll() {
    stopWebglBuildPoll();
    addChatMsg('system', '📦 WebGL 빌드 진행 중... (상태 모니터링 시작)');
    const btn = document.getElementById('webglBuildBtn');
    if (btn) btn.classList.add('active');

    _webglBuildPollTimer = setInterval(async () => {
        try {
            const data = await (await fetch(`${API}/api/webgl/build-status`)).json();
            if (data.status === 'completed') {
                stopWebglBuildPoll();
                const dur = data.duration_s ? ` (${data.duration_s}s)` : '';
                addChatMsg('system', `✅ WebGL 빌드 완료${dur}: ${data.message || ''}`);
                if (btn) btn.classList.remove('active');
            } else if (data.status === 'failed') {
                stopWebglBuildPoll();
                addChatMsg('system', `❌ WebGL 빌드 실패: ${data.message || ''}`);
                if (btn) btn.classList.remove('active');
            }
            // 'building' status — keep polling
        } catch {
            // ignore fetch errors during polling
        }
    }, 5000); // Poll every 5 seconds
}

function stopWebglBuildPoll() {
    if (_webglBuildPollTimer) {
        clearInterval(_webglBuildPollTimer);
        _webglBuildPollTimer = null;
    }
}

async function checkWebglStatus() {
    try {
        const data = await (await fetch(`${API}/api/webgl/status`)).json();
        const setupBtn = document.getElementById('webglSetupBtn');
        if (setupBtn) {
            setupBtn.classList.toggle('active', !!data.installed);
            setupBtn.title = data.installed
                ? 'WebGL Viewer (installed)'
                : 'WebGL Viewer Setup';
        }
        return data;
    } catch {
        return { installed: false };
    }
}

function toggleMoveMode() {
    if (!window.sceneViewer || !window.sceneViewer.initialized) {
        addChatMsg('system', '3D 뷰가 초기화되지 않았습니다.');
        return;
    }
    const enabled = window.sceneViewer.toggleMoveMode();
    const btn = document.getElementById('moveModeBtn');
    if (btn) {
        btn.classList.toggle('active', enabled);
        btn.title = enabled ? 'Move Mode ON (W)' : 'Move Mode OFF (W)';
    }
    addChatMsg('system', enabled
        ? '이동 모드 ON — 오브젝트를 클릭하고 기즈모를 드래그하여 이동하세요.'
        : '이동 모드 OFF — 뷰 모드로 전환되었습니다.');
}

async function deleteSelected() {
    if (!selectedObject) return;
    if (!confirm(`Delete "${selectedObject}"?`)) return;
    try {
        await fetch(`${API}/api/object/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: selectedObject, search_method: 'by_name', action: 'delete' }),
        });
        addChatMsg('system', `Deleted ${selectedObject}`);
        selectedObject = null;
        refreshHierarchy();
        refreshSceneView();
    } catch (e) {
        addChatMsg('system', `Delete failed: ${e.message}`);
    }
}

async function duplicateSelected() {
    if (!selectedObject) return;
    try {
        await fetch(`${API}/api/object/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: selectedObject, search_method: 'by_name', action: 'duplicate' }),
        });
        addChatMsg('system', `Duplicated ${selectedObject}`);
        refreshHierarchy();
    } catch (e) {
        addChatMsg('system', `Duplicate failed: ${e.message}`);
    }
}

async function refreshConsole() {
    const el = document.getElementById('consoleLog');
    el.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';
    try {
        const data = await (await fetch(`${API}/api/console?count=50`)).json();
        el.innerHTML = '';
        const content = data?.result?.content || [];
        for (const item of content) {
            if (item.type === 'text') {
                try {
                    const entries = JSON.parse(item.text);
                    if (Array.isArray(entries)) {
                        for (const entry of entries) {
                            const div = document.createElement('div');
                            const type = (entry.type || 'log').toLowerCase();
                            div.className = `console-entry ${type}`;
                            div.textContent = `[${type.toUpperCase()}] ${entry.message || entry}`;
                            el.appendChild(div);
                        }
                        return;
                    }
                } catch {
                    const div = document.createElement('div');
                    div.className = 'console-entry log';
                    div.textContent = item.text;
                    el.appendChild(div);
                }
            }
        }
    } catch (e) {
        el.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
    }
}

// ── Progress Handling ───────────────────────────────────────

function resetExecProgress() {
    const el = document.getElementById('execProgress');
    const fill = document.getElementById('execFill');
    const count = document.getElementById('execCount');
    const label = document.getElementById('execLabel');
    const steps = document.getElementById('execSteps');
    const spinner = document.getElementById('execSpinner');
    if (fill) fill.style.width = '0%';
    if (count) count.textContent = '0/0';
    if (label) label.textContent = 'Processing...';
    if (steps) steps.innerHTML = '';
    if (spinner) { spinner.textContent = '\u2699'; spinner.classList.remove('done'); }
    if (el) el.style.display = 'none';
}

const ACTION_LABELS = {
    create: 'Create', modify: 'Modify', delete: 'Delete', duplicate: 'Duplicate',
    move: 'Move', color: 'Color', material: 'Material', screenshot: 'Screenshot',
    save: 'Save', light: 'Light', import: 'Import',
};

function actionLabel(type) {
    if (!type) return '';
    return ACTION_LABELS[type.toLowerCase().replace(/^manage_/, '')] || type;
}

function updateActionProgress(current, total, actionType, status) {
    const el = document.getElementById('execProgress');
    const fill = document.getElementById('execFill');
    const count = document.getElementById('execCount');
    const label = document.getElementById('execLabel');
    const steps = document.getElementById('execSteps');
    const spinner = document.getElementById('execSpinner');

    if (!el || total <= 0) return;

    el.style.display = 'block';
    const pct = Math.min(100, Math.round((current / total) * 100));
    if (fill) fill.style.width = pct + '%';
    if (count) count.textContent = `${current}/${total}`;

    const lbl = actionLabel(actionType);
    if (current < total && label) {
        label.textContent = lbl ? `${lbl}...` : 'Executing...';
        if (spinner) spinner.classList.remove('done');
    }

    if (steps) {
        const stepId = `exec-step-${current}`;
        let stepEl = document.getElementById(stepId);
        if (!stepEl) {
            stepEl = document.createElement('div');
            stepEl.id = stepId;
            stepEl.className = 'exec-step active';
            stepEl.innerHTML = `<span class="exec-step-icon">\u25B6</span><span class="exec-step-label">${current}. ${lbl || 'Action'}</span>`;
            steps.appendChild(stepEl);
            stepEl.scrollIntoView({ block: 'nearest' });
        }
        const isDone = status === 'completed' || status === 'success';
        const isFail = status === 'failed' || status === 'error';
        if (isDone || isFail) {
            stepEl.classList.remove('active');
            stepEl.classList.add(isDone ? 'completed' : 'failed');
            stepEl.querySelector('.exec-step-icon').textContent = isDone ? '\u2713' : '\u2717';
        }
    }

    if (current >= total) {
        if (label) label.textContent = 'Complete!';
        if (spinner) { spinner.textContent = '\u2714'; spinner.classList.add('done'); }
        setTimeout(() => {
            if (el) el.style.display = 'none';
            if (steps) steps.innerHTML = '';
        }, 2500);
    }
}

function handleStageUpdate(data) {
    setFooterStatus(data.message || data.stage || '');
    const el = document.getElementById('execProgress');
    const label = document.getElementById('execLabel');
    if (el) el.style.display = 'block';
    if (label) label.textContent = data.message || '';
}

function handleCompositeProgress(data) {
    const el = document.getElementById('execProgress');
    const fill = document.getElementById('execFill');
    const count = document.getElementById('execCount');
    const label = document.getElementById('execLabel');

    if (el) el.style.display = 'block';
    if (label) label.textContent = data.detail || '';
    if (data.total > 0 && fill && count) {
        const pct = Math.min(100, Math.round((data.current / data.total) * 100));
        fill.style.width = pct + '%';
        count.textContent = `${data.current}/${data.total}`;
    }
    setFooterStatus(data.detail || '');
}

// ── Resize ──────────────────────────────────────────────────

let resizing = null;

function startResize(e, side) {
    e.preventDefault();
    resizing = side;
    document.addEventListener('mousemove', doResize);
    document.addEventListener('mouseup', stopResize);
}

function doResize(e) {
    if (!resizing) return;
    if (resizing === 'left') {
        const w = Math.max(180, Math.min(450, e.clientX));
        document.getElementById('panelLeft').style.width = w + 'px';
    } else if (resizing === 'right') {
        const w = Math.max(200, Math.min(500, window.innerWidth - e.clientX));
        document.getElementById('panelRight').style.width = w + 'px';
    }
}

function stopResize() {
    resizing = null;
    document.removeEventListener('mousemove', doResize);
    document.removeEventListener('mouseup', stopResize);
}

// ── Utils ───────────────────────────────────────────────────

function esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + 'B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(0) + 'KB';
    return (bytes / 1048576).toFixed(1) + 'MB';
}

// ── Equipment Selection (iframe → parent window) ────────────

function inferAssetType(name) {
    const n = name.toLowerCase();
    if (/ferment|reactor|tank|vessel|digest/.test(n)) return 'vessel';
    if (/valve/.test(n)) return 'valve';
    if (/pump/.test(n)) return 'pump';
    if (/pipe|duct/.test(n)) return 'pipe';
    if (/heat.*exchanger|cooler|heater/.test(n)) return 'heat_exchanger';
    if (/motor|engine|turbine|generator/.test(n)) return 'machine';
    if (/sensor|gauge|meter/.test(n)) return 'instrument';
    return 'equipment';
}

function extractTag(name) {
    // Match P&ID tags: TCV-7742, V-101, P-201A, HX-3001, etc.
    const m = name.match(/[A-Z]{1,4}-\d{2,5}[A-Z]?/);
    return m ? m[0] : name;
}

function notifyEquipmentSelected(name) {
    const obj = _sceneObjects[name];

    const event = {
        type: 'EQUIPMENT_SELECTED',
        assetId: obj?.path || name,
        assetTag: obj?.tag || extractTag(name),       // prefer backend tag
        assetName: name,
        assetType: obj?.type || inferAssetType(name),  // prefer backend type
        metadata: {
            position: obj?.position || null,
            scale: obj?.scale || null,
            path: obj?.path || name,
            primitive: obj?.primitive || null,
            color: obj?.color || null,
        },
        timestamp: Date.now(),
    };

    console.log('[Vibe3D → HeatOps] EQUIPMENT_SELECTED', event);

    // Send to parent window (iframe → HeatOps Nav X)
    if (window.parent !== window) {
        window.parent.postMessage(event, '*');
        console.log('[Vibe3D] postMessage sent to parent window');
    } else {
        console.log('[Vibe3D] Not in iframe — postMessage skipped (direct access)');
    }

    // Also store on backend for REST polling
    fetch(`${API}/api/equipment/event`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(event),
    }).catch((err) => console.warn('[Vibe3D] equipment event POST failed:', err));
}

// ── Inbound Equipment Selection (parent window → iframe) ────

console.log('[Vibe3D] SELECT_OBJECT listener registered (app.js v10)');

window.addEventListener('message', (event) => {
    if (!event.data || typeof event.data !== 'object') return;
    // Log ALL incoming postMessages for debugging
    if (event.data.type) {
        console.log('[Vibe3D] postMessage received:', event.data.type, event.data);
    }
    if (event.data.type !== 'SELECT_OBJECT') return;

    const { assetTag, assetName, assetId } = event.data;
    console.log('[Vibe3D ← Navigator] SELECT_OBJECT', { assetTag, assetName, assetId, sceneObjectCount: Object.keys(_sceneObjects).length });

    // Search priority: 1) assetTag → 2) assetName → 3) assetId (path)
    let found = null;
    for (const [name, obj] of Object.entries(_sceneObjects)) {
        if (assetTag && (obj.tag === assetTag || extractTag(name) === assetTag)) { found = name; break; }
        if (assetName && name === assetName) { found = name; break; }
        if (assetId && (obj.path === assetId || name === assetId)) { found = name; break; }
    }

    if (found) {
        // 3D viewer: purple outline + camera focus
        if (window.sceneViewer && window.sceneViewer.initialized) {
            window.sceneViewer.selectObject(found);
        }
        inspectObject(found);      // right panel info
        setTargetTag(found);       // @tag in chat input
        selectedObject = found;

        // Highlight in hierarchy tree
        document.querySelectorAll('.node-row.selected').forEach(el => el.classList.remove('selected'));
        document.querySelectorAll('.node-name').forEach(el => {
            if (el.textContent === found) el.closest('.node-row')?.classList.add('selected');
        });
    }

    // Respond to parent with result
    if (window.parent !== window) {
        window.parent.postMessage({
            type: 'SELECT_OBJECT_RESULT',
            success: !!found,
            assetName: found || null,
            requestedTag: assetTag || null,
        }, '*');
    }
});
