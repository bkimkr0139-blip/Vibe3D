// Vibe3D Unity Accelerator — Source File Quality Analysis (source-picker.js)

(function () {
    'use strict';

    const API = window.location.origin;

    // ── SourcePicker Class ──────────────────────────────────────

    class SourcePicker {

        // ── API Calls ───────────────────────────────────────────

        /**
         * Analyze a source file for quality and compatibility.
         * POST /api/source/analyze
         * @param {string} filePath - Absolute path to the file
         * @returns {Promise<Object>} Analysis result
         */
        async analyzeFile(filePath) {
            const resp = await fetch(`${API}/api/source/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_path: filePath }),
            });
            if (!resp.ok) {
                throw new Error(`분석 실패: ${resp.status} ${resp.statusText}`);
            }
            return resp.json();
        }

        /**
         * Convert a source file into an actionable import plan.
         * POST /api/source/to-plan
         * @param {string} filePath - Absolute path to the file
         * @returns {Promise<Object>} Generated plan
         */
        async convertToPlan(filePath) {
            const resp = await fetch(`${API}/api/source/to-plan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_path: filePath }),
            });
            if (!resp.ok) {
                throw new Error(`플랜 생성 실패: ${resp.status} ${resp.statusText}`);
            }
            return resp.json();
        }

        // ── Quality Badge ───────────────────────────────────────

        /**
         * Render a small colored grade badge into the given container.
         * @param {HTMLElement} containerEl - Element to append badge into
         * @param {number} score - Quality score 0-100
         * @returns {HTMLSpanElement} The created badge element
         */
        renderQualityBadge(containerEl, score) {
            const grade = this._scoreToGrade(score);

            // Remove any existing badge in this container
            const existing = containerEl.querySelector('.quality-badge');
            if (existing) existing.remove();

            const badge = document.createElement('span');
            badge.className = `quality-badge grade-${grade.letter.toLowerCase()}`;
            badge.textContent = `${grade.letter} ${score}`;
            badge.title = `품질 점수: ${score}/100 (등급 ${grade.letter})`;

            containerEl.appendChild(badge);
            this._ensureBadgeStyles();
            return badge;
        }

        // ── Analysis Panel ──────────────────────────────────────

        /**
         * Render a full analysis detail panel into the given container.
         * @param {HTMLElement} containerEl - Element to render panel into
         * @param {Object} analysis - Analysis result from analyzeFile()
         *   Expected shape:
         *   {
         *     score: number,
         *     type: string,
         *     issues: Array<{ message: string, severity: 'warning'|'error'|'info' }>,
         *     recommendations: Array<string>,
         *     file_path: string
         *   }
         */
        renderAnalysisPanel(containerEl, analysis) {
            // Remove any existing panel
            const existing = containerEl.querySelector('.source-analysis');
            if (existing) existing.remove();

            const panel = document.createElement('div');
            panel.className = 'source-analysis';

            // Header: score + type
            const header = document.createElement('div');
            header.className = 'analysis-header';

            const scoreEl = document.createElement('span');
            scoreEl.className = 'analysis-score';
            const grade = this._scoreToGrade(analysis.score || 0);
            scoreEl.className = `analysis-score grade-${grade.letter.toLowerCase()}`;
            scoreEl.textContent = analysis.score != null ? analysis.score : '--';

            const typeEl = document.createElement('span');
            typeEl.className = 'analysis-type';
            typeEl.textContent = analysis.type || 'Unknown';

            header.appendChild(scoreEl);
            header.appendChild(typeEl);
            panel.appendChild(header);

            // Issues list
            const issues = analysis.issues || [];
            if (issues.length > 0) {
                const issuesDiv = document.createElement('div');
                issuesDiv.className = 'analysis-issues';
                for (const issue of issues) {
                    const item = document.createElement('div');
                    const severity = issue.severity || 'warning';
                    item.className = `issue-item ${severity}`;
                    item.textContent = issue.message || String(issue);
                    issuesDiv.appendChild(item);
                }
                panel.appendChild(issuesDiv);
            }

            // Recommendations
            const recs = analysis.recommendations || [];
            if (recs.length > 0) {
                const recsDiv = document.createElement('div');
                recsDiv.className = 'analysis-recs';
                for (const rec of recs) {
                    const item = document.createElement('div');
                    item.className = 'rec-item';
                    item.textContent = typeof rec === 'string' ? rec : rec.message || String(rec);
                    recsDiv.appendChild(item);
                }
                panel.appendChild(recsDiv);
            }

            // Generate Plan button
            const filePath = analysis.file_path || '';
            if (filePath) {
                const btn = document.createElement('button');
                btn.className = 'btn btn-sm btn-primary';
                btn.textContent = '플랜 생성';
                btn.addEventListener('click', () => this._handleGeneratePlan(btn, filePath));
                panel.appendChild(btn);
            }

            containerEl.appendChild(panel);
            this._ensurePanelStyles();
            return panel;
        }

        // ── Integration Helper ──────────────────────────────────

        /**
         * Enhance an existing file item element with an analyze button
         * and quality badge placeholder. Called from app.js when rendering
         * file list items.
         *
         * @param {HTMLElement} fileItemEl - The .file-item element
         * @param {string} filePath - Absolute path to the file
         */
        enhanceFileItem(fileItemEl, filePath) {
            // Avoid double-enhancement
            if (fileItemEl.dataset.sourcePickerEnhanced) return;
            fileItemEl.dataset.sourcePickerEnhanced = 'true';

            // Create analyze button
            const analyzeBtn = document.createElement('button');
            analyzeBtn.className = 'source-analyze-btn';
            analyzeBtn.textContent = '분석';
            analyzeBtn.title = '소스 파일 품질 분석';
            analyzeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._handleAnalyze(fileItemEl, filePath, analyzeBtn);
            });

            // Insert before the .file-meta span if it exists, otherwise append
            const meta = fileItemEl.querySelector('.file-meta');
            if (meta) {
                fileItemEl.insertBefore(analyzeBtn, meta);
            } else {
                fileItemEl.appendChild(analyzeBtn);
            }

            this._ensureIntegrationStyles();
        }

        // ── Private Helpers ─────────────────────────────────────

        /**
         * Map a numeric score (0-100) to a grade object.
         */
        _scoreToGrade(score) {
            if (score >= 90) return { letter: 'A', css: 'grade-a' };
            if (score >= 60) return { letter: 'B', css: 'grade-b' };
            if (score >= 30) return { letter: 'C', css: 'grade-c' };
            return { letter: 'D', css: 'grade-d' };
        }

        /**
         * Handle the analyze button click on a file item.
         */
        async _handleAnalyze(fileItemEl, filePath, btn) {
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '...';

            try {
                const analysis = await this.analyzeFile(filePath);

                // Add quality badge to the file item
                const score = analysis.score != null ? analysis.score : 0;
                this.renderQualityBadge(fileItemEl, score);

                // Render the full analysis panel below the file item
                // Create or reuse a sibling panel container
                let panelContainer = fileItemEl.nextElementSibling;
                if (!panelContainer || !panelContainer.classList.contains('source-analysis-container')) {
                    panelContainer = document.createElement('div');
                    panelContainer.className = 'source-analysis-container';
                    fileItemEl.parentNode.insertBefore(panelContainer, fileItemEl.nextSibling);
                }

                // Ensure the analysis carries the file path for the plan button
                analysis.file_path = analysis.file_path || filePath;
                this.renderAnalysisPanel(panelContainer, analysis);

                btn.textContent = '재분석';
            } catch (err) {
                btn.textContent = '오류';
                btn.title = err.message;
                console.error('[SourcePicker] 분석 실패:', err);
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.title = '소스 파일 품질 분석';
                }, 3000);
            } finally {
                btn.disabled = false;
            }
        }

        /**
         * Handle the Generate Plan button click inside an analysis panel.
         */
        async _handleGeneratePlan(btn, filePath) {
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '생성 중...';

            try {
                const result = await this.convertToPlan(filePath);

                // If the global showPlan function exists (from app.js), use it
                if (typeof window.showPlan === 'function' && result.plan) {
                    window.showPlan(result.plan, result.method || 'source-analysis');
                }

                // If the global addJob function exists, log completion
                if (typeof window.addJob === 'function') {
                    window.addJob({
                        command: `소스 플랜: ${filePath.split(/[\\/]/).pop()}`,
                        status: 'completed',
                        detail: `${result.plan?.actions?.length || 0}개 작업 생성됨`,
                    });
                }

                btn.textContent = '플랜 생성됨';
                setTimeout(() => { btn.textContent = originalText; }, 2000);
            } catch (err) {
                btn.textContent = '실패';
                btn.title = err.message;
                console.error('[SourcePicker] 플랜 생성 실패:', err);

                if (typeof window.addJob === 'function') {
                    window.addJob({
                        command: '소스 플랜',
                        status: 'failed',
                        detail: err.message,
                    });
                }

                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.title = '';
                }, 3000);
            } finally {
                btn.disabled = false;
            }
        }

        // ── Dynamic Style Injection ─────────────────────────────
        // Inject minimal styles once per category so this component is
        // self-contained. Styles respect the existing CSS custom properties
        // from style.css when available.

        _ensureBadgeStyles() {
            if (document.getElementById('sp-badge-styles')) return;
            const style = document.createElement('style');
            style.id = 'sp-badge-styles';
            style.textContent = `
                .quality-badge {
                    display: inline-block;
                    font-size: 10px;
                    font-weight: 700;
                    padding: 1px 6px;
                    border-radius: 3px;
                    margin-left: 6px;
                    line-height: 16px;
                    vertical-align: middle;
                    white-space: nowrap;
                    letter-spacing: 0.3px;
                }
                .quality-badge.grade-a {
                    background: #00b894;
                    color: #fff;
                }
                .quality-badge.grade-b {
                    background: #fdcb6e;
                    color: #2d3436;
                }
                .quality-badge.grade-c {
                    background: #e17055;
                    color: #fff;
                }
                .quality-badge.grade-d {
                    background: #d63031;
                    color: #fff;
                }
            `;
            document.head.appendChild(style);
        }

        _ensurePanelStyles() {
            if (document.getElementById('sp-panel-styles')) return;
            const style = document.createElement('style');
            style.id = 'sp-panel-styles';
            style.textContent = `
                .source-analysis {
                    background: var(--surface-2, #2a2a2a);
                    border: 1px solid var(--border, #3a3a3a);
                    border-radius: 6px;
                    padding: 10px 12px;
                    margin-top: 6px;
                    font-size: 12px;
                }
                .source-analysis .analysis-header {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 8px;
                }
                .source-analysis .analysis-score {
                    font-size: 20px;
                    font-weight: 800;
                    line-height: 1;
                    min-width: 36px;
                    text-align: center;
                }
                .source-analysis .analysis-score.grade-a { color: #00b894; }
                .source-analysis .analysis-score.grade-b { color: #fdcb6e; }
                .source-analysis .analysis-score.grade-c { color: #e17055; }
                .source-analysis .analysis-score.grade-d { color: #d63031; }
                .source-analysis .analysis-type {
                    color: var(--text-2, #999);
                    font-size: 11px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                .source-analysis .analysis-issues {
                    margin-bottom: 6px;
                }
                .source-analysis .issue-item {
                    padding: 3px 8px;
                    border-radius: 3px;
                    margin-bottom: 3px;
                    font-size: 11px;
                    line-height: 1.4;
                }
                .source-analysis .issue-item.warning {
                    background: rgba(253, 203, 110, 0.15);
                    color: #fdcb6e;
                    border-left: 3px solid #fdcb6e;
                }
                .source-analysis .issue-item.error {
                    background: rgba(214, 48, 49, 0.15);
                    color: #ff7675;
                    border-left: 3px solid #d63031;
                }
                .source-analysis .issue-item.info {
                    background: rgba(116, 185, 255, 0.12);
                    color: #74b9ff;
                    border-left: 3px solid #74b9ff;
                }
                .source-analysis .analysis-recs {
                    margin-bottom: 8px;
                }
                .source-analysis .rec-item {
                    padding: 3px 8px;
                    font-size: 11px;
                    color: var(--text-2, #aaa);
                    line-height: 1.4;
                }
                .source-analysis .rec-item::before {
                    content: '\\2192 ';
                    color: var(--accent, #6c5ce7);
                }
                .source-analysis .btn {
                    margin-top: 4px;
                }
            `;
            document.head.appendChild(style);
        }

        _ensureIntegrationStyles() {
            if (document.getElementById('sp-integration-styles')) return;
            const style = document.createElement('style');
            style.id = 'sp-integration-styles';
            style.textContent = `
                .source-analyze-btn {
                    background: transparent;
                    border: 1px solid var(--border, #3a3a3a);
                    color: var(--text-2, #aaa);
                    font-size: 10px;
                    padding: 1px 6px;
                    border-radius: 3px;
                    cursor: pointer;
                    margin-left: auto;
                    margin-right: 4px;
                    white-space: nowrap;
                    transition: background 0.15s, color 0.15s;
                }
                .source-analyze-btn:hover {
                    background: var(--accent, #6c5ce7);
                    color: #fff;
                    border-color: var(--accent, #6c5ce7);
                }
                .source-analyze-btn:disabled {
                    opacity: 0.5;
                    cursor: default;
                }
                .source-analysis-container {
                    padding: 0 4px 4px;
                }
            `;
            document.head.appendChild(style);
        }
    }

    // ── Export ───────────────────────────────────────────────────

    window.SourcePicker = new SourcePicker();

})();
