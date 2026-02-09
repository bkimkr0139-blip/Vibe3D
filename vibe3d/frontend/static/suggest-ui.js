// Vibe3D Unity Accelerator — Autocomplete / Suggestion UI Component

(function () {
    'use strict';

    // ── Source icon map ──────────────────────────────────────────
    var SOURCE_ICONS = {
        history: '\uD83D\uDD51',       // &#128337;
        preset: '\u2733',              // &#9733; (star)
        scene_object: '\u25FC'         // &#9724; (black square)
    };

    // ── SuggestUI Class ─────────────────────────────────────────

    function SuggestUI() {
        this._inputEl = null;
        this._dropdownEl = null;
        this._items = [];
        this._selectedIdx = -1;
        this._debounceTimer = null;
        this._visible = false;
        this._bound = {};
    }

    // ── attach ──────────────────────────────────────────────────

    SuggestUI.prototype.attach = function (inputEl, dropdownEl) {
        this._inputEl = inputEl;
        this._dropdownEl = dropdownEl;

        this._bound.onInput = this._onInput.bind(this);
        this._bound.onKeyDown = this._onKeyDown.bind(this);
        this._bound.onBlur = this._onBlur.bind(this);

        this._inputEl.addEventListener('input', this._bound.onInput);
        this._inputEl.addEventListener('keydown', this._bound.onKeyDown);
        this._inputEl.addEventListener('blur', this._bound.onBlur);

        // Prevent dropdown mousedown from stealing focus
        this._bound.onDropdownMouseDown = function (e) {
            e.preventDefault();
        };
        this._dropdownEl.addEventListener('mousedown', this._bound.onDropdownMouseDown);
    };

    // ── destroy ─────────────────────────────────────────────────

    SuggestUI.prototype.destroy = function () {
        if (this._inputEl) {
            this._inputEl.removeEventListener('input', this._bound.onInput);
            this._inputEl.removeEventListener('keydown', this._bound.onKeyDown);
            this._inputEl.removeEventListener('blur', this._bound.onBlur);
        }
        if (this._dropdownEl) {
            this._dropdownEl.removeEventListener('mousedown', this._bound.onDropdownMouseDown);
        }
        this.hide();
        clearTimeout(this._debounceTimer);
        this._inputEl = null;
        this._dropdownEl = null;
        this._items = [];
        this._bound = {};
    };

    // ── setSuggestions ───────────────────────────────────────────

    SuggestUI.prototype.setSuggestions = function (suggestions) {
        this._items = (suggestions || []).slice(0, 5);
        this._selectedIdx = -1;
        this._render();
        if (this._items.length > 0) {
            this.show();
        } else {
            this.hide();
        }
    };

    // ── show / hide ─────────────────────────────────────────────

    SuggestUI.prototype.show = function () {
        if (!this._dropdownEl) return;
        this._dropdownEl.style.display = 'block';
        this._visible = true;
    };

    SuggestUI.prototype.hide = function () {
        if (!this._dropdownEl) return;
        this._dropdownEl.style.display = 'none';
        this._visible = false;
        this._selectedIdx = -1;
    };

    // ── Internal: input handler (debounced fetch) ───────────────

    SuggestUI.prototype._onInput = function () {
        var self = this;
        clearTimeout(this._debounceTimer);

        var prefix = (this._inputEl.value || '').trim();
        if (!prefix) {
            this.hide();
            return;
        }

        this._debounceTimer = setTimeout(function () {
            self._fetchSuggestions(prefix);
        }, 200);
    };

    // ── Internal: fetch from API ────────────────────────────────

    SuggestUI.prototype._fetchSuggestions = function (prefix) {
        var self = this;
        var url = window.location.origin + '/api/suggest?prefix=' + encodeURIComponent(prefix);

        fetch(url)
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data && data.suggestions) {
                    self.setSuggestions(data.suggestions);
                }
            })
            .catch(function () {
                self.hide();
            });
    };

    // ── Internal: keyboard navigation ───────────────────────────

    SuggestUI.prototype._onKeyDown = function (e) {
        if (!this._visible || this._items.length === 0) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this._selectedIdx = Math.min(this._selectedIdx + 1, this._items.length - 1);
            this._updateSelection();
            return;
        }

        if (e.key === 'ArrowUp') {
            e.preventDefault();
            this._selectedIdx = Math.max(this._selectedIdx - 1, 0);
            this._updateSelection();
            return;
        }

        if (e.key === 'Enter' && this._selectedIdx >= 0) {
            e.preventDefault();
            e.stopPropagation();
            this._applyItem(this._items[this._selectedIdx]);
            return;
        }

        if (e.key === 'Escape') {
            e.preventDefault();
            this.hide();
            return;
        }
    };

    // ── Internal: blur handler ──────────────────────────────────

    SuggestUI.prototype._onBlur = function () {
        var self = this;
        // Delay to allow click events on dropdown items to fire
        setTimeout(function () {
            self.hide();
        }, 150);
    };

    // ── Internal: apply selected item ───────────────────────────

    SuggestUI.prototype._applyItem = function (item) {
        if (!item || !this._inputEl) return;
        this._inputEl.value = item.command || item.label;
        this._inputEl.focus();
        this.hide();
    };

    // ── Internal: render dropdown ───────────────────────────────

    SuggestUI.prototype._render = function () {
        if (!this._dropdownEl) return;
        var self = this;
        this._dropdownEl.innerHTML = '';

        for (var i = 0; i < this._items.length; i++) {
            (function (idx) {
                var item = self._items[idx];
                var row = document.createElement('div');
                row.className = 'suggest-item' + (idx === self._selectedIdx ? ' selected' : '');

                var icon = document.createElement('span');
                icon.className = 'suggest-icon';
                icon.textContent = SOURCE_ICONS[item.source] || '\u25B6';

                var label = document.createElement('span');
                label.className = 'suggest-label';
                label.textContent = item.label;

                var badge = document.createElement('span');
                badge.className = 'suggest-source badge';
                badge.textContent = item.source || '';

                row.appendChild(icon);
                row.appendChild(label);
                row.appendChild(badge);

                row.addEventListener('click', function () {
                    self._applyItem(item);
                });

                self._dropdownEl.appendChild(row);
            })(i);
        }
    };

    // ── Internal: update selection highlight ────────────────────

    SuggestUI.prototype._updateSelection = function () {
        var rows = this._dropdownEl.querySelectorAll('.suggest-item');
        for (var i = 0; i < rows.length; i++) {
            if (i === this._selectedIdx) {
                rows[i].classList.add('selected');
            } else {
                rows[i].classList.remove('selected');
            }
        }
    };

    // ── Suggestion Chips ────────────────────────────────────────

    /**
     * Render suggestion chips into a container element.
     * @param {HTMLElement} containerEl - Container to render chips into
     * @param {Array} suggestions - Array of {label, command?, confidence?}
     * @param {Object} [options] - Options: autoSend (boolean)
     */
    SuggestUI.prototype.renderChips = function (containerEl, suggestions, options) {
        if (!containerEl) return;
        options = options || {};

        containerEl.innerHTML = '';
        var wrapper = document.createElement('div');
        wrapper.className = 'suggest-chips';

        for (var i = 0; i < suggestions.length; i++) {
            (function (item) {
                var confidence = typeof item.confidence === 'number' ? item.confidence : 0.5;
                var level = confidence > 0.8 ? 'high' : confidence > 0.5 ? 'medium' : 'low';

                var chip = document.createElement('span');
                chip.className = 'suggest-chip ' + level;
                chip.textContent = item.label;

                chip.addEventListener('click', function () {
                    var input = document.getElementById('commandInput');
                    if (input) {
                        input.value = item.command || item.label;
                        input.focus();
                    }
                    if (options.autoSend && typeof window.sendCommand === 'function') {
                        window.sendCommand();
                    }
                });

                wrapper.appendChild(chip);
            })(suggestions[i]);
        }

        containerEl.appendChild(wrapper);
    };

    // ── Export ───────────────────────────────────────────────────

    window.SuggestUI = SuggestUI;
})();
