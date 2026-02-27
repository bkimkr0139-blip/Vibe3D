/**
 * Drone2Twin Wizard — 7-step pipeline UI
 *
 * Steps: Project → Ingest QA → Reconstruction → Optimize → Unity Import → WebGL Build → Deploy
 * Integrates with existing Vibe3D patterns: approval cards, job log, WebSocket events.
 */

const DRONE_STEPS = [
    { id: 'project',  label: '프로젝트',     icon: '📁' },
    { id: 'ingest',   label: 'Ingest QA',    icon: '🔍' },
    { id: 'recon',    label: '재구성',        icon: '🏗️' },
    { id: 'optimize', label: '최적화',        icon: '⚙️' },
    { id: 'unity',    label: 'Unity Import',  icon: '🎮' },
    { id: 'webgl',    label: 'WebGL Build',   icon: '🌐' },
    { id: 'deploy',   label: '배포',          icon: '🚀' },
];

class DroneWizard {
    constructor() {
        this._currentStep = 0;
        this._project = null;          // current DroneProject
        this._qaReport = null;
        this._container = null;
        this._initialized = false;
        this._selectedInputOption = 'vendor_pack';
        this._objTiles = null;         // scanned OBJ tile data
    }

    init(containerId) {
        this._container = document.getElementById(containerId);
        if (!this._container) return;
        this._render();
        this._initialized = true;
    }

    // ── Rendering ───────────────────────────────────────────

    _render() {
        this._container.innerHTML = '';

        // Stepper header
        const stepper = document.createElement('div');
        stepper.className = 'drone-stepper';
        DRONE_STEPS.forEach((step, i) => {
            const el = document.createElement('div');
            el.className = 'drone-step-indicator';
            if (i < this._currentStep) el.classList.add('completed');
            if (i === this._currentStep) el.classList.add('active');
            el.innerHTML = `
                <div class="step-circle">${i < this._currentStep ? '✓' : (i + 1)}</div>
                <div class="step-label">${step.label}</div>
            `;
            el.onclick = () => { if (i <= this._currentStep) this._goToStep(i); };
            stepper.appendChild(el);
        });
        this._container.appendChild(stepper);

        // Step content
        const content = document.createElement('div');
        content.className = 'drone-step-content';
        content.id = 'droneStepContent';
        this._container.appendChild(content);

        this._renderStep(this._currentStep);
    }

    _renderStep(stepIndex) {
        const content = document.getElementById('droneStepContent');
        if (!content) return;

        const renderers = [
            () => this._renderProjectStep(content),
            () => this._renderIngestStep(content),
            () => this._renderReconStep(content),
            () => this._renderOptimizeStep(content),
            () => this._renderUnityStep(content),
            () => this._renderWebGLStep(content),
            () => this._renderDeployStep(content),
        ];

        if (renderers[stepIndex]) renderers[stepIndex]();
    }

    _goToStep(index) {
        this._currentStep = index;
        this._render();
    }

    _nextStep() {
        if (this._currentStep < DRONE_STEPS.length - 1) {
            this._currentStep++;
            this._render();
        }
    }

    // ── Step 0: Project ─────────────────────────────────────

    _renderProjectStep(el) {
        el.innerHTML = `
            <h3>📁 프로젝트 생성</h3>
            <div class="drone-form">
                <label>프로젝트 이름</label>
                <input type="text" id="droneProjectName" class="drone-input"
                       placeholder="예: Factory_Building_A" value="${this._project?.name || ''}">

                <label>소스 폴더</label>
                <div class="drone-input-row">
                    <input type="text" id="droneBaseDir" class="drone-input"
                           placeholder="소스 파일이 있는 폴더 경로"
                           value="${this._project?.base_dir || ''}">
                    <button class="btn btn-sm" onclick="droneWizard._browseFolder()">찾기</button>
                </div>

                <label>입력 유형</label>
                <div class="drone-input-option-row">
                    <button class="drone-option-btn ${this._selectedInputOption === 'vendor_pack' ? 'active' : ''}"
                            onclick="droneWizard._selectInputOption('vendor_pack')">
                        <strong>Vendor Pack</strong><br>
                        <small>GLB/FBX 메쉬 + 텍스처</small>
                    </button>
                    <button class="drone-option-btn ${this._selectedInputOption === 'raw_images' ? 'active' : ''}"
                            onclick="droneWizard._selectInputOption('raw_images')">
                        <strong>Raw Images</strong><br>
                        <small>드론 촬영 이미지</small>
                    </button>
                    <button class="drone-option-btn ${this._selectedInputOption === 'obj_folder' ? 'active' : ''}"
                            onclick="droneWizard._selectInputOption('obj_folder')">
                        <strong>OBJ 타일</strong><br>
                        <small>도시뷰 OBJ 타일셋</small>
                    </button>
                </div>

                ${this._selectedInputOption === 'obj_folder' ? `
                    <div class="drone-obj-scan-section">
                        <button class="btn btn-sm" id="objScanBtn" onclick="droneWizard._scanObjFolder()">
                            폴더 스캔
                        </button>
                        <div id="objScanResult"></div>
                    </div>
                ` : ''}

                <label>프리셋</label>
                <div class="drone-preset-row">
                    <button class="drone-preset-btn ${!this._project || this._project?.preset === 'preview' ? 'active' : ''}"
                            onclick="droneWizard._selectPreset('preview')">
                        <strong>Preview</strong><br>
                        <small>빠른 확인 (중간 품질)</small>
                    </button>
                    <button class="drone-preset-btn ${this._project?.preset === 'production' ? 'active' : ''}"
                            onclick="droneWizard._selectPreset('production')">
                        <strong>Production</strong><br>
                        <small>최상 품질 (느림)</small>
                    </button>
                </div>

                <div class="drone-actions">
                    <button class="btn btn-primary" onclick="droneWizard._createProject()">
                        프로젝트 생성 →
                    </button>
                </div>
            </div>
            ${this._project ? `
                <div class="drone-info-card">
                    <strong>현재 프로젝트:</strong> ${this._project.name}<br>
                    <strong>ID:</strong> ${this._project.id}<br>
                    <strong>옵션:</strong> ${this._project.input_option}<br>
                    <strong>단계:</strong> ${this._project.stage}
                </div>
            ` : ''}
        `;

        // Render cached scan results if available
        if (this._selectedInputOption === 'obj_folder' && this._objTiles) {
            this._renderObjScanResult(this._objTiles);
        }
    }

    _selectedPreset = 'preview';

    _selectPreset(preset) {
        this._selectedPreset = preset;
        document.querySelectorAll('.drone-preset-btn').forEach(b => b.classList.remove('active'));
        event.target.closest('.drone-preset-btn').classList.add('active');
    }

    _browseFolder() {
        // Use current file browser path
        const pathInput = document.getElementById('filePathInput');
        if (pathInput && pathInput.value) {
            document.getElementById('droneBaseDir').value = pathInput.value;
        }
    }

    _selectInputOption(option) {
        this._selectedInputOption = option;
        document.querySelectorAll('.drone-option-btn').forEach(b => b.classList.remove('active'));
        event.target.closest('.drone-option-btn').classList.add('active');
        // Re-render to show/hide OBJ scan section
        const content = document.getElementById('droneStepContent');
        if (content) this._renderProjectStep(content);
    }

    async _scanObjFolder() {
        const folderPath = document.getElementById('droneBaseDir')?.value?.trim();
        if (!folderPath) {
            this._showMsg('소스 폴더 경로를 입력하세요', 'error');
            return;
        }

        const btn = document.getElementById('objScanBtn');
        if (btn) { btn.disabled = true; btn.textContent = '스캔 중...'; }

        try {
            const resp = await fetch('/api/drone/obj-folder/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_path: folderPath }),
            });
            const data = await resp.json();
            this._objTiles = data;
            this._renderObjScanResult(data);
            if (btn) { btn.textContent = '재스캔'; btn.disabled = false; }
        } catch (e) {
            this._showMsg(`스캔 실패: ${e.message}`, 'error');
            if (btn) { btn.textContent = '재시도'; btn.disabled = false; }
        }
    }

    _renderObjScanResult(data) {
        const container = document.getElementById('objScanResult');
        if (!container || !data) return;

        const { tile_count, total_size_mb, tiles, warnings, grid } = data;

        let gridHtml = '';
        if (grid && grid.rows && grid.rows.length) {
            gridHtml = '<div class="tile-grid">';
            for (const row of grid.rows) {
                for (const col of grid.cols) {
                    const tile = tiles.find(t => t.row === row && t.col === col);
                    if (tile) {
                        const sizeClass = tile.size_mb > 150 ? 'large'
                            : tile.size_mb > 50 ? 'medium' : 'small';
                        gridHtml += `<div class="tile-cell ${sizeClass}" title="${tile.name}\n${tile.size_mb} MB">
                            <div>${row}-${col}</div>
                            <div>${tile.size_mb.toFixed(0)}M</div>
                        </div>`;
                    } else {
                        gridHtml += `<div class="tile-cell empty">-</div>`;
                    }
                }
            }
            gridHtml += '</div>';
        }

        container.innerHTML = `
            <div class="drone-info-card" style="margin-top: 8px;">
                <strong>스캔 결과:</strong> ${tile_count}개 타일, ${total_size_mb.toFixed(0)} MB<br>
                ${grid?.row_count ? `<strong>그리드:</strong> ${grid.row_count} rows × ${grid.col_count} cols` : ''}
            </div>
            ${gridHtml}
            ${warnings?.length ? `
                <div class="qa-warnings" style="margin-top: 8px;">
                    <strong>경고:</strong>
                    <ul>${warnings.map(w => `<li>${w}</li>`).join('')}</ul>
                </div>
            ` : ''}
        `;
    }

    async _createProject() {
        const name = document.getElementById('droneProjectName')?.value?.trim();
        const baseDir = document.getElementById('droneBaseDir')?.value?.trim();

        if (!name) {
            this._showMsg('프로젝트 이름을 입력하세요', 'error');
            return;
        }

        try {
            const resp = await fetch('/api/drone/project/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    input_option: this._selectedInputOption,
                    preset: this._selectedPreset,
                    base_dir: baseDir || '',
                }),
            });
            const data = await resp.json();
            if (data.project) {
                this._project = data.project;
                this._showMsg(`프로젝트 "${name}" 생성 완료`, 'success');
                this._nextStep();
            } else {
                this._showMsg(data.detail || '생성 실패', 'error');
            }
        } catch (e) {
            this._showMsg(`오류: ${e.message}`, 'error');
        }
    }

    // ── Step 1: Ingest QA ───────────────────────────────────

    _renderIngestStep(el) {
        if (!this._project) {
            el.innerHTML = '<p class="drone-warn">먼저 프로젝트를 생성하세요.</p>';
            return;
        }

        el.innerHTML = `
            <h3>🔍 Ingest QA — 소스 품질 분석</h3>
            <p>프로젝트 폴더를 스캔하여 입력 옵션(A/B)을 자동 판별하고 품질을 분석합니다.</p>
            <div class="drone-actions">
                <button class="btn btn-primary" id="ingestRunBtn" onclick="droneWizard._runIngestQA()">
                    분석 시작
                </button>
            </div>
            <div id="ingestResult"></div>
        `;
    }

    async _runIngestQA() {
        const btn = document.getElementById('ingestRunBtn');
        if (btn) { btn.disabled = true; btn.textContent = '분석 중...'; }

        try {
            const resp = await fetch('/api/drone/ingest/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: this._project.id }),
            });
            const data = await resp.json();
            this._qaReport = data.qa_report;

            // Refresh project status
            await this._refreshProject();

            this._renderQAResult(data.qa_report);

            if (btn) { btn.textContent = '재분석'; btn.disabled = false; }
        } catch (e) {
            this._showMsg(`분석 실패: ${e.message}`, 'error');
            if (btn) { btn.textContent = '재시도'; btn.disabled = false; }
        }
    }

    _renderQAResult(report) {
        const container = document.getElementById('ingestResult');
        if (!container || !report) return;

        const grade = report.score >= 80 ? 'A' : report.score >= 60 ? 'B' : report.score >= 40 ? 'C' : 'D';
        const gradeColor = { A: '#00b894', B: '#fdcb6e', C: '#e17055', D: '#d63031' }[grade];

        const optionLabels = {
            vendor_pack: 'A (Vendor Pack)',
            raw_images: 'B (Raw Images)',
            obj_folder: 'C (OBJ Tiles)',
        };

        // Tile grid for OBJ folder
        let tileGridHtml = '';
        if (report.input_option === 'obj_folder' && report.obj_tiles?.length) {
            const tiles = report.obj_tiles;
            const rows = [...new Set(tiles.map(t => t.row).filter(r => r > 0))].sort((a, b) => a - b);
            const cols = [...new Set(tiles.map(t => t.col).filter(c => c > 0))].sort((a, b) => a - b);
            if (rows.length && cols.length) {
                tileGridHtml = '<div class="tile-grid" style="margin: 8px 0;">';
                for (const row of rows) {
                    for (const col of cols) {
                        const tile = tiles.find(t => t.row === row && t.col === col);
                        if (tile) {
                            const sizeClass = tile.size_mb > 150 ? 'large'
                                : tile.size_mb > 50 ? 'medium' : 'small';
                            tileGridHtml += `<div class="tile-cell ${sizeClass}" title="${tile.name}\n${tile.size_mb} MB">
                                <div>${row}-${col}</div>
                                <div>${tile.size_mb.toFixed(0)}M</div>
                            </div>`;
                        }
                    }
                }
                tileGridHtml += '</div>';
            }
        }

        container.innerHTML = `
            <div class="qa-score-card">
                <div class="qa-score" style="color: ${gradeColor}">
                    <span class="qa-grade">${grade}</span>
                    <span class="qa-number">${report.score}/100</span>
                </div>
                <div class="qa-details">
                    <div><strong>입력 옵션:</strong> ${optionLabels[report.input_option] || report.input_option}</div>
                    ${report.input_option === 'obj_folder' && report.obj_tiles?.length
                        ? `<div><strong>OBJ 타일:</strong> ${report.obj_tiles.length}개</div>`
                        : ''}
                    ${report.image_count ? `<div><strong>이미지:</strong> ${report.image_count}장 (해상도: ${report.avg_resolution || '-'})</div>` : ''}
                    ${report.mesh_files?.length ? `<div><strong>메쉬:</strong> ${report.mesh_files.length}개</div>` : ''}
                    ${report.texture_files?.length ? `<div><strong>텍스처:</strong> ${report.texture_files.length}개</div>` : ''}
                    <div><strong>총 용량:</strong> ${report.total_size_mb || 0} MB</div>
                </div>
            </div>
            ${tileGridHtml}
            ${report.warnings?.length ? `
                <div class="qa-warnings">
                    <strong>경고:</strong>
                    <ul>${report.warnings.map(w => `<li>${w}</li>`).join('')}</ul>
                </div>
            ` : ''}
            ${report.recommendations?.length ? `
                <div class="qa-recs">
                    <strong>권장:</strong>
                    <ul>${report.recommendations.map(r => `<li>${r}</li>`).join('')}</ul>
                </div>
            ` : ''}
            <div class="drone-actions">
                <button class="btn btn-primary" onclick="droneWizard._nextStep()">
                    다음 단계 →
                </button>
            </div>
        `;
    }

    // ── Step 2: Reconstruction (Option B only) ──────────────

    _renderReconStep(el) {
        if (!this._project) {
            el.innerHTML = '<p class="drone-warn">먼저 프로젝트를 생성하세요.</p>';
            return;
        }

        const isOptionB = this._project.input_option === 'raw_images';
        const isObjFolder = this._project.input_option === 'obj_folder';

        if (isObjFolder) {
            el.innerHTML = `
                <h3>🏗️ 재구성 — 건너뜀</h3>
                <p>OBJ 타일셋은 이미 메쉬 데이터가 포함되어 있으므로 재구성이 불필요합니다.</p>
                <div class="drone-actions">
                    <button class="btn btn-primary" onclick="droneWizard._nextStep()">다음 단계 →</button>
                </div>
            `;
            return;
        }

        if (!isOptionB) {
            el.innerHTML = `
                <h3>🏗️ 재구성 — 건너뜀</h3>
                <p>Vendor Pack (Option A)이므로 재구성 단계를 건너뜁니다.</p>
                <div class="drone-actions">
                    <button class="btn btn-primary" onclick="droneWizard._nextStep()">다음 단계 →</button>
                </div>
            `;
            return;
        }

        el.innerHTML = `
            <h3>🏗️ 3D 재구성 (Photogrammetry)</h3>
            <p>드론 이미지로부터 3D 메쉬를 생성합니다.</p>

            <label>재구성 엔진</label>
            <select class="drone-input" id="reconEngine">
                <option value="colmap">COLMAP (오픈소스)</option>
                <option value="realitycapture" disabled>RealityCapture (상용 — 추후 지원)</option>
            </select>

            <div class="drone-actions">
                <button class="btn btn-primary" id="reconRunBtn" onclick="droneWizard._runRecon()">
                    재구성 시작
                </button>
            </div>
            <div id="reconResult"></div>
        `;
    }

    async _runRecon() {
        const btn = document.getElementById('reconRunBtn');
        if (btn) { btn.disabled = true; btn.textContent = '재구성 중...'; }

        try {
            const resp = await fetch('/api/drone/recon/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: this._project.id, stage: 'reconstruction' }),
            });
            const data = await resp.json();
            this._showMsg('재구성이 시작되었습니다. 완료 시 알림을 받습니다.', 'success');
            if (btn) { btn.textContent = '실행 중...'; }
        } catch (e) {
            this._showMsg(`재구성 실패: ${e.message}`, 'error');
            if (btn) { btn.textContent = '재시도'; btn.disabled = false; }
        }
    }

    // ── Step 3: Optimize ────────────────────────────────────

    _renderOptimizeStep(el) {
        if (!this._project) {
            el.innerHTML = '<p class="drone-warn">먼저 프로젝트를 생성하세요.</p>';
            return;
        }

        if (this._project.input_option === 'obj_folder') {
            el.innerHTML = `
                <h3>⚙️ 최적화 — 건너뜀</h3>
                <p>OBJ 타일은 직접 Unity에 임포트됩니다. Blender 최적화가 불필요합니다.</p>
                <div class="drone-info-card">
                    Unity 내장 메쉬 압축(Medium) + 텍스처 압축(HQ 4096)이 자동 적용됩니다.
                </div>
                <div class="drone-actions">
                    <button class="btn btn-primary" onclick="droneWizard._nextStep()">다음 단계 →</button>
                </div>
            `;
            return;
        }

        el.innerHTML = `
            <h3>⚙️ 메쉬 최적화</h3>
            <p>Blender CLI로 LOD 생성, 노이즈 제거, 텍스처 리사이즈를 수행합니다.</p>
            <div class="drone-info-card">
                프리셋: <strong>${this._project.preset}</strong><br>
                ${this._project.preset === 'preview'
                    ? 'LOD0: 100K / LOD1: 30K / LOD2: 10K / 텍스처: 2K'
                    : 'LOD0: 300K / LOD1: 80K / LOD2: 20K / 텍스처: 4K'}
            </div>
            <div class="drone-actions">
                <button class="btn btn-primary" id="optimizeRunBtn" onclick="droneWizard._runOptimize()">
                    최적화 시작
                </button>
            </div>
            <div id="optimizeResult"></div>
        `;
    }

    async _runOptimize() {
        const btn = document.getElementById('optimizeRunBtn');
        if (btn) { btn.disabled = true; btn.textContent = '최적화 중...'; }

        try {
            const resp = await fetch('/api/drone/optimize/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: this._project.id }),
            });
            const data = await resp.json();
            this._showMsg('최적화가 시작되었습니다.', 'success');
            if (btn) { btn.textContent = '실행 중...'; }
        } catch (e) {
            this._showMsg(`최적화 실패: ${e.message}`, 'error');
            if (btn) { btn.textContent = '재시도'; btn.disabled = false; }
        }
    }

    // ── Step 4: Unity Import ────────────────────────────────

    _renderUnityStep(el) {
        if (!this._project) {
            el.innerHTML = '<p class="drone-warn">먼저 프로젝트를 생성하세요.</p>';
            return;
        }

        const isObjFolder = this._project.input_option === 'obj_folder';
        const tileCount = this._qaReport?.obj_tiles?.length || this._objTiles?.tile_count || 0;

        if (isObjFolder) {
            el.innerHTML = `
                <h3>🎮 Unity Import — OBJ 타일 순차 임포트</h3>
                <p>${tileCount}개 타일을 Assets/CityTiles/ 에 순차적으로 임포트합니다.</p>
                <ul>
                    <li>CityTile AssetPostprocessor — 자동 임포트 세팅</li>
                    <li>OBJ + MTL + 텍스처 → Assets/CityTiles/{TileName}/</li>
                    <li>메쉬 압축 (Medium) + 텍스처 4096 HQ</li>
                    <li>MTL 기반 머티리얼 자동 생성</li>
                </ul>
                <div class="drone-actions">
                    <button class="btn btn-primary" id="unityImportBtn" onclick="droneWizard._runUnityImport()">
                        타일 Import 시작 (${tileCount}개)
                    </button>
                </div>
                <div id="tileProgressContainer"></div>
                <div id="unityResult"></div>
            `;
        } else {
            el.innerHTML = `
                <h3>🎮 Unity Import + 타일링</h3>
                <p>최적화된 메쉬를 Unity에 Import하고 LOD/Addressables/스트리밍을 자동 설정합니다.</p>
                <ul>
                    <li>AssetPostprocessor — Import 세팅 자동화</li>
                    <li>LODGroup 자동 생성 (100%/35%/10%)</li>
                    <li>BoxCollider 프록시 생성</li>
                    <li>구역별 타일링 + Addressables 그룹</li>
                    <li>스트리밍 로더 설치</li>
                </ul>
                <div class="drone-actions">
                    <button class="btn btn-primary" id="unityImportBtn" onclick="droneWizard._runUnityImport()">
                        Unity Import 실행
                    </button>
                </div>
                <div id="unityResult"></div>
            `;
        }
    }

    async _runUnityImport() {
        const btn = document.getElementById('unityImportBtn');
        if (btn) { btn.disabled = true; btn.textContent = 'Import 중...'; }

        try {
            const resp = await fetch('/api/drone/unity/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: this._project.id }),
            });
            const data = await resp.json();
            this._showMsg('Unity Import가 시작되었습니다.', 'success');
            if (btn) { btn.textContent = '실행 중...'; }
        } catch (e) {
            this._showMsg(`Unity Import 실패: ${e.message}`, 'error');
            if (btn) { btn.textContent = '재시도'; btn.disabled = false; }
        }
    }

    // ── Step 5: WebGL Build ─────────────────────────────────

    _renderWebGLStep(el) {
        if (!this._project) {
            el.innerHTML = '<p class="drone-warn">먼저 프로젝트를 생성하세요.</p>';
            return;
        }

        el.innerHTML = `
            <h3>🌐 WebGL Build</h3>
            <p>Unity 프로젝트를 WebGL로 빌드합니다.</p>
            <div class="drone-info-card">
                Compression: Brotli<br>
                Data Caching: On<br>
                Code Stripping: High<br>
                텍스처: KTX2/Basis 권장
            </div>
            <div class="drone-actions">
                <button class="btn btn-primary" id="webglBuildBtn" onclick="droneWizard._runWebGLBuild()">
                    WebGL Build 시작
                </button>
            </div>
            <div id="webglResult"></div>
        `;
    }

    async _runWebGLBuild() {
        const btn = document.getElementById('webglBuildBtn');
        if (btn) { btn.disabled = true; btn.textContent = '빌드 중...'; }

        try {
            const resp = await fetch('/api/drone/webgl/build', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: this._project.id }),
            });
            const data = await resp.json();
            this._showMsg('WebGL 빌드가 시작되었습니다.', 'success');
            if (btn) { btn.textContent = '빌드 중...'; }
        } catch (e) {
            this._showMsg(`WebGL 빌드 실패: ${e.message}`, 'error');
            if (btn) { btn.textContent = '재시도'; btn.disabled = false; }
        }
    }

    // ── Step 6: Deploy ──────────────────────────────────────

    _renderDeployStep(el) {
        if (!this._project) {
            el.innerHTML = '<p class="drone-warn">먼저 프로젝트를 생성하세요.</p>';
            return;
        }

        el.innerHTML = `
            <h3>🚀 배포 & 리포트</h3>
            <p>WebGL 빌드를 Nginx/CDN에 배포하고 성능 리포트를 생성합니다.</p>
            <div class="drone-actions">
                <button class="btn btn-primary" id="deployBtn" onclick="droneWizard._runDeploy()">
                    배포 실행
                </button>
                <button class="btn btn-sm" onclick="droneWizard._viewReports()">
                    리포트 보기
                </button>
            </div>
            <div id="deployResult"></div>
        `;
    }

    async _runDeploy() {
        const btn = document.getElementById('deployBtn');
        if (btn) { btn.disabled = true; btn.textContent = '배포 중...'; }

        try {
            const resp = await fetch('/api/drone/deploy', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: this._project.id }),
            });
            const data = await resp.json();
            this._showMsg('배포가 시작되었습니다.', 'success');
        } catch (e) {
            this._showMsg(`배포 실패: ${e.message}`, 'error');
            if (btn) { btn.textContent = '재시도'; btn.disabled = false; }
        }
    }

    async _viewReports() {
        if (!this._project) return;

        try {
            const resp = await fetch(`/api/drone/reports/${this._project.id}`);
            const data = await resp.json();
            const container = document.getElementById('deployResult');
            if (container) {
                container.innerHTML = `<pre class="code-block">${JSON.stringify(data.reports, null, 2)}</pre>`;
            }
        } catch (e) {
            this._showMsg(`리포트 조회 실패: ${e.message}`, 'error');
        }
    }

    // ── Full pipeline (one-click) ───────────────────────────

    async runFullPipeline() {
        if (!this._project) {
            this._showMsg('먼저 프로젝트를 생성하세요.', 'error');
            return;
        }

        try {
            const resp = await fetch('/api/drone/pipeline/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: this._project.id }),
            });
            const data = await resp.json();
            this._showMsg(`원클릭 파이프라인 시작: ${data.message}`, 'success');
        } catch (e) {
            this._showMsg(`파이프라인 실패: ${e.message}`, 'error');
        }
    }

    // ── Helpers ──────────────────────────────────────────────

    async _refreshProject() {
        if (!this._project?.id) return;
        try {
            const resp = await fetch(`/api/drone/project/${this._project.id}`);
            const data = await resp.json();
            if (data.project) this._project = data.project;
        } catch (e) {
            console.warn('[Drone2Twin] Failed to refresh project:', e);
        }
    }

    _showMsg(msg, type = 'info') {
        // Use existing Vibe3D chat message system
        if (typeof addChatMsg === 'function') {
            addChatMsg('assistant', `[Drone2Twin] ${msg}`);
        } else {
            console.log(`[Drone2Twin] ${type}: ${msg}`);
        }
    }

    // ── WebSocket event handler ─────────────────────────────

    handleWS(event, data) {
        if (!this._initialized) return;

        switch (event) {
            case 'drone_pipeline_progress':
                this._showMsg(`파이프라인 진행: ${data.stage} (${Math.round(data.progress * 100)}%)`);
                break;
            case 'drone_stage_complete':
                this._showMsg(`단계 완료: ${data.stage}`, 'success');
                this._refreshProject().then(() => this._render());
                break;
            case 'drone_pipeline_complete':
                this._showMsg(`파이프라인 완료! (${data.stages_completed} 단계)`, 'success');
                this._refreshProject().then(() => this._render());
                break;
            case 'drone_pipeline_failed':
                this._showMsg(`파이프라인 실패: ${data.stage} — ${data.error}`, 'error');
                this._refreshProject().then(() => this._render());
                break;
            case 'drone_tile_progress':
                this._updateTileProgress(data);
                break;
            case 'drone_tiles_complete':
                this._onTilesComplete(data);
                break;
        }
    }

    _updateTileProgress(data) {
        const container = document.getElementById('tileProgressContainer');
        if (!container) return;

        const { tile_index, total, tile_name, size_mb } = data;
        const pct = Math.round(((tile_index + 1) / total) * 100);

        container.innerHTML = `
            <div class="tile-progress-info">
                <strong>Tile ${tile_index + 1}/${total}:</strong> ${tile_name} (${(size_mb || 0).toFixed(1)} MB)
            </div>
            <div class="tile-progress">
                <div class="tile-progress-bar" style="width: ${pct}%"></div>
            </div>
            <div class="tile-progress-pct">${pct}%</div>
        `;
    }

    _onTilesComplete(data) {
        const container = document.getElementById('tileProgressContainer');
        if (container) {
            container.innerHTML = `
                <div class="drone-info-card" style="border-color: var(--success);">
                    <strong>타일 임포트 완료!</strong><br>
                    ${data.imported}/${data.total} 타일 임포트 성공
                    ${data.failed > 0 ? `<br><span style="color: var(--error);">${data.failed}개 실패</span>` : ''}
                </div>
            `;
        }

        const btn = document.getElementById('unityImportBtn');
        if (btn) { btn.textContent = '완료'; btn.disabled = false; }

        this._showMsg(data.message, data.failed > 0 ? 'warning' : 'success');
    }
}

// ── Singleton ───────────────────────────────────────────────
const droneWizard = new DroneWizard();
