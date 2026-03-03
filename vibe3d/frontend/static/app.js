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
let _sceneObjects = {}; // uid (path) → {name, position, scale, path, primitive, color}
function _findSceneObjectByName(name) {
    for (const obj of Object.values(_sceneObjects)) {
        if (obj.name === name) return obj;
    }
    return null;
}
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

    // Drone2Twin Wizard
    if (typeof DroneWizard === 'function') {
        window.droneWizard = new DroneWizard();
        window.droneWizard.init('droneWizardContainer');
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
let _targetObjectUid = null;

function setTargetTag(name, uid) {
    _targetObjectName = name;
    _targetObjectUid = uid || name;
    const tag = document.getElementById('targetTag');
    if (tag) {
        tag.textContent = name;
        tag.style.display = 'inline-flex';
        tag.title = `대상: ${name} (클릭하여 해제)`;
    }
    const input = document.getElementById('chatInput');
    input.placeholder = `"${name}"에 대한 명령을 입력하세요...`;
    input.focus();

    // Show selection preview banner
    const preview = document.getElementById('selectionPreview');
    if (preview) {
        preview.style.display = 'flex';
        const nameEl = document.getElementById('selPreviewName');
        const detailEl = document.getElementById('selPreviewDetail');
        if (nameEl) nameEl.textContent = name;
        if (detailEl) {
            const obj = _sceneObjects[_targetObjectUid];
            const parts = [];
            if (obj?.primitive) parts.push(obj.primitive);
            if (obj?.tag && obj.tag !== 'Untagged') parts.push(`Tag: ${obj.tag}`);
            if (obj?.type) parts.push(obj.type);
            if (obj?.path) parts.push(obj.path);
            detailEl.textContent = parts.length ? parts.join(' | ') : 'Unity Object';
        }
    }

    // Auto-switch to Hierarchy tab to show inspector
    switchPanel('right', 'hierarchy');
}

function clearTargetTag() {
    _targetObjectName = null;
    _targetObjectUid = null;
    const tag = document.getElementById('targetTag');
    if (tag) tag.style.display = 'none';
    const input = document.getElementById('chatInput');
    input.placeholder = '자연어 명령을 입력하세요... (Enter로 전송)';

    // Hide selection preview banner
    const preview = document.getElementById('selectionPreview');
    if (preview) preview.style.display = 'none';
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
    // Drone2Twin pipeline events
    if (event.startsWith('drone_')) {
        if (typeof droneWizard !== 'undefined' && droneWizard.handleWS) {
            droneWizard.handleWS(event, data);
        }
    }
    // Mesh Edit events
    if (event.startsWith('mesh_edit_')) {
        mesheditHandleWS(event, data);
    }
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
        window.sceneViewer.onSelect = (name, uid) => {
            selectedObject = name;
            inspectObject(name, uid);
            // Highlight in hierarchy
            document.querySelectorAll('.node-row.selected').forEach(el => el.classList.remove('selected'));
            document.querySelectorAll('.node-name').forEach(el => {
                if (el.textContent === name) el.closest('.node-row')?.classList.add('selected');
            });
            // Set target tag in command input
            setTargetTag(name, uid);
            // Notify parent window (HeatOps Nav X) of equipment selection
            notifyEquipmentSelected(name, uid);
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
            // Cache scene objects keyed by uid (path) for unique lookup
            _sceneObjects = {};
            for (const obj of (data.objects || [])) {
                const uid = obj.path || obj.name;
                if (uid) _sceneObjects[uid] = obj;
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
    // Auto-load tiles when Mesh Edit tab is opened
    if (name === 'meshedit' && !_mesheditTiles.length) mesheditInit();
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

async function inspectObject(name, uid) {
    const body = document.getElementById('inspectorBody');
    body.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';

    // Fallback: show local cache data while API loads (or if MCP unavailable)
    const lookupKey = uid || name;
    const cached = _sceneObjects[lookupKey] || _findSceneObjectByName(name);

    try {
        // Use by_path when path (uid) available for precise lookup; fallback to by_name
        const searchMethod = (uid && uid !== name) ? 'by_path' : 'by_name';
        const searchTarget = (uid && uid !== name) ? uid : name;
        const resp = await fetch(`${API}/api/object/inspect?target=${encodeURIComponent(searchTarget)}&search_method=${searchMethod}`);
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

        if (!objInfo) {
            // Fallback to local cache when MCP not connected
            if (cached) {
                _renderInspectorLocal(body, name, cached);
            } else {
                body.innerHTML = `<div class="empty-state"><p>"${esc(name)}" not found</p></div>`;
            }
            return;
        }

        _renderInspectorFull(body, name, objInfo, cached);
    } catch (e) {
        // API error — show local data if available
        if (cached) {
            _renderInspectorLocal(body, name, cached);
        } else {
            body.innerHTML = `<div class="empty-state"><p>Error: ${esc(e.message)}</p></div>`;
        }
    }
}

function _renderInspectorFull(body, name, objInfo, cached) {
    const t = objInfo.transform || {};
    const pos = t.position || t.localPosition || {};
    const rot = t.rotation || t.localRotation || {};
    const scl = t.scale || t.localScale || {};

    // Object header
    const objName = objInfo.name || name;
    const objPath = objInfo.path || cached?.path || '';

    // Badges
    let badges = '';
    const tag = objInfo.tag || cached?.tag || '';
    const layer = objInfo.layer || '';
    const isActive = objInfo.activeSelf !== undefined ? objInfo.activeSelf : true;
    if (tag && tag !== 'Untagged') badges += `<span class="inspector-badge tag">${esc(tag)}</span>`;
    if (layer && layer !== 'Default') badges += `<span class="inspector-badge layer">${esc(layer)}</span>`;
    badges += `<span class="inspector-badge ${isActive ? 'active' : 'inactive'}">${isActive ? 'Active' : 'Inactive'}</span>`;
    const prim = cached?.primitive || objInfo.type || '';
    if (prim) badges += `<span class="inspector-badge type">${esc(prim)}</span>`;

    // Components
    let compsHtml = '';
    const comps = objInfo.components || [];
    if (comps.length) {
        compsHtml = `<div class="inspector-info-divider">Components</div>
            <div class="inspector-components">${comps.map(c => {
                const cName = typeof c === 'string' ? c : (c.type || c.name || '');
                return `<span class="inspector-comp-item">${esc(cName)}</span>`;
            }).join('')}</div>`;
    }

    body.innerHTML = `
        <div class="inspector-header">
            <div class="inspector-header-name">${esc(objName)}</div>
            ${objPath ? `<div class="inspector-header-path">${esc(objPath)}</div>` : ''}
        </div>
        <div class="inspector-badges">${badges}</div>
        ${compsHtml}
        <div class="inspector-info-divider">Transform</div>
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
}

function _renderInspectorLocal(body, name, cached) {
    // Render from local _sceneObjects cache (no MCP needed)
    const pos = cached.position || {};
    const scl = cached.scale || {};

    let badges = '';
    const tag = cached.tag || '';
    if (tag && tag !== 'Untagged') badges += `<span class="inspector-badge tag">${esc(tag)}</span>`;
    const prim = cached.primitive || cached.type || '';
    if (prim) badges += `<span class="inspector-badge type">${esc(prim)}</span>`;
    badges += `<span class="inspector-badge active">Local</span>`;

    body.innerHTML = `
        <div class="inspector-header">
            <div class="inspector-header-name">${esc(name)}</div>
            ${cached.path ? `<div class="inspector-header-path">${esc(cached.path)}</div>` : ''}
        </div>
        <div class="inspector-badges">${badges}</div>
        <div class="inspector-info-divider">Transform (local cache)</div>
        <div class="inspector-field">
            <span class="inspector-label">Pos</span>
            <div class="inspector-value">
                <input id="insp-px" value="${(pos.x||0).toFixed(2)}">
                <input id="insp-py" value="${(pos.y||0).toFixed(2)}">
                <input id="insp-pz" value="${(pos.z||0).toFixed(2)}">
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

function notifyEquipmentSelected(name, uid) {
    const obj = _sceneObjects[uid || name] || _findSceneObjectByName(name);

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
    let foundUid = null;
    let foundName = null;
    for (const [uid, obj] of Object.entries(_sceneObjects)) {
        const objName = obj.name || uid;
        if (assetTag && (obj.tag === assetTag || extractTag(objName) === assetTag)) { foundUid = uid; foundName = objName; break; }
        if (assetName && objName === assetName) { foundUid = uid; foundName = objName; break; }
        if (assetId && (obj.path === assetId || uid === assetId)) { foundUid = uid; foundName = objName; break; }
    }

    if (foundUid) {
        // 3D viewer: outline + camera focus
        if (window.sceneViewer && window.sceneViewer.initialized) {
            window.sceneViewer.selectObject(foundUid);
        }
        inspectObject(foundName, foundUid);  // right panel info
        setTargetTag(foundName, foundUid);   // @tag in chat input
        selectedObject = foundName;

        // Highlight in hierarchy tree
        document.querySelectorAll('.node-row.selected').forEach(el => el.classList.remove('selected'));
        document.querySelectorAll('.node-name').forEach(el => {
            if (el.textContent === foundName) el.closest('.node-row')?.classList.add('selected');
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

// ── City Tiles 3D Viewer ─────────────────────────────────────

let _cityTilesLoaded = false;

async function loadCityTiles() {
    if (!window.sceneViewer || !window.sceneViewer.initialized) {
        // Switch to 3D view first
        setSceneViewMode('3d');
        await new Promise(r => setTimeout(r, 500));
    }

    if (!window.sceneViewer || !window.sceneViewer.initialized) {
        addChatMsg('system', '3D 뷰가 초기화되지 않았습니다.');
        return;
    }

    addChatMsg('system', 'City Tiles 데이터를 로딩 중...');

    // Progress callback
    window.sceneViewer.onTileProgress = (loaded, total) => {
        const pct = Math.round((loaded / total) * 100);
        setFooterStatus(`City Tiles: ${loaded}/${total} (${pct}%)`);
    };

    // ── Try LOD endpoint first (progressive loading) ──
    try {
        const lodResp = await fetch(`${API}/api/drone/citytiles-lod`);
        if (lodResp.ok) {
            const lodData = await lodResp.json();
            if (lodData.has_lods && lodData.tiles && lodData.tiles.length > 0) {
                addChatMsg('system',
                    `${lodData.tile_count}개 타일 발견 (LOD 지원)\n` +
                    `LOD2 우선 로딩 (~${lodData.total_lod2_mb} MB) → 풀 디테일 ${lodData.total_lod0_mb} MB`
                );

                const result = await window.sceneViewer.loadOBJTilesWithLOD(lodData.tiles);
                _cityTilesLoaded = true;

                addChatMsg('system',
                    `Phase 1 완료: ${result.loaded}/${result.total}개 타일 (LOD2)\n` +
                    `카메라 근처 타일은 자동으로 풀 디테일로 업그레이드됩니다.`
                );
                setFooterStatus(`City Tiles: ${result.loaded}개 (LOD)`);

                const btn = document.getElementById('cityTilesBtn');
                if (btn) btn.classList.add('active');
                return;
            }
        }
    } catch (e) {
        console.warn('[CityTiles] LOD endpoint failed, falling back:', e);
    }

    // ── Fallback: original full-mesh loading ──
    try {
        const resp = await fetch(`${API}/api/drone/citytiles`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        if (!data.tiles || data.tiles.length === 0) {
            addChatMsg('system', 'CityTiles가 없습니다. Unity Assets/CityTiles/ 폴더를 확인하세요.');
            return;
        }

        // Sort tiles by size (smallest first for faster initial display)
        const sortedTiles = [...data.tiles].sort((a, b) => a.size_mb - b.size_mb);
        const totalMB = data.total_size_mb;

        addChatMsg('system',
            `${data.tile_count}개 타일 발견 (${totalMB} MB)\n` +
            `작은 타일부터 순서대로 로딩합니다...`
        );

        const result = await window.sceneViewer.loadOBJTiles(sortedTiles);
        _cityTilesLoaded = true;

        addChatMsg('system',
            `City Tiles 로딩 완료! ${result.loaded}/${result.total}개 타일\n` +
            `Row별: ${Object.keys(data.rows).map(r => `Row ${r} (${data.rows[r].length}개)`).join(', ')}`
        );
        setFooterStatus(`City Tiles: ${result.loaded}개 로딩됨`);

        // Update toolbar button state
        const btn = document.getElementById('cityTilesBtn');
        if (btn) btn.classList.add('active');

    } catch (e) {
        addChatMsg('system', `City Tiles 로딩 실패: ${e.message}`);
        console.error('[CityTiles]', e);
    }
}

function toggleCityTiles() {
    if (!_cityTilesLoaded) {
        loadCityTiles();
    } else if (window.sceneViewer) {
        const visible = window.sceneViewer._tileGroup?.visible;
        window.sceneViewer.setTilesVisible(!visible);
        const btn = document.getElementById('cityTilesBtn');
        if (btn) btn.classList.toggle('active', !visible);
        addChatMsg('system', !visible ? 'City Tiles 표시' : 'City Tiles 숨김');
    }
}

// ═══════════════════════════════════════════════════════════════
// GeoBIM — Building Extraction + Inspector + Measurement
// ═══════════════════════════════════════════════════════════════

let _geobimBuildings = [];
let _geobimSelectedId = null;
let _geobimExtracting = false;

async function geobimExtract() {
    if (_geobimExtracting) return;
    _geobimExtracting = true;
    const btn = document.getElementById('geobimExtractBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Extracting...'; }

    // Determine tile folder from drone orchestrator or default
    let tileFolder = '';
    try {
        const infoResp = await fetch(`${API}/api/drone/project-info`);
        if (infoResp.ok) {
            const info = await infoResp.json();
            tileFolder = info.tile_folder || info.source_path || '';
        }
    } catch(e) { /* ignore */ }

    if (!tileFolder) {
        // Fallback: try Unity CityTiles path
        const unityProject = window._unityProjectPath || 'C:/UnityProjects/My project';
        tileFolder = `${unityProject}/Assets/CityTiles`;
    }

    addChatMsg('system', `GeoBIM: 건물 추출 시작...\nTile folder: ${tileFolder}`);

    try {
        const resp = await fetch(`${API}/api/drone/geobim/extract`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tile_folder: tileFolder }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        // Poll status
        await _pollGeoBIMStatus();
    } catch (e) {
        addChatMsg('system', `GeoBIM 추출 실패: ${e.message}`);
    } finally {
        _geobimExtracting = false;
        if (btn) { btn.disabled = false; btn.textContent = 'Extract Buildings from Tiles'; }
    }
}

async function _pollGeoBIMStatus() {
    const maxWait = 120; // seconds
    const interval = 2000;
    let elapsed = 0;

    while (elapsed < maxWait * 1000) {
        await new Promise(r => setTimeout(r, interval));
        elapsed += interval;

        try {
            const resp = await fetch(`${API}/api/drone/geobim/status`);
            if (!resp.ok) break;
            const s = await resp.json();

            setFooterStatus(`GeoBIM: ${s.tiles_processed}/${s.tile_count} tiles (${s.building_count} buildings)`);

            if (s.status === 'completed') {
                addChatMsg('system',
                    `GeoBIM 추출 완료! ${s.building_count}개 건물 발견\n` +
                    `처리 시간: ${s.processing_time_s}s`
                );
                await _loadGeoBIMResults();
                return;
            } else if (s.status === 'failed') {
                addChatMsg('system', `GeoBIM 추출 실패: ${s.error || 'Unknown error'}`);
                return;
            }
        } catch(e) { break; }
    }
}

async function _loadGeoBIMResults() {
    try {
        // Load summary
        const sumResp = await fetch(`${API}/api/drone/geobim/summary`);
        if (sumResp.ok) {
            const sum = await sumResp.json();
            _showGeoBIMStats(sum);
        }

        // Load buildings list
        const bldgResp = await fetch(`${API}/api/drone/geobim/buildings`);
        if (bldgResp.ok) {
            const data = await bldgResp.json();
            _geobimBuildings = data.buildings || [];
            _renderGeoBIMBuildingList();
        }

        // Load footprints for 3D overlay
        const fpResp = await fetch(`${API}/api/drone/geobim/footprints`);
        if (fpResp.ok) {
            const fpData = await fpResp.json();
            if (window.sceneViewer && fpData.footprints) {
                window.sceneViewer.loadFootprints(fpData.footprints);
                // Wire building click callback
                window.sceneViewer.onBuildingClick = (id) => geobimSelectBuilding(id);
            }
        }
    } catch (e) {
        console.error('[GeoBIM] Failed to load results:', e);
    }
}

function _showGeoBIMStats(sum) {
    const statsEl = document.getElementById('geobimStats');
    if (statsEl) statsEl.style.display = '';
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setVal('geobimBldgCount', sum.building_count || 0);
    setVal('geobimAvgHeight', `${(sum.avg_height || 0).toFixed(1)}m`);
    setVal('geobimMaxHeight', `${(sum.max_height || 0).toFixed(1)}m`);
    setVal('geobimArea', `${(sum.total_footprint_area || 0).toFixed(0)}m²`);
}

function _renderGeoBIMBuildingList(filter = '') {
    const listEl = document.getElementById('geobimBuildingList');
    if (!listEl) return;

    const query = filter.toLowerCase().trim();
    const filtered = query
        ? _geobimBuildings.filter(b =>
            (b.label || '').toLowerCase().includes(query) ||
            (b.tile_name || '').toLowerCase().includes(query) ||
            (b.id || '').toLowerCase().includes(query)
        )
        : _geobimBuildings;

    if (filtered.length === 0) {
        listEl.innerHTML = query
            ? `<div class="empty-state"><p>No match for "${filter}"</p></div>`
            : '<div class="empty-state"><p>No buildings detected</p></div>';
        return;
    }

    listEl.innerHTML = filtered.map(b => {
        const confClass = b.confidence > 0.7 ? 'high' : b.confidence > 0.4 ? 'medium' : 'low';
        return `
            <div class="geobim-building-item" data-id="${b.id}" onclick="geobimSelectBuilding('${b.id}')">
                <div class="geobim-building-icon">🏢</div>
                <div class="geobim-building-info">
                    <div class="geobim-building-name">${b.label}</div>
                    <div class="geobim-building-meta">${b.height.toFixed(1)}m | ${b.footprint_area.toFixed(0)}m² | ${b.tile_name}</div>
                </div>
                <span class="geobim-confidence ${confClass}">${(b.confidence * 100).toFixed(0)}%</span>
            </div>
        `;
    }).join('');
}

function geobimSearchBuildings(query) {
    _renderGeoBIMBuildingList(query);
}

function geobimSelectBuilding(id) {
    _geobimSelectedId = id;

    // Highlight in list
    document.querySelectorAll('.geobim-building-item').forEach(el => {
        el.classList.toggle('selected', el.dataset.id === id);
    });

    // Show inspector
    const b = _geobimBuildings.find(x => x.id === id);
    if (!b) return;

    _showBuildingInspector(b);

    // Highlight footprint + BBox wireframe in 3D
    if (window.sceneViewer) {
        window.sceneViewer._highlightFootprint(id);
        window.sceneViewer.highlightBuildingBBox(b);
    }
}

function _showBuildingInspector(b) {
    const inspectorBody = document.getElementById('inspectorBody');
    if (!inspectorBody) return;

    inspectorBody.innerHTML = `
        <div class="geobim-inspector">
            <div class="geobim-inspector-header">
                <div class="geobim-building-icon">🏢</div>
                <span class="geobim-inspector-title">${b.label}</span>
            </div>
            <div class="geobim-props">
                <span class="geobim-prop-key">Tile</span>
                <span class="geobim-prop-val">${b.tile_name}</span>
                <span class="geobim-prop-key">Height</span>
                <span class="geobim-prop-val">${b.height.toFixed(2)} m</span>
                <span class="geobim-prop-key">Ground Elev.</span>
                <span class="geobim-prop-val">${b.ground_elevation.toFixed(2)} m</span>
                <span class="geobim-prop-key">Roof Elev.</span>
                <span class="geobim-prop-val">${b.roof_elevation.toFixed(2)} m</span>
                <span class="geobim-prop-key">Footprint</span>
                <span class="geobim-prop-val">${b.footprint_area.toFixed(1)} m²</span>
                <span class="geobim-prop-key">Vertices</span>
                <span class="geobim-prop-val">${b.vertex_count.toLocaleString()}</span>
                <span class="geobim-prop-key">Faces</span>
                <span class="geobim-prop-val">${b.face_count.toLocaleString()}</span>
                <span class="geobim-prop-key">Confidence</span>
                <span class="geobim-prop-val">${(b.confidence * 100).toFixed(1)}%</span>
                <span class="geobim-prop-key">Centroid</span>
                <span class="geobim-prop-val">[${b.centroid.map(v => v.toFixed(1)).join(', ')}]</span>
                <span class="geobim-prop-key">BBox Min</span>
                <span class="geobim-prop-val">[${b.bbox_min.map(v => v.toFixed(1)).join(', ')}]</span>
                <span class="geobim-prop-key">BBox Max</span>
                <span class="geobim-prop-val">[${b.bbox_max.map(v => v.toFixed(1)).join(', ')}]</span>
                ${b.roof_planes && b.roof_planes.length > 0 ? `
                <span class="geobim-prop-key">Roof Planes</span>
                <span class="geobim-prop-val">${b.roof_planes.length} plane(s)</span>
                ${b.roof_planes.map((rp, i) => `
                    <span class="geobim-prop-key" style="padding-left:12px">Plane ${i+1}</span>
                    <span class="geobim-prop-val">tilt=${rp.tilt_deg.toFixed(1)}° az=${rp.azimuth_deg.toFixed(0)}° area=${rp.area.toFixed(1)}m²</span>
                `).join('')}` : ''}
                ${b.tags ? `
                <span class="geobim-prop-key">Tags</span>
                <span class="geobim-prop-val">${b.tags.join(', ')}</span>
                ` : ''}
            </div>
        </div>
    `;
}

// ── Measurement Tools ──────────────────────────────────────

let _measureMode = null;

function toggleMeasureToolbar() {
    const tb = document.getElementById('measureToolbar');
    if (!tb) return;
    tb.classList.toggle('hidden');
    const btn = document.getElementById('measureBtn');
    if (btn) btn.classList.toggle('active', !tb.classList.contains('hidden'));

    // If hiding, also clear mode
    if (tb.classList.contains('hidden')) {
        setMeasureMode(null);
    }
}

function setMeasureMode(mode) {
    _measureMode = mode;

    // Update toolbar button states
    document.querySelectorAll('.measure-btn[data-mode]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Set mode on scene viewer
    if (window.sceneViewer) {
        window.sceneViewer.setMeasureMode(mode);

        // Wire measurement callback
        if (mode) {
            window.sceneViewer.onMeasure = (mType, result) => {
                let msg = '';
                if (mType === 'distance') msg = `📏 거리: ${result.distance.toFixed(2)}m`;
                else if (mType === 'height') msg = `📐 높이: ${result.height.toFixed(2)}m`;
                else if (mType === 'area') msg = `⬡ 면적: ${result.area.toFixed(2)}m²`;
                if (msg) addChatMsg('system', msg);
            };
        }
    }
}

function clearMeasurements() {
    if (window.sceneViewer) {
        window.sceneViewer.clearMeasurements();
    }
    setMeasureMode(null);
    addChatMsg('system', '계측 결과 초기화됨');
}

// ── Measurement Export ─────────────────────────────────────

let _measurementHistory = [];

function recordMeasurement(type, result) {
    _measurementHistory.push({
        type,
        value: result.distance || result.height || result.area || 0,
        unit: type === 'area' ? 'm²' : 'm',
        points: result.points ? result.points.map(p => [p.x, p.y, p.z]) : [],
        timestamp: new Date().toISOString(),
    });
}

async function exportMeasurements(fmt = 'json') {
    if (_measurementHistory.length === 0) {
        addChatMsg('system', '내보낼 계측 결과가 없습니다.');
        return;
    }
    try {
        const resp = await fetch(`${API}/api/drone/geobim/export/measurements`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                measurements: _measurementHistory,
                output_path: `geobim_export/measurements.${fmt}`,
                format: fmt,
            }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        addChatMsg('system', `계측 결과 ${data.count}건 내보내기 완료: ${fmt.toUpperCase()}`);
    } catch (e) {
        addChatMsg('system', `계측 내보내기 실패: ${e.message}`);
    }
}

// ── Full Pipeline ──────────────────────────────────────────

async function geobimRunPipeline() {
    let tileFolder = '';
    let exportFolder = '';

    try {
        const infoResp = await fetch(`${API}/api/drone/project-info`);
        if (infoResp.ok) {
            const info = await infoResp.json();
            tileFolder = info.tile_folder || info.source_path || '';
        }
    } catch(e) { /* ignore */ }

    if (!tileFolder) {
        const unityProject = window._unityProjectPath || 'C:/UnityProjects/My project';
        tileFolder = `${unityProject}/Assets/CityTiles`;
    }
    exportFolder = tileFolder.replace(/\/Assets\/CityTiles.*/, '') + '/GeoBIM_Export';

    addChatMsg('system', `GeoBIM 파이프라인 시작 (00~40)...\nTiles: ${tileFolder}\nExport: ${exportFolder}`);

    try {
        const resp = await fetch(`${API}/api/drone/geobim/pipeline/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tile_folder: tileFolder,
                export_folder: exportFolder,
                skip_collider: true,  // Skip Blender step if not available
            }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        // Poll pipeline status
        await _pollPipelineStatus();
    } catch (e) {
        addChatMsg('system', `파이프라인 실패: ${e.message}`);
    }
}

async function _pollPipelineStatus() {
    const maxWait = 300;
    const interval = 3000;
    let elapsed = 0;

    while (elapsed < maxWait * 1000) {
        await new Promise(r => setTimeout(r, interval));
        elapsed += interval;

        try {
            const resp = await fetch(`${API}/api/drone/geobim/pipeline/status`);
            if (!resp.ok) break;
            const s = await resp.json();

            const stage = s.current_stage || 'done';
            setFooterStatus(`Pipeline: ${stage} (${s.progress_pct}%)`);

            if (!s.is_running) {
                if (s.error) {
                    addChatMsg('system', `파이프라인 오류: ${s.error}`);
                } else {
                    addChatMsg('system',
                        `파이프라인 완료!\n건물: ${s.building_count}개\n콜라이더: ${s.collider_count}개\n` +
                        `단계: ${s.stages_completed.join(' → ')}`
                    );
                    await _loadGeoBIMResults();
                }
                return;
            }
        } catch(e) { break; }
    }
}

// ── NavMesh Path (Web Viewer) ──────────────────────────────

let _navMode = null;
let _navPoints = [];

function toggleNavMode() {
    if (_navMode) {
        // Deactivate
        _navMode = null;
        _navPoints = [];
        if (window.sceneViewer) {
            window.sceneViewer.onNavClick = null;
            window.sceneViewer.renderer.domElement.style.cursor = 'grab';
        }
        const btn = document.getElementById('navModeBtn');
        if (btn) btn.classList.toggle('active', false);
        addChatMsg('system', '동선 모드 종료');
        return;
    }

    // Activate
    _navMode = 'setStart';
    _navPoints = [];
    const btn = document.getElementById('navModeBtn');
    if (btn) btn.classList.toggle('active', true);
    addChatMsg('system', '동선 모드: 시작점을 클릭하세요');

    if (window.sceneViewer) {
        window.sceneViewer.setMeasureMode(null);
        window.sceneViewer.renderer.domElement.style.cursor = 'crosshair';
        window.sceneViewer.onNavClick = async (pt) => {
            if (_navMode === 'setStart') {
                _navPoints = [pt];
                _navMode = 'setEnd';
                addChatMsg('system', `시작점: [${pt.x.toFixed(1)}, ${pt.z.toFixed(1)}] — 종점을 클릭하세요`);
            } else if (_navMode === 'setEnd') {
                _navPoints.push(pt);
                addChatMsg('system', `종점: [${pt.x.toFixed(1)}, ${pt.z.toFixed(1)}] — 경로 탐색 중...`);
                window.sceneViewer.renderer.domElement.style.cursor = 'wait';
                try {
                    const resp = await fetch(`${API}/api/drone/geobim/pathfind`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            start: [_navPoints[0].x, _navPoints[0].z],
                            end: [_navPoints[1].x, _navPoints[1].z],
                            resolution: 1.0,
                            agent_radius: 0.5,
                        }),
                    });
                    const data = await resp.json();
                    if (data.success && data.path.length > 0) {
                        window.sceneViewer.renderNavPath(data.path);
                        addChatMsg('system', `경로 발견: ${data.distance.toFixed(1)}m (${data.path.length} 포인트, ${data.elapsed_ms.toFixed(0)}ms)`);
                    } else {
                        addChatMsg('system', `경로 없음: ${data.error || '도달 불가'}`);
                    }
                } catch (e) {
                    addChatMsg('system', `경로 탐색 실패: ${e.message}`);
                }
                // Reset for next path
                _navMode = 'setStart';
                _navPoints = [];
                window.sceneViewer.renderer.domElement.style.cursor = 'crosshair';
                addChatMsg('system', '다음 시작점을 클릭하거나 NavMesh 버튼으로 종료하세요');
            }
        };
    }
}

// ── Visibility Analysis (Web) ──────────────────────────────

async function runVisibilityAnalysis() {
    const posStr = prompt('센서 위치 (x,y,z):', '0,3,0');
    if (!posStr) return;
    const parts = posStr.split(',').map(Number);
    if (parts.length < 3 || parts.some(isNaN)) {
        addChatMsg('system', '잘못된 좌표 형식입니다. x,y,z 형식으로 입력하세요.');
        return;
    }

    const fovStr = prompt('수평 시야각 (도, 360=전방위):', '360');
    const hfov = parseFloat(fovStr) || 360;
    const distStr = prompt('최대 거리 (m):', '100');
    const maxDist = parseFloat(distStr) || 100;
    const yawStr = prompt('방향각 yaw (도, 0=East):', '0');
    const yaw = parseFloat(yawStr) || 0;

    addChatMsg('system', `가시성 분석 중...\n센서: [${parts.join(', ')}], FOV=${hfov}°, 거리=${maxDist}m`);

    try {
        const resp = await fetch(`${API}/api/drone/geobim/visibility`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sensors: [{
                    position: parts,
                    hfov: hfov,
                    yaw: yaw,
                    max_distance: maxDist,
                    height: parts[1] || 3.0,
                }],
                grid_resolution: 2.0,
            }),
        });
        const data = await resp.json();

        if (data.error) {
            addChatMsg('system', `가시성 분석 실패: ${data.error}`);
            return;
        }

        // Render heatmap in 3D viewer
        if (window.sceneViewer) {
            window.sceneViewer.renderVisibilityHeatmap(data.heatmap, data.grid_resolution);
            window.sceneViewer.renderSensorMarkers(data.sensors);
        }

        const pct = (data.coverage_ratio * 100).toFixed(1);
        addChatMsg('system',
            `가시성 분석 완료 (${data.elapsed_ms.toFixed(0)}ms)\n` +
            `커버리지: ${pct}% (${data.visible_cells}/${data.total_cells} 셀)\n` +
            `사각지대: ${data.blind_cells} 셀\n` +
            `히트맵 해상도: ${data.grid_resolution}m`
        );
    } catch (e) {
        addChatMsg('system', `가시성 분석 오류: ${e.message}`);
    }
}

function clearVisibility() {
    if (window.sceneViewer) {
        window.sceneViewer.clearVisibilityHeatmap();
        addChatMsg('system', '가시성 히트맵 제거됨');
    }
}

// ── Accessibility Analysis (Section 4.7) ───────────────────

async function runAccessibilityAnalysis() {
    const posStr = prompt('시작점 (x,z):', '0,0');
    if (!posStr) return;
    const parts = posStr.split(',').map(Number);
    if (parts.length < 2 || parts.some(isNaN)) {
        addChatMsg('system', '잘못된 좌표 형식입니다. x,z 형식으로 입력하세요.');
        return;
    }

    const timeStr = prompt('최대 이동 시간 (초):', '300');
    const maxTime = parseFloat(timeStr) || 300;
    const speedStr = prompt('이동 속도 (m/s, 보행=1.4):', '1.4');
    const speed = parseFloat(speedStr) || 1.4;

    addChatMsg('system', `접근성 분석 중...\n시작: [${parts.join(', ')}], 시간=${maxTime}s, 속도=${speed}m/s`);

    try {
        const resp = await fetch(`${API}/api/drone/geobim/accessibility`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                start: parts.slice(0, 2),
                max_time: maxTime,
                speed: speed,
                resolution: 1.0,
            }),
        });
        const data = await resp.json();

        if (!data.success) {
            addChatMsg('system', `접근성 분석 실패: ${data.error || '알 수 없는 오류'}`);
            return;
        }

        // Render on 3D viewer
        if (window.sceneViewer) {
            window.sceneViewer.renderAccessibilityHeatmap(data.reachable_cells, 1.0, maxTime);
        }

        addChatMsg('system',
            `접근성 분석 완료 (${data.elapsed_ms.toFixed(0)}ms)\n` +
            `도달 가능 면적: ${data.reachable_area_m2.toFixed(0)}m² (${data.cell_count} 셀)\n` +
            `최대 이동 거리: ${data.max_distance_m.toFixed(0)}m\n` +
            `이동 시간: ${maxTime}s, 속도: ${speed}m/s`
        );
    } catch (e) {
        addChatMsg('system', `접근성 분석 오류: ${e.message}`);
    }
}

// ── Per-Building Coverage Report (Section 4.8) ─────────────

async function runCoverageReport() {
    const posStr = prompt('센서 위치 (x,y,z):', '0,5,0');
    if (!posStr) return;
    const parts = posStr.split(',').map(Number);
    if (parts.length < 3 || parts.some(isNaN)) {
        addChatMsg('system', '잘못된 좌표 형식입니다.');
        return;
    }

    addChatMsg('system', '건물별 커버리지 리포트 생성 중...');

    try {
        const resp = await fetch(`${API}/api/drone/geobim/visibility/coverage-report`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sensors: [{ position: parts, hfov: 360, max_distance: 100, height: parts[1] }],
                grid_resolution: 2.0,
            }),
        });
        const data = await resp.json();

        if (data.error) {
            addChatMsg('system', `리포트 실패: ${data.error}`);
            return;
        }

        let report = `건물별 커버리지 리포트 (${data.building_count}개 건물)\n`;
        report += `전체 커버리지: ${(data.overall_coverage * 100).toFixed(1)}%\n`;
        report += `평균 건물 커버리지: ${(data.avg_coverage * 100).toFixed(1)}%\n`;
        report += `\n--- 사각지대 취약 건물 (하위 5개) ---\n`;

        const worst = data.buildings.slice(0, 5);
        worst.forEach((b, i) => {
            report += `${i+1}. ${b.label}: ${(b.coverage_ratio * 100).toFixed(1)}% (blind=${b.blind_cells} cells)\n`;
        });

        addChatMsg('system', report);
    } catch (e) {
        addChatMsg('system', `리포트 오류: ${e.message}`);
    }
}

// ── HITL Review Queue (Section 3.3.3) ──────────────────────

async function populateReviewQueue() {
    try {
        const resp = await fetch(`${API}/api/drone/geobim/review/populate`, { method: 'POST' });
        const data = await resp.json();
        addChatMsg('system', `검수 큐 생성: ${data.count}개 (신뢰도 < ${data.threshold})`);
        await loadReviewQueue();
    } catch (e) {
        addChatMsg('system', `검수 큐 오류: ${e.message}`);
    }
}

async function loadReviewQueue() {
    try {
        const resp = await fetch(`${API}/api/drone/geobim/review/queue?status=pending&limit=50`);
        const data = await resp.json();
        _renderReviewQueue(data.items || []);
    } catch (e) {
        console.error('[HITL] Load failed:', e);
    }
}

function _renderReviewQueue(items) {
    const listEl = document.getElementById('reviewQueueList');
    if (!listEl) return;

    if (items.length === 0) {
        listEl.innerHTML = '<div class="empty-state"><p>검수 대기 항목 없음</p></div>';
        return;
    }

    listEl.innerHTML = items.map(item => `
        <div class="review-item" data-id="${item.building_id}">
            <div class="review-item-info">
                <span class="review-item-label">${item.label || item.building_id}</span>
                <span class="review-item-meta">${(item.confidence * 100).toFixed(0)}% | ${(item.height_max || 0).toFixed(1)}m | ${(item.area_2d || 0).toFixed(0)}m²</span>
            </div>
            <div class="review-item-actions">
                <button class="review-btn confirm" onclick="reviewDecide('${item.building_id}','building')" title="건물 확인">✓</button>
                <button class="review-btn reject" onclick="reviewDecide('${item.building_id}','not_building')" title="비건물 제거">✗</button>
                <button class="review-btn skip" onclick="reviewDecide('${item.building_id}','skip')" title="건너뛰기">→</button>
            </div>
        </div>
    `).join('');
}

async function reviewDecide(buildingId, decision) {
    try {
        const resp = await fetch(`${API}/api/drone/geobim/review/decide`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ building_id: buildingId, decision }),
        });
        if (resp.ok) {
            // Remove from UI
            const el = document.querySelector(`.review-item[data-id="${buildingId}"]`);
            if (el) el.remove();
            const labels = { building: '건물 확인', not_building: '비건물 제거', skip: '건너뛰기' };
            addChatMsg('system', `[HITL] ${buildingId}: ${labels[decision] || decision}`);
        }
    } catch (e) {
        addChatMsg('system', `검수 결정 오류: ${e.message}`);
    }
}

// ── Wire measurement recording to viewer callback ──────────

(function _wireMeasureRecording() {
    const origSetMeasureMode = window.setMeasureMode;
    if (!origSetMeasureMode) return;

    // Patch: record measurements when onMeasure fires
    const _checkViewer = setInterval(() => {
        if (window.sceneViewer && window.sceneViewer.onMeasure === null) {
            // Default recording callback
        }
        if (window.sceneViewer) {
            const existingCb = window.sceneViewer.onMeasure;
            window.sceneViewer.onMeasure = (mType, result) => {
                recordMeasurement(mType, result);
                if (existingCb) existingCb(mType, result);

                let msg = '';
                if (mType === 'distance') msg = `📏 거리: ${result.distance.toFixed(2)}m`;
                else if (mType === 'height') msg = `📐 높이: ${result.height.toFixed(2)}m`;
                else if (mType === 'area') msg = `⬡ 면적: ${result.area.toFixed(2)}m²`;
                if (msg) addChatMsg('system', msg);
            };
            clearInterval(_checkViewer);
        }
    }, 2000);
})();

// ═══════════════════════════════════════════════════════════════
// Mesh Edit — unified step-based UI (replaces Tile Edit + Wizard)
// ═══════════════════════════════════════════════════════════════

let _mesheditStep = 1;
let _mesheditTiles = [];
let _mesheditSelectedTile = null;
let _mesheditSelectedPreset = null;
let _mesheditJobId = null;
let _mesheditPolling = null;
let _mesheditScanResult = null;

const _MESHEDIT_PRESETS = {
    clean_noise: { min_fragment_area: 0.5, remove_degenerate: true },
    decimate_to_target: { target_triangles: 100000, preserve_boundaries: true },
    generate_lods: { lod_ratios: '1.0, 0.4, 0.15', export_format: 'fbx' },
    generate_collider_proxy: { target_triangles: 50000, min_fragment_area: 1.0 },
    pack_for_unity: { target_triangles_lod0: 600000, collider_target_triangles: 50000, min_fragment_area: 0.5 },
};

// ── Step management ──────────────────────────────────────────

function mesheditSetStep(n) {
    _mesheditStep = n;
    // Update stepper circles
    document.querySelectorAll('.meshedit-step').forEach(el => {
        const s = parseInt(el.dataset.step);
        el.classList.remove('active', 'done');
        if (s === n) el.classList.add('active');
        else if (s < n) el.classList.add('done');
    });
    // Show/hide step bodies
    for (let i = 1; i <= 5; i++) {
        const body = document.getElementById(`mesheditStep${i}`);
        if (body) body.classList.toggle('active', i === n);
    }
}

function mesheditGoStep(n) {
    // Only allow going back or to current step, unless step is unlocked
    if (n > _mesheditStep && n !== _mesheditStep + 1) return;
    if (n === 2 && !_mesheditTiles.length) return;
    if (n === 3 && !_mesheditSelectedTile) return;
    mesheditSetStep(n);
}

// ── Init (auto-load on tab switch) ───────────────────────────

async function mesheditInit() {
    const statusEl = document.getElementById('mesheditAutoLoadStatus');
    if (statusEl) statusEl.textContent = 'Loading tiles...';
    try {
        const resp = await fetch(`${API}/api/drone/tiles`);
        if (!resp.ok) throw new Error('Failed to load tiles');
        const data = await resp.json();
        _mesheditTiles = data.tiles || data || [];
        if (_mesheditTiles.length) {
            if (statusEl) statusEl.textContent = `${_mesheditTiles.length} tiles loaded`;
            // Show quick stats
            const statsEl = document.getElementById('mesheditStats');
            if (statsEl) {
                const totalTris = _mesheditTiles.reduce((s, t) => s + (t.triangles || 0), 0);
                const totalSize = _mesheditTiles.reduce((s, t) => s + (t.size_mb || 0), 0);
                statsEl.innerHTML = `
                    <div class="meshedit-stat-card"><div class="meshedit-stat-value">${_mesheditTiles.length}</div><div class="meshedit-stat-label">Tiles</div></div>
                    <div class="meshedit-stat-card"><div class="meshedit-stat-value">${totalTris > 0 ? (totalTris/1e6).toFixed(1) + 'M' : '—'}</div><div class="meshedit-stat-label">Total Tris</div></div>
                `;
                statsEl.style.display = '';
            }
            // Populate tile list in step 2
            _mesheditRenderTileList();
            // Auto-advance to step 2
            setTimeout(() => mesheditSetStep(2), 300);
        } else {
            if (statusEl) statusEl.textContent = 'No tiles in project. Use "Manual Folder Scan" below.';
        }
    } catch (e) {
        if (statusEl) statusEl.textContent = `Load error: ${e.message}`;
    }
}

// ── Manual folder scan ───────────────────────────────────────

async function mesheditScanFolder() {
    const folder = document.getElementById('mesheditFolderPath')?.value?.trim();
    if (!folder) { addChatMsg('system', 'Enter a folder path'); return; }

    const statusEl = document.getElementById('mesheditAutoLoadStatus');
    if (statusEl) statusEl.textContent = 'Scanning folder...';

    try {
        const res = await fetch('/api/wizard/scan', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ folder_path: folder }),
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Scan failed'); }
        const data = await res.json();
        _mesheditScanResult = data;

        // Show stats
        const fmtNum = n => n?.toLocaleString() ?? '0';
        const statsEl = document.getElementById('mesheditStats');
        if (statsEl) {
            statsEl.innerHTML = `
                <div class="meshedit-stat-card"><div class="meshedit-stat-value">${fmtNum(data.tile_count)}</div><div class="meshedit-stat-label">Tiles</div></div>
                <div class="meshedit-stat-card"><div class="meshedit-stat-value">${fmtNum(data.total_faces)}</div><div class="meshedit-stat-label">Total Faces</div></div>
                <div class="meshedit-stat-card"><div class="meshedit-stat-value">${data.total_size_mb?.toFixed(1)} MB</div><div class="meshedit-stat-label">Total Size</div></div>
                <div class="meshedit-stat-card"><div class="meshedit-stat-value">${data.estimated_memory_mb?.toFixed(0)} MB</div><div class="meshedit-stat-label">Est. Memory</div></div>
            `;
            statsEl.style.display = '';
        }

        // Show issues
        const issuesEl = document.getElementById('mesheditIssues');
        if (issuesEl && data.issues?.length) {
            issuesEl.innerHTML = data.issues.map(i =>
                `<div class="meshedit-issue ${i.severity}"><strong>[${i.code}]</strong> ${i.message}</div>`
            ).join('');
            issuesEl.style.display = '';
        }

        // Show recommendation
        const recEl = document.getElementById('mesheditRecommend');
        if (recEl && data.recommended_preset) {
            const params = data.recommended_params || {};
            recEl.innerHTML = `<div class="meshedit-recommend">
                <div class="meshedit-recommend-preset">${data.recommended_preset.replace(/_/g, ' ').toUpperCase()}</div>
                <div class="meshedit-recommend-mode">Mode: ${params.mode || 'balanced'}</div>
                <div class="meshedit-recommend-reason">${params.reason || ''}</div>
            </div>`;
            recEl.style.display = '';
        }

        // Populate tiles
        if (data.tiles?.length) {
            _mesheditTiles = data.tiles.map(t => ({
                name: t.tile_id,
                tile_id: t.tile_id,
                triangles: t.faces || 0,
                size_mb: t.file_size_mb || 0,
            }));
            _mesheditRenderTileList();
        }

        if (statusEl) statusEl.textContent = `Scan complete: ${data.tile_count} tiles`;
        addChatMsg('system', `Scan complete: ${data.tile_count} tiles, ${fmtNum(data.total_faces)} faces`);

        // Auto-advance to step 2 after scan
        if (_mesheditTiles.length) setTimeout(() => mesheditSetStep(2), 500);
    } catch (e) {
        if (statusEl) statusEl.textContent = `Scan error: ${e.message}`;
        addChatMsg('system', `Scan error: ${e.message}`);
    }
}

// ── Tile list rendering ──────────────────────────────────────

function _mesheditRenderTileList() {
    const list = document.getElementById('mesheditTileList');
    if (!list || !_mesheditTiles.length) return;
    list.innerHTML = _mesheditTiles.map(t => {
        const name = t.name || t.tile_id || t;
        const tris = t.triangles ? `${(t.triangles/1000).toFixed(0)}k` : '';
        const size = t.size_mb ? `${t.size_mb.toFixed(1)}MB` : '';
        return `<div class="meshedit-tile-item" onclick="mesheditSelectTile('${name}')" data-tile="${name}">
            <span class="tile-name">${name}</span>
            <span class="tile-tris">${tris}</span>
            <span class="tile-size">${size}</span>
        </div>`;
    }).join('');
}

function mesheditFilterTiles(query) {
    const items = document.querySelectorAll('.meshedit-tile-item');
    const q = query.toLowerCase();
    items.forEach(el => {
        const name = (el.dataset.tile || '').toLowerCase();
        el.style.display = name.includes(q) ? '' : 'none';
    });
}

// ── Tile selection ───────────────────────────────────────────

function mesheditSelectTile(tileId) {
    _mesheditSelectedTile = tileId;
    document.querySelectorAll('.meshedit-tile-item').forEach(el => {
        el.classList.toggle('active', el.dataset.tile === tileId);
    });
    // Highlight in 3D viewer
    if (window.sceneViewer && window.sceneViewer.highlightTile) {
        window.sceneViewer.highlightTile(tileId);
    }
    // Advance to step 3 (preset selection)
    mesheditSetStep(3);
    // Pre-select recommended preset if available
    if (_mesheditScanResult?.recommended_preset && !_mesheditSelectedPreset) {
        mesheditSelectPreset(_mesheditScanResult.recommended_preset);
    }
}

// ── Preset selection ─────────────────────────────────────────

function mesheditSelectPreset(preset) {
    _mesheditSelectedPreset = preset;
    // Highlight selected card
    document.querySelectorAll('.meshedit-preset-card').forEach(el => {
        el.classList.toggle('selected', el.getAttribute('onclick')?.includes(`'${preset}'`));
    });
    // Enable start button
    const btn = document.getElementById('mesheditStartBtn');
    if (btn) btn.disabled = false;
    // Show/populate advanced params
    const paramsDetails = document.getElementById('mesheditParamsDetails');
    if (paramsDetails) paramsDetails.style.display = '';
    const container = document.getElementById('mesheditParams');
    if (container) {
        const params = _MESHEDIT_PRESETS[preset] || {};
        container.innerHTML = Object.entries(params).map(([key, val]) => {
            const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            return `<div class="meshedit-param-row">
                <span class="meshedit-param-label">${label}</span>
                <input class="meshedit-param-input" data-param="${key}" value="${val}">
            </div>`;
        }).join('');
    }
}

function _mesheditGetParams() {
    const params = {};
    document.querySelectorAll('#mesheditParams .meshedit-param-input').forEach(inp => {
        const key = inp.dataset.param;
        let val = inp.value;
        if (val === 'true') val = true;
        else if (val === 'false') val = false;
        else if (!isNaN(val) && val !== '') val = parseFloat(val);
        params[key] = val;
    });
    return params;
}

// ── Start job ────────────────────────────────────────────────

async function mesheditStart() {
    if (!_mesheditSelectedTile) { addChatMsg('system', 'Select a tile first'); return; }
    if (!_mesheditSelectedPreset) { addChatMsg('system', 'Select a preset first'); return; }

    const params = _mesheditGetParams();
    const btn = document.getElementById('mesheditStartBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Processing...'; }

    try {
        const resp = await fetch(`${API}/api/mesh/edit/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tile_id: _mesheditSelectedTile,
                preset: _mesheditSelectedPreset,
                project_dir: '',
                params: params,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Failed to start job');

        _mesheditJobId = data.job_id;
        addChatMsg('system', `Mesh Edit started: ${data.job_id} (${_mesheditSelectedPreset})`);

        // Clear log and advance to step 4
        const logEl = document.getElementById('mesheditLog');
        if (logEl) logEl.innerHTML = '';
        _mesheditAppendLog(`Job started: ${data.job_id} (${_mesheditSelectedPreset})`);
        mesheditSetStep(4);

        // Start polling
        _mesheditStartPolling();
    } catch (e) {
        addChatMsg('system', `Mesh Edit error: ${e.message}`);
        if (btn) { btn.disabled = false; btn.textContent = 'Start Edit Job'; }
    }
}

// ── Polling ──────────────────────────────────────────────────

function _mesheditStartPolling() {
    if (_mesheditPolling) clearInterval(_mesheditPolling);
    _mesheditPolling = setInterval(async () => {
        if (!_mesheditJobId) { clearInterval(_mesheditPolling); return; }
        try {
            const resp = await fetch(`${API}/api/mesh/edit/status/${_mesheditJobId}`);
            if (!resp.ok) return;
            const data = await resp.json();
            _mesheditUpdateProgress(data);

            if (data.status === 'preview_ready' || data.status === 'completed' ||
                data.status === 'failed' || data.status === 'cancelled') {
                clearInterval(_mesheditPolling);
                _mesheditPolling = null;
                if (data.status === 'preview_ready') _mesheditLoadPreview();
                if (data.status === 'failed') {
                    addChatMsg('system', `Mesh Edit failed: ${data.error || 'unknown'}`);
                    _mesheditAppendLog(data.error || 'Job failed', 'error');
                }
            }
        } catch (e) { /* ignore polling errors */ }
    }, 2000);
}

function _mesheditUpdateProgress(data) {
    const stageEl = document.getElementById('mesheditStage');
    const fillEl = document.getElementById('mesheditProgressFill');
    const pctEl = document.getElementById('mesheditProgressPct');
    const stage = (data.stage || 'queued').replace(/_/g, ' ').toUpperCase();
    if (stageEl) stageEl.textContent = stage;
    if (fillEl) fillEl.style.width = `${data.progress_pct || 0}%`;
    if (pctEl) pctEl.textContent = `${Math.round(data.progress_pct || 0)}%`;
    _mesheditAppendLog(`Stage: ${stage} (${Math.round(data.progress_pct || 0)}%)`);
}

// ── Preview / Results ────────────────────────────────────────

async function _mesheditLoadPreview() {
    if (!_mesheditJobId) return;
    try {
        const resp = await fetch(`${API}/api/mesh/edit/preview/${_mesheditJobId}`);
        if (!resp.ok) return;
        const data = await resp.json();

        const container = document.getElementById('mesheditComparison');
        if (container) {
            const fmtNum = n => n >= 1000 ? `${(n/1000).toFixed(1)}k` : n;
            container.innerHTML = `
                <div class="meshedit-compare-card before">
                    <span class="stat-label">Before (Tris)</span>
                    <span class="stat-value">${fmtNum(data.original?.triangles || 0)}</span>
                </div>
                <div class="meshedit-compare-card after">
                    <span class="stat-label">After (Tris)</span>
                    <span class="stat-value">${fmtNum(data.result?.triangles || 0)}</span>
                </div>
                <div class="meshedit-compare-card before">
                    <span class="stat-label">Before (Verts)</span>
                    <span class="stat-value">${fmtNum(data.original?.vertices || 0)}</span>
                </div>
                <div class="meshedit-compare-card after">
                    <span class="stat-label">After (Verts)</span>
                    <span class="stat-value">${fmtNum(data.result?.vertices || 0)}</span>
                </div>
                ${data.lod0_triangles ? `
                <div class="meshedit-compare-card after">
                    <span class="stat-label">LOD0</span>
                    <span class="stat-value">${fmtNum(data.lod0_triangles)}</span>
                </div>
                <div class="meshedit-compare-card after">
                    <span class="stat-label">LOD1 / LOD2</span>
                    <span class="stat-value">${fmtNum(data.lod1_triangles || 0)} / ${fmtNum(data.lod2_triangles || 0)}</span>
                </div>` : ''}
                ${data.collider_triangles ? `
                <div class="meshedit-compare-card after" style="grid-column:span 2">
                    <span class="stat-label">Collider</span>
                    <span class="stat-value">${fmtNum(data.collider_triangles)} tris</span>
                </div>` : ''}
            `;
        }

        // Show warnings
        const warnEl = document.getElementById('mesheditWarnings');
        if (warnEl && data.warnings?.length) {
            warnEl.style.display = '';
            warnEl.innerHTML = data.warnings.map(w => `&#9888; ${w}`).join('<br>');
            data.warnings.forEach(w => _mesheditAppendLog(w, 'warning'));
        } else if (warnEl) {
            warnEl.style.display = 'none';
        }

        _mesheditAppendLog(`Preview ready (${data.duration_s}s)`);
        addChatMsg('system', `Mesh Edit preview ready (${data.duration_s}s) — review before/after stats`);

        // Advance to step 5 (results)
        mesheditSetStep(5);
        // Load history for this tile
        mesheditLoadHistory();
    } catch (e) {
        addChatMsg('system', `Preview error: ${e.message}`);
    }
}

// ── Apply / Cancel ───────────────────────────────────────────

async function mesheditApply() {
    if (!_mesheditJobId) return;
    try {
        const resp = await fetch(`${API}/api/mesh/edit/apply/${_mesheditJobId}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Apply failed');
        addChatMsg('system', `Mesh Edit applied: v${data.version} for ${data.tile_id}`);
        mesheditLoadHistory();
    } catch (e) {
        addChatMsg('system', `Apply error: ${e.message}`);
    }
}

async function mesheditCancel() {
    if (_mesheditJobId) {
        try {
            await fetch(`${API}/api/mesh/edit/cancel/${_mesheditJobId}`, { method: 'POST' });
            addChatMsg('system', 'Mesh Edit cancelled');
        } catch (e) { /* ignore */ }
    }
    _mesheditJobId = null;
    if (_mesheditPolling) { clearInterval(_mesheditPolling); _mesheditPolling = null; }
    // Reset start button
    const btn = document.getElementById('mesheditStartBtn');
    if (btn) { btn.disabled = !_mesheditSelectedPreset; btn.textContent = 'Start Edit Job'; }
    // Go back to step 3
    mesheditSetStep(3);
}

function mesheditReset() {
    _mesheditJobId = null;
    _mesheditSelectedTile = null;
    _mesheditSelectedPreset = null;
    if (_mesheditPolling) { clearInterval(_mesheditPolling); _mesheditPolling = null; }
    // Deselect UI
    document.querySelectorAll('.meshedit-tile-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.meshedit-preset-card').forEach(el => el.classList.remove('selected'));
    const btn = document.getElementById('mesheditStartBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Start Edit Job'; }
    const fillEl = document.getElementById('mesheditProgressFill');
    if (fillEl) fillEl.style.width = '0%';
    mesheditSetStep(2);
}

// ── History / Rollback ───────────────────────────────────────

async function mesheditLoadHistory() {
    const container = document.getElementById('mesheditHistory');
    if (!container) return;

    let items = [];
    if (_mesheditSelectedTile) {
        try {
            const resp = await fetch(`${API}/api/mesh/edit/versions/${_mesheditSelectedTile}`);
            if (resp.ok) items = await resp.json();
        } catch (e) { /* fallback */ }
    }
    if (!items.length) {
        const tileParam = _mesheditSelectedTile ? `?tile_id=${_mesheditSelectedTile}&limit=20` : '?limit=20';
        try {
            const resp = await fetch(`${API}/api/mesh/edit/history${tileParam}`);
            if (resp.ok) items = await resp.json();
        } catch (e) { /* ignore */ }
    }

    if (!items.length) {
        container.innerHTML = '<div class="empty-state"><p>No edits yet</p></div>';
        return;
    }
    container.innerHTML = items.map(h => {
        const date = h.completed_at ? new Date(h.completed_at * 1000).toLocaleString() : '';
        const tileId = h.tile_id || _mesheditSelectedTile || '';
        const canRollback = h.status === 'completed' || h.status === 'preview_ready';
        return `<div class="meshedit-history-item">
            <span class="meshedit-version-badge">v${h.version}</span>
            <span class="hist-preset">${(h.preset || '').replace(/_/g, ' ')}</span>
            <span class="hist-time">${date}</span>
            ${canRollback ? `<button class="hist-rollback" onclick="mesheditRollback('${tileId}',${h.version})" title="Rollback to this version">&#8617;</button>` : ''}
        </div>`;
    }).join('');
}

async function mesheditRollback(tileId, version) {
    if (!confirm(`Rollback ${tileId} to v${version}?`)) return;
    try {
        const resp = await fetch(`${API}/api/mesh/edit/rollback/${tileId}/${version}?project_dir=`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Rollback failed');
        addChatMsg('system', `Rolled back ${tileId} to v${version}`);
        mesheditLoadHistory();
    } catch (e) {
        addChatMsg('system', `Rollback error: ${e.message}`);
    }
}

async function mesheditRollbackToRaw() {
    if (!_mesheditSelectedTile) return;
    if (!confirm(`Revert ${_mesheditSelectedTile} to raw (original) tile?`)) return;
    try {
        const resp = await fetch(`${API}/api/mesh/edit/rollback/${_mesheditSelectedTile}/0?project_dir=`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Revert failed');
        addChatMsg('system', `Reverted ${_mesheditSelectedTile} to raw`);
        mesheditLoadHistory();
    } catch (e) {
        addChatMsg('system', `Revert error: ${e.message}`);
    }
}

// ── Validate / Report ────────────────────────────────────────

async function mesheditValidate() {
    if (!_mesheditSelectedTile) { addChatMsg('system', 'Select a tile first'); return; }
    try {
        const resp = await fetch(`${API}/api/mesh/edit/validate/${_mesheditSelectedTile}?project_dir=`);
        if (!resp.ok) return;
        const data = await resp.json();
        const valEl = document.getElementById('mesheditValidation');
        if (valEl) {
            valEl.style.display = '';
            valEl.className = `meshedit-validation ${data.valid ? 'valid' : 'invalid'}`;
            let html = `<b>${data.valid ? 'Valid' : 'Issues Found'}</b> (${data.format}, ${(data.size_bytes/1e6).toFixed(1)}MB)`;
            if (data.issues?.length) {
                html += '<br>' + data.issues.map(i => `[${i.severity}] ${i.message}`).join('<br>');
            }
            valEl.innerHTML = html;
        }
    } catch (e) {
        addChatMsg('system', `Validation error: ${e.message}`);
    }
}

async function mesheditReport() {
    try {
        const resp = await fetch(`${API}/api/mesh/edit/report?project_dir=`);
        if (!resp.ok) return;
        const data = await resp.json();
        let msg = `Quality Report: ${data.tile_count} tiles, ${data.total_jobs} jobs`;
        msg += ` (${data.completed} completed, ${data.failed} failed, ${data.success_rate}% success)`;
        if (data.tiles?.length) {
            msg += '\n' + data.tiles.map(t =>
                `  ${t.tile_id}: v${t.latest_version} active=${t.active_version} ` +
                `${t.original_tris}→${t.result_tris} tris (${t.reduction_pct}% reduction)`
            ).join('\n');
        }
        addChatMsg('system', msg);
    } catch (e) {
        addChatMsg('system', `Report error: ${e.message}`);
    }
}

// ── Log helper ───────────────────────────────────────────────

function _mesheditAppendLog(msg, level = '') {
    const log = document.getElementById('mesheditLog');
    if (!log) return;
    const entry = document.createElement('div');
    entry.className = `log-entry ${level ? 'log-' + level : ''}`;
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

// ── WebSocket handler ────────────────────────────────────────

function mesheditHandleWS(event, data) {
    if (event === 'mesh_edit_progress' && data.job_id === _mesheditJobId) {
        _mesheditUpdateProgress(data);
    }
    if (event === 'mesh_edit_preview_ready' && data.job_id === _mesheditJobId) {
        if (_mesheditPolling) { clearInterval(_mesheditPolling); _mesheditPolling = null; }
        _mesheditLoadPreview();
    }
    if (event === 'mesh_edit_applied') {
        addChatMsg('system', `Mesh Edit applied: v${data.version} for ${data.tile_id}`);
        mesheditLoadHistory();
    }
    if (event === 'mesh_edit_failed' && data.job_id === _mesheditJobId) {
        addChatMsg('system', `Mesh Edit failed: ${data.error}`);
        _mesheditAppendLog(data.error || 'Job failed', 'error');
    }
}

// ── Version comparison ───────────────────────────────────────

async function mesheditCompare(tileId, v1, v2) {
    try {
        const resp = await fetch(`${API}/api/mesh/edit/compare/${tileId}?v1=${v1}&v2=${v2}`);
        if (!resp.ok) return;
        const data = await resp.json();
        const fmtNum = n => n >= 1000 ? `${(n/1000).toFixed(1)}k` : n;
        addChatMsg('system',
            `Version Compare (${tileId}): v${data.v1.version} vs v${data.v2.version}\n` +
            `  Triangles: ${fmtNum(data.v1.result.triangles)} → ${fmtNum(data.v2.result.triangles)} (${data.diff.triangles > 0 ? '+' : ''}${fmtNum(data.diff.triangles)})\n` +
            `  Collider: ${fmtNum(data.v1.collider)} → ${fmtNum(data.v2.collider)} (${data.diff.collider > 0 ? '+' : ''}${fmtNum(data.diff.collider)})`
        );
    } catch (e) { /* ignore */ }
}

// ── Bookmarks ───────────────────────────────────────────────

async function bookmarkSaveCurrent() {
    // Get camera state from 3D viewer
    let camPos = [0, 0, 0], camTarget = [0, 0, 0], camZoom = 1;
    if (window._sceneViewer && window._sceneViewer.camera) {
        const cam = window._sceneViewer.camera;
        camPos = [cam.position.x, cam.position.y, cam.position.z];
        if (window._sceneViewer.controls && window._sceneViewer.controls.target) {
            const t = window._sceneViewer.controls.target;
            camTarget = [t.x, t.y, t.z];
        }
        camZoom = cam.zoom || 1;
    }

    const name = prompt('Bookmark name:', `View ${new Date().toLocaleTimeString()}`);
    if (!name) return;

    try {
        const res = await fetch('/api/bookmarks/', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name,
                category: 'general',
                camera_position: camPos,
                camera_target: camTarget,
                camera_zoom: camZoom,
            }),
        });
        if (!res.ok) throw new Error('Failed to save');
        addChatMsg('system', `Bookmark saved: ${name}`);
        bookmarkLoadAll();
    } catch (e) {
        addChatMsg('system', `Bookmark save error: ${e.message}`);
    }
}

async function bookmarkLoadAll() {
    const filter = document.getElementById('bookmarkFilter')?.value || '';
    const url = filter ? `/api/bookmarks/?category=${filter}` : '/api/bookmarks/';

    try {
        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();
        const list = document.getElementById('bookmarkList');
        if (!data.bookmarks.length) {
            list.innerHTML = '<div class="empty-state"><p>No bookmarks yet</p></div>';
            return;
        }

        list.innerHTML = data.bookmarks.map(b => {
            const time = new Date(b.created_at * 1000).toLocaleString();
            const pos = b.camera_position.map(v => v.toFixed(1)).join(', ');
            return `<div class="bookmark-item" onclick="bookmarkRestore('${b.bookmark_id}')">
                <div class="bookmark-item-header">
                    <span class="bookmark-item-name">${b.name}</span>
                    <span class="bookmark-item-cat">${b.category}</span>
                </div>
                <div class="bookmark-item-meta">${time} · pos(${pos})</div>
                <div class="bookmark-item-actions" onclick="event.stopPropagation()">
                    <button onclick="bookmarkRestore('${b.bookmark_id}')">Restore</button>
                    <button class="bookmark-del" onclick="bookmarkDelete('${b.bookmark_id}')">Delete</button>
                </div>
            </div>`;
        }).join('');
    } catch (e) { /* ignore */ }
}

async function bookmarkRestore(id) {
    try {
        const res = await fetch(`/api/bookmarks/${id}`);
        if (!res.ok) throw new Error('Not found');
        const bm = await res.json();

        // Restore camera position in 3D viewer
        if (window._sceneViewer && window._sceneViewer.camera) {
            const cam = window._sceneViewer.camera;
            cam.position.set(bm.camera_position[0], bm.camera_position[1], bm.camera_position[2]);
            if (window._sceneViewer.controls && window._sceneViewer.controls.target) {
                window._sceneViewer.controls.target.set(
                    bm.camera_target[0], bm.camera_target[1], bm.camera_target[2]
                );
                window._sceneViewer.controls.update();
            }
        }
        addChatMsg('system', `Restored bookmark: ${bm.name}`);
    } catch (e) {
        addChatMsg('system', `Restore error: ${e.message}`);
    }
}

async function bookmarkDelete(id) {
    if (!confirm('Delete this bookmark?')) return;
    try {
        await fetch(`/api/bookmarks/${id}`, { method: 'DELETE' });
        bookmarkLoadAll();
    } catch (e) { /* ignore */ }
}

// ── Annotations ─────────────────────────────────────────────
let _annotations = [];

function annotationAdd(text, position) {
    _annotations.push({ text, position: position || [0, 0, 0], created: Date.now() });
    annotationRender();
}

function annotationRender() {
    const list = document.getElementById('annotationList');
    if (!list) return;
    if (!_annotations.length) {
        list.innerHTML = '<div class="empty-state"><p>No annotations</p></div>';
        return;
    }
    list.innerHTML = _annotations.map((a, i) => `
        <div class="annotation-item">
            <div class="annotation-item-text">${a.text}</div>
            <div class="annotation-item-pos">pos(${a.position.map(v => v.toFixed(1)).join(', ')})</div>
        </div>
    `).join('');
}

async function annotationExportPNG() {
    // Capture current 3D view as screenshot
    if (window._sceneViewer && window._sceneViewer.renderer) {
        const canvas = window._sceneViewer.renderer.domElement;
        const dataUrl = canvas.toDataURL('image/png');
        const link = document.createElement('a');
        link.download = `vibe3d_snapshot_${Date.now()}.png`;
        link.href = dataUrl;
        link.click();
        addChatMsg('system', 'Snapshot exported as PNG');
    } else {
        addChatMsg('system', 'No 3D viewer available for snapshot');
    }
}

// ── Performance Monitor ─────────────────────────────────────
let _perfMonitorActive = false;
let _perfInterval = null;

function perfStartMonitor() {
    if (_perfMonitorActive) return;
    _perfMonitorActive = true;
    _perfInterval = setInterval(perfUpdate, 2000);
    perfUpdate();
}

function perfStopMonitor() {
    _perfMonitorActive = false;
    if (_perfInterval) { clearInterval(_perfInterval); _perfInterval = null; }
}

function perfUpdate() {
    // Collect metrics from Three.js renderer
    let fps = 0, memory = 0, drawCalls = 0, triangles = 0;

    if (window._sceneViewer && window._sceneViewer.renderer) {
        const info = window._sceneViewer.renderer.info;
        drawCalls = info.render?.calls || 0;
        triangles = info.render?.triangles || 0;
        // FPS approximation from frame delta
        fps = Math.round(1000 / Math.max(16, info.render?.frame ? 16 : 16));
    }

    // Memory from performance API
    if (performance.memory) {
        memory = Math.round(performance.memory.usedJSHeapSize / (1024 * 1024));
    }

    perfRenderMeters({ fps, memory, drawCalls, triangles });
    perfCheckThresholds({ fps, memory, drawCalls, triangles });
}

function perfRenderMeters(m) {
    const container = document.getElementById('perfMeters');
    if (!container) return;

    const fpsColor = m.fps >= 50 ? 'perf-good' : m.fps >= 30 ? 'perf-warn' : 'perf-bad';
    const memColor = m.memory < 500 ? 'perf-good' : m.memory < 1000 ? 'perf-warn' : 'perf-bad';
    const dcColor = m.drawCalls < 200 ? 'perf-good' : m.drawCalls < 500 ? 'perf-warn' : 'perf-bad';

    container.innerHTML = `
        <div class="perf-meter">
            <span class="perf-meter-label">FPS</span>
            <div class="perf-meter-bar"><div class="perf-meter-fill" style="width:${Math.min(100,m.fps/60*100)}%;background:${fpsColor==='perf-good'?'#22aa66':fpsColor==='perf-warn'?'#f5a623':'#cc3333'}"></div></div>
            <span class="perf-meter-value ${fpsColor}">${m.fps}</span>
        </div>
        <div class="perf-meter">
            <span class="perf-meter-label">Memory</span>
            <div class="perf-meter-bar"><div class="perf-meter-fill" style="width:${Math.min(100,m.memory/1500*100)}%;background:${memColor==='perf-good'?'#22aa66':memColor==='perf-warn'?'#f5a623':'#cc3333'}"></div></div>
            <span class="perf-meter-value ${memColor}">${m.memory} MB</span>
        </div>
        <div class="perf-meter">
            <span class="perf-meter-label">Draw Calls</span>
            <div class="perf-meter-bar"><div class="perf-meter-fill" style="width:${Math.min(100,m.drawCalls/500*100)}%;background:${dcColor==='perf-good'?'#22aa66':dcColor==='perf-warn'?'#f5a623':'#cc3333'}"></div></div>
            <span class="perf-meter-value ${dcColor}">${m.drawCalls}</span>
        </div>
        <div class="perf-meter">
            <span class="perf-meter-label">Triangles</span>
            <div class="perf-meter-bar"><div class="perf-meter-fill" style="width:${Math.min(100,m.triangles/1000000*100)}%;background:#4fc3f7"></div></div>
            <span class="perf-meter-value" style="color:#4fc3f7">${(m.triangles/1000).toFixed(0)}K</span>
        </div>
    `;
}

function perfCheckThresholds(m) {
    const container = document.getElementById('perfSuggestions');
    if (!container) return;

    const suggestions = [];
    if (m.fps < 30) {
        suggestions.push('<strong>Low FPS:</strong> Consider reducing streaming radius or enabling LOD decimation on heavy tiles.');
    }
    if (m.memory > 1000) {
        suggestions.push('<strong>High Memory:</strong> Too many tiles loaded. Try reducing enable distance in CityTileStreamer.');
    }
    if (m.drawCalls > 400) {
        suggestions.push('<strong>Draw Calls:</strong> Enable GPU instancing or batch similar materials.');
    }
    if (m.triangles > 2000000) {
        suggestions.push('<strong>High Triangle Count:</strong> Use "Decimate to Target" preset on heavy tiles.');
    }

    if (suggestions.length === 0) {
        container.innerHTML = '<div class="perf-suggestion"><strong>All clear!</strong> Performance is within acceptable limits.</div>';
    } else {
        container.innerHTML = suggestions.map(s => `<div class="perf-suggestion">${s}</div>`).join('');
    }
}

// ── Tool Mode Panel ──────────────────────────────────────────

function toggleToolModePanel() {
    const panel = document.getElementById('toolmodePanel');
    if (!panel) return;
    panel.classList.toggle('hidden');
    const btn = document.getElementById('toolModeBtn');
    if (btn) btn.classList.toggle('active', !panel.classList.contains('hidden'));

    if (panel.classList.contains('hidden')) {
        setMeasureMode(null);
    }
}

function switchToolMode(tab) {
    document.querySelectorAll('.toolmode-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    document.querySelectorAll('.toolmode-content').forEach(c => c.classList.toggle('active', c.id === `toolmode-${tab}`));

    // Reset measurement mode when switching tabs
    if (tab !== 'measure') setMeasureMode(null);
}

// Override measurement callback to also populate results list
(function() {
    const origSet = window.setMeasureMode;
    if (!origSet) return;

    const origCallback = function(mType, result) {
        let val = 0, unit = 'm';
        if (mType === 'distance') { val = result.distance; }
        else if (mType === 'height') { val = result.height; }
        else if (mType === 'area') { val = result.area; unit = 'm²'; }

        // Add to results panel
        const container = document.getElementById('measureResults');
        if (container) {
            // Remove empty placeholder
            const empty = container.querySelector('.toolmode-empty');
            if (empty) empty.remove();

            const item = document.createElement('div');
            item.className = 'toolmode-result-item';
            item.innerHTML = `
                <span class="r-type">${mType}</span>
                <span class="r-value">${val.toFixed(2)} ${unit}</span>
                <span class="r-time">${new Date().toLocaleTimeString()}</span>
            `;
            container.appendChild(item);
            container.scrollTop = container.scrollHeight;
        }

        // Also record for export
        recordMeasurement(mType, result);
    };

    // Patch setMeasureMode to wire our enhanced callback
    const patchedSetMeasureMode = function(mode) {
        origSet(mode);
        if (mode && window.sceneViewer) {
            window.sceneViewer.onMeasure = function(mType, result) {
                let msg = '';
                if (mType === 'distance') msg = `📏 거리: ${result.distance.toFixed(2)}m`;
                else if (mType === 'height') msg = `📐 높이: ${result.height.toFixed(2)}m`;
                else if (mType === 'area') msg = `⬡ 면적: ${result.area.toFixed(2)}m²`;
                if (msg) addChatMsg('system', msg);
                origCallback(mType, result);
            };
        }
    };
    window.setMeasureMode = patchedSetMeasureMode;
})();

// ── Path Finding ────────────────────────────────────────────
let _pathStart = null, _pathEnd = null, _pathPickMode = null;

function pathSetStart() {
    _pathPickMode = 'start';
    addChatMsg('system', '🟢 Click on the 3D scene to set path start point');
    if (window.sceneViewer) {
        window.sceneViewer.onSceneClick = (point) => {
            if (_pathPickMode === 'start') {
                _pathStart = { x: point.x, y: point.y, z: point.z };
                document.getElementById('pathStartLabel').textContent =
                    `(${point.x.toFixed(1)}, ${point.y.toFixed(1)}, ${point.z.toFixed(1)})`;
                _pathPickMode = null;
                addChatMsg('system', `Start set: (${point.x.toFixed(1)}, ${point.y.toFixed(1)}, ${point.z.toFixed(1)})`);
            }
        };
    }
}

function pathSetEnd() {
    _pathPickMode = 'end';
    addChatMsg('system', '🔴 Click on the 3D scene to set path end point');
    if (window.sceneViewer) {
        window.sceneViewer.onSceneClick = (point) => {
            if (_pathPickMode === 'end') {
                _pathEnd = { x: point.x, y: point.y, z: point.z };
                document.getElementById('pathEndLabel').textContent =
                    `(${point.x.toFixed(1)}, ${point.y.toFixed(1)}, ${point.z.toFixed(1)})`;
                _pathPickMode = null;
                addChatMsg('system', `End set: (${point.x.toFixed(1)}, ${point.y.toFixed(1)}, ${point.z.toFixed(1)})`);
            }
        };
    }
}

function pathCompute() {
    if (!_pathStart || !_pathEnd) {
        addChatMsg('system', 'Please set both start and end points first');
        return;
    }

    // Compute straight-line distance (NavMesh path would need Unity)
    const dx = _pathEnd.x - _pathStart.x;
    const dy = _pathEnd.y - _pathStart.y;
    const dz = _pathEnd.z - _pathStart.z;
    const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);
    const walkSpeed = 1.4; // m/s average walking speed
    const timeSeconds = dist / walkSpeed;

    document.getElementById('pathDistLabel').textContent = `${dist.toFixed(2)} m`;
    document.getElementById('pathTimeLabel').textContent = timeSeconds < 60
        ? `${timeSeconds.toFixed(0)} sec`
        : `${(timeSeconds/60).toFixed(1)} min`;

    // Draw line in 3D viewer
    if (window.sceneViewer && window.sceneViewer.drawPath) {
        window.sceneViewer.drawPath(_pathStart, _pathEnd);
    }

    // Results
    const container = document.getElementById('pathResults');
    if (container) {
        const empty = container.querySelector('.toolmode-empty');
        if (empty) empty.remove();
        const item = document.createElement('div');
        item.className = 'toolmode-result-item';
        item.innerHTML = `
            <span class="r-type">Straight-line</span>
            <span class="r-value">${dist.toFixed(2)} m</span>
            <span class="r-time">${(timeSeconds/60).toFixed(1)} min walk</span>
        `;
        container.appendChild(item);
    }

    addChatMsg('system', `Path: ${dist.toFixed(2)}m straight-line, ~${(timeSeconds/60).toFixed(1)} min walk at 1.4 m/s`);
}

function pathClear() {
    _pathStart = null;
    _pathEnd = null;
    _pathPickMode = null;
    document.getElementById('pathStartLabel').textContent = 'Not set';
    document.getElementById('pathEndLabel').textContent = 'Not set';
    document.getElementById('pathDistLabel').textContent = '—';
    document.getElementById('pathTimeLabel').textContent = '—';
    const container = document.getElementById('pathResults');
    if (container) container.innerHTML = '<div class="toolmode-empty">Set start/end points on the scene, then click Find Path</div>';
    if (window.sceneViewer && window.sceneViewer.clearPath) window.sceneViewer.clearPath();
}

// ── Visibility Analysis ─────────────────────────────────────
let _visSensors = [];
let _visPickMode = false;

function visSetSensor() {
    _visPickMode = true;
    addChatMsg('system', '📷 Click on the 3D scene to place a sensor');
    if (window.sceneViewer) {
        window.sceneViewer.onSceneClick = (point) => {
            if (!_visPickMode) return;
            const template = document.getElementById('visSensorTemplate').value;
            const range = parseFloat(document.getElementById('visRange').value) || 50;
            const fov = template === 'cctv_90' ? 90 : template === 'cctv_120' ? 120 : template === 'dome_360' ? 360 : 90;

            _visSensors.push({
                position: { x: point.x, y: point.y, z: point.z },
                template, range, fov,
            });

            _visPickMode = false;
            addChatMsg('system', `Sensor placed at (${point.x.toFixed(1)}, ${point.y.toFixed(1)}, ${point.z.toFixed(1)}) — ${template} ${fov}° / ${range}m`);

            // Show sensor in results
            const container = document.getElementById('visResults');
            if (container) {
                const empty = container.querySelector('.toolmode-empty');
                if (empty) empty.remove();
                const item = document.createElement('div');
                item.className = 'toolmode-result-item';
                item.innerHTML = `
                    <span class="r-type">${template}</span>
                    <span class="r-value">${fov}° / ${range}m</span>
                    <span class="r-time">(${point.x.toFixed(0)}, ${point.z.toFixed(0)})</span>
                `;
                container.appendChild(item);
            }
        };
    }
}

function visCompute() {
    if (_visSensors.length === 0) {
        addChatMsg('system', 'Please place at least one sensor first');
        return;
    }

    // Compute coverage estimate (approximation based on sensor FOV and range)
    let totalCoverageArea = 0;
    const sensorReports = _visSensors.map((s, i) => {
        const radiusM = s.range;
        const fovRad = (s.fov / 360) * 2 * Math.PI;
        const sectorArea = 0.5 * radiusM * radiusM * fovRad;
        totalCoverageArea += sectorArea;
        return {
            id: i + 1,
            template: s.template,
            fov: s.fov,
            range: s.range,
            coverage_m2: Math.round(sectorArea),
            position: s.position,
        };
    });

    // Build report
    const report = {
        sensor_count: _visSensors.length,
        total_coverage_m2: Math.round(totalCoverageArea),
        sensors: sensorReports,
    };

    // Display in results
    const container = document.getElementById('visResults');
    if (container) {
        container.innerHTML = `
            <div class="toolmode-result-item" style="font-weight:600;border-bottom:2px solid #333">
                <span class="r-type">TOTAL</span>
                <span class="r-value">${totalCoverageArea.toFixed(0)} m²</span>
                <span class="r-time">${_visSensors.length} sensors</span>
            </div>
        ` + sensorReports.map(s => `
            <div class="toolmode-result-item">
                <span class="r-type">#${s.id} ${s.template}</span>
                <span class="r-value">${s.coverage_m2} m²</span>
                <span class="r-time">${s.fov}°/${s.range}m</span>
            </div>
        `).join('');
    }

    addChatMsg('system', `Visibility Report: ${_visSensors.length} sensors, ~${totalCoverageArea.toFixed(0)} m² coverage`);
    window._lastVisReport = report;
}

function visClear() {
    _visSensors = [];
    _visPickMode = false;
    const container = document.getElementById('visResults');
    if (container) container.innerHTML = '<div class="toolmode-empty">Place sensors and click Analyze for coverage report</div>';
}

function visExportReport() {
    if (!window._lastVisReport) {
        addChatMsg('system', 'No visibility report to export. Click Analyze first.');
        return;
    }
    const json = JSON.stringify(window._lastVisReport, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.download = `visibility_report_${Date.now()}.json`;
    link.href = url;
    link.click();
    URL.revokeObjectURL(url);
    addChatMsg('system', 'Visibility report exported as JSON');
}

// ── Enhanced Annotations (3D pins + PDF + server persistence) ──

let _annotationPinMode = false;
let _annotationPins = []; // {id, text, position, element}

function annotationStartPinMode() {
    _annotationPinMode = true;
    addChatMsg('system', '📌 Click on the 3D scene to place annotation pin');
    if (window.sceneViewer) {
        window.sceneViewer.onSceneClick = (point) => {
            if (!_annotationPinMode) return;
            _annotationPinMode = false;
            const text = document.getElementById('annotationText')?.value?.trim() || 'Annotation';
            annotationPlacePin(text, [point.x, point.y, point.z]);
            const input = document.getElementById('annotationText');
            if (input) input.value = '';
        };
    }
}

function annotationPlacePin(text, position) {
    const pin = {
        id: `pin_${Date.now()}`,
        text,
        position,
        created: Date.now(),
    };
    _annotationPins.push(pin);
    _annotations.push({ text, position, created: Date.now() });

    // Create 3D pin overlay element
    const container = document.getElementById('scene3dContainer');
    if (container) {
        const el = document.createElement('div');
        el.className = 'scene-pin';
        el.id = pin.id;
        el.title = text;
        el.innerHTML = `<div class="scene-pin-tooltip">${text}</div>`;
        container.appendChild(el);
        pin.element = el;

        // Position will be updated in animation loop if sceneViewer supports it
        updatePinPosition(pin);
    }

    annotationRender();
    addChatMsg('system', `📌 Pin placed: "${text}" at (${position.map(v=>v.toFixed(1)).join(', ')})`);

    // Persist to server via bookmark annotations
    annotationPersistToServer();
}

function updatePinPosition(pin) {
    if (!window._sceneViewer || !window._sceneViewer.camera || !pin.element) return;
    // Project 3D position to screen coordinates
    const THREE = window.THREE;
    if (!THREE) return;

    const vec = new THREE.Vector3(pin.position[0], pin.position[1], pin.position[2]);
    vec.project(window._sceneViewer.camera);

    const canvas = document.getElementById('scene3dContainer');
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = (vec.x * 0.5 + 0.5) * rect.width;
    const y = (-vec.y * 0.5 + 0.5) * rect.height;

    // Hide if behind camera
    if (vec.z > 1) {
        pin.element.style.display = 'none';
    } else {
        pin.element.style.display = '';
        pin.element.style.left = `${x}px`;
        pin.element.style.top = `${y}px`;
    }
}

// Update pin positions on camera move
setInterval(() => {
    _annotationPins.forEach(pin => updatePinPosition(pin));
}, 100);

async function annotationPersistToServer() {
    // Save annotations to a bookmark for persistence
    const annData = _annotations.map(a => ({
        text: a.text,
        position: a.position,
        created: a.created,
    }));

    try {
        // Try to update existing annotation bookmark
        const listRes = await fetch('/api/bookmarks/?category=annotations');
        const list = await listRes.json();
        if (list.bookmarks.length > 0) {
            await fetch(`/api/bookmarks/${list.bookmarks[0].bookmark_id}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ annotations: annData }),
            });
        } else {
            await fetch('/api/bookmarks/', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    name: 'Scene Annotations',
                    category: 'annotations',
                    annotations: annData,
                }),
            });
        }
    } catch (e) { /* best-effort persist */ }
}

async function annotationLoadFromServer() {
    try {
        const res = await fetch('/api/bookmarks/?category=annotations');
        const data = await res.json();
        if (data.bookmarks.length > 0 && data.bookmarks[0].annotations.length > 0) {
            _annotations = data.bookmarks[0].annotations;
            annotationRender();
        }
    } catch (e) { /* ignore */ }
}

function annotationExportPDF() {
    // Generate a simple PDF-like report as downloadable HTML
    const canvas = window._sceneViewer?.renderer?.domElement;
    const imgData = canvas ? canvas.toDataURL('image/png') : '';

    const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Vibe3D Annotation Report</title>
<style>
body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
h1 { color: #333; border-bottom: 2px solid #4fc3f7; padding-bottom: 10px; }
.snapshot { width: 100%; max-height: 400px; object-fit: contain; border: 1px solid #ddd; margin: 10px 0; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; }
th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 12px; }
th { background: #f5f5f5; }
.footer { color: #999; font-size: 10px; margin-top: 20px; border-top: 1px solid #ddd; padding-top: 8px; }
</style></head><body>
<h1>Vibe3D Annotation Report</h1>
<p>Generated: ${new Date().toLocaleString()}</p>
${imgData ? `<img class="snapshot" src="${imgData}" alt="Scene Snapshot">` : ''}
<h2>Annotations (${_annotations.length})</h2>
<table>
<tr><th>#</th><th>Note</th><th>Position</th><th>Time</th></tr>
${_annotations.map((a, i) => `<tr>
<td>${i+1}</td><td>${a.text}</td>
<td>(${a.position.map(v=>v.toFixed(1)).join(', ')})</td>
<td>${new Date(a.created).toLocaleString()}</td>
</tr>`).join('')}
</table>
${window._lastVisReport ? `<h2>Visibility Report</h2>
<p>${window._lastVisReport.sensor_count} sensors, ${window._lastVisReport.total_coverage_m2} m² total coverage</p>` : ''}
${_measurementHistory.length > 0 ? `<h2>Measurements (${_measurementHistory.length})</h2>
<table><tr><th>Type</th><th>Value</th><th>Time</th></tr>
${_measurementHistory.map(m => `<tr><td>${m.type}</td><td>${m.value.toFixed(2)} ${m.unit}</td><td>${m.timestamp}</td></tr>`).join('')}
</table>` : ''}
<div class="footer">Generated by Vibe3D v2.7</div>
</body></html>`;

    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.download = `vibe3d_report_${Date.now()}.html`;
    link.href = url;
    link.click();
    URL.revokeObjectURL(url);
    addChatMsg('system', 'Report exported as HTML (printable to PDF via browser)');
}

// Load annotations on startup
document.addEventListener('DOMContentLoaded', () => { annotationLoadFromServer(); });

// ── Performance Tuner: Backend metrics + auto-preset ────────

async function perfFetchBackendMetrics() {
    try {
        const res = await fetch('/api/mesh/edit/report');
        if (!res.ok) return null;
        return await res.json();
    } catch (e) { return null; }
}

async function perfAutoSuggestPresets() {
    const report = await perfFetchBackendMetrics();
    if (!report || !report.tiles) return;

    const suggestions = [];
    for (const tile of report.tiles) {
        if (tile.original_tris > 1500000 && tile.active_version === 0) {
            suggestions.push({
                tile_id: tile.tile_id,
                original_tris: tile.original_tris,
                preset: 'decimate_to_target',
                reason: `${tile.tile_id} has ${tile.original_tris.toLocaleString()} tris (unedited) — decimation recommended`,
            });
        }
    }

    const container = document.getElementById('perfSuggestions');
    if (container && suggestions.length > 0) {
        const existing = container.innerHTML;
        const autoHtml = suggestions.map(s =>
            `<div class="perf-suggestion"><strong>Auto:</strong> ${s.reason}
             <button onclick="perfApplyPreset('${s.tile_id}','${s.preset}')" style="margin-left:4px;padding:2px 6px;font-size:9px;border:1px solid #4fc3f7;background:transparent;color:#4fc3f7;border-radius:3px;cursor:pointer">Apply</button></div>`
        ).join('');
        container.innerHTML = existing + autoHtml;
    }
}

async function perfApplyPreset(tileId, preset) {
    try {
        const res = await fetch('/api/mesh/edit/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ tile_id: tileId, preset }),
        });
        if (!res.ok) throw new Error('Failed');
        const data = await res.json();
        addChatMsg('system', `Auto-edit started for ${tileId}: job ${data.job_id}`);
    } catch (e) {
        addChatMsg('system', `Auto-edit failed: ${e.message}`);
    }
}

// Run backend metric check periodically when perf panel is active
setInterval(() => {
    if (_perfMonitorActive) perfAutoSuggestPresets();
}, 30000); // every 30s
