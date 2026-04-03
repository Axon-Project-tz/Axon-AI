// settings.js — Settings panel, model slot switching, connection status, feature toggles

(function () {
    // ── Cached DOM ────────────────────────────────────
    var settingsOverlay = document.getElementById('settings-overlay');
    var btnSettings = document.getElementById('btn-settings');
    var btnCloseSettings = document.getElementById('btn-close-settings');
    var sidebarDot = document.querySelector('.sidebar-active-model .model-dot');
    var sidebarName = document.querySelector('.sidebar-model-name');
    var connDot = document.querySelector('.connection-dot');
    var connText = document.querySelector('.connection-text');

    // Dropdown elements
    var modelDropdown = document.getElementById('model-dropdown');
    var dropdownBtn = document.getElementById('model-dropdown-btn');
    var dropdownDot = document.getElementById('dropdown-dot');
    var dropdownName = document.getElementById('dropdown-name');
    var dropdownItems = document.querySelectorAll('.model-dropdown-item');

    // Plus menu elements
    var btnPlus = document.getElementById('btn-plus');
    var plusMenu = document.getElementById('plus-menu');
    var plusUpload = document.getElementById('plus-upload');
    var plusImage = document.getElementById('plus-image');
    var plusDeepSearch = document.getElementById('plus-deepsearch');
    var plusAgent = document.getElementById('plus-agent');
    var plusAgentBadge = document.getElementById('plus-agent-badge');
    var plusRoblox = document.getElementById('plus-roblox');
    var plusRobloxBadge = document.getElementById('plus-roblox-badge');

    // ── Global feature state ──────────────────────────
    Axon.features = {
        memory: true,
        agent: true,
        deepthink: true,
        rag: true,
        voice: true,
        auto_routing: true
    };
    // Roblox mode state
    Axon.robloxMode = false;
    Axon.robloxProjectRoot = '';
    // Slot data cache (from settings API)
    Axon.slotData = null;

    // Deep search next message flag
    Axon.deepSearchNext = false;

    // ── Settings panel open / close ───────────────────
    if (btnSettings) {
        btnSettings.addEventListener('click', function () {
            loadSettings();
            settingsOverlay.style.display = 'flex';
        });
    }
    if (btnCloseSettings) {
        btnCloseSettings.addEventListener('click', function () {
            settingsOverlay.style.display = 'none';
        });
    }
    if (settingsOverlay) {
        settingsOverlay.addEventListener('click', function (e) {
            if (e.target === settingsOverlay) {
                settingsOverlay.style.display = 'none';
            }
        });
    }

    // ── Model slot switching ──────────────────────────
    function setActiveSlot(slotId) {
        Axon.activeSlotId = slotId;

        // Update dropdown items
        dropdownItems.forEach(function (item) {
            var id = parseInt(item.dataset.slotId, 10);
            item.classList.toggle('active', id === slotId);
        });

        var slot = null;
        for (var i = 0; i < MODEL_SLOTS.length; i++) {
            if (MODEL_SLOTS[i].id === slotId) { slot = MODEL_SLOTS[i]; break; }
        }
        if (slot) {
            Axon.activeAccent = slot.accent;
            // Update dropdown button
            if (dropdownDot) dropdownDot.style.background = slot.accent;
            if (dropdownName) dropdownName.textContent = slot.name;
            // Update sidebar
            if (sidebarDot) sidebarDot.style.background = slot.accent;
            if (sidebarName) sidebarName.textContent = slot.name;
            // Update input bar accent
            var inputBarInner = document.querySelector('.input-bar-inner');
            if (inputBarInner) inputBarInner.style.setProperty('--slot-accent', slot.accent);
            var sendBtn = document.getElementById('btn-send');
            if (sendBtn) sendBtn.style.setProperty('--slot-accent', slot.accent);
        }

        // Image upload only on Vision slot
        if (plusImage) plusImage.disabled = (slotId !== 2);
    }

    // Dropdown item click handlers
    dropdownItems.forEach(function (item) {
        item.addEventListener('click', function () {
            setActiveSlot(parseInt(item.dataset.slotId, 10));
            closeDropdown();
        });
    });

    setActiveSlot(1);

    // ── Model Dropdown open / close ───────────────────
    function openDropdown() {
        if (modelDropdown) modelDropdown.classList.add('open');
    }
    function closeDropdown() {
        if (modelDropdown) modelDropdown.classList.remove('open');
    }
    function toggleDropdown() {
        if (modelDropdown) modelDropdown.classList.toggle('open');
    }

    if (dropdownBtn) {
        dropdownBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            closePlusMenu();
            toggleDropdown();
        });
    }

    // ── Plus Menu open / close ────────────────────────
    function openPlusMenu() {
        if (plusMenu) plusMenu.classList.add('open');
    }
    function closePlusMenu() {
        if (plusMenu) plusMenu.classList.remove('open');
    }
    function togglePlusMenu() {
        if (plusMenu) plusMenu.classList.toggle('open');
    }

    if (btnPlus) {
        btnPlus.addEventListener('click', function (e) {
            e.stopPropagation();
            closeDropdown();
            togglePlusMenu();
        });
    }

    // Close menus on outside click
    document.addEventListener('click', function (e) {
        if (modelDropdown && !modelDropdown.contains(e.target)) {
            closeDropdown();
        }
        if (plusMenu && !btnPlus.contains(e.target) && !plusMenu.contains(e.target)) {
            closePlusMenu();
        }
    });

    // ── Plus Menu item handlers ───────────────────────
    if (plusUpload) {
        plusUpload.addEventListener('click', function () {
            closePlusMenu();
            // Trigger file upload (upload.js listens for this)
            if (Axon.triggerFileUpload) Axon.triggerFileUpload();
        });
    }

    if (plusImage) {
        plusImage.addEventListener('click', function () {
            if (plusImage.disabled) return;
            closePlusMenu();
            if (Axon.triggerFileUpload) Axon.triggerFileUpload();
        });
    }

    if (plusDeepSearch) {
        plusDeepSearch.addEventListener('click', function () {
            Axon.deepSearchNext = !Axon.deepSearchNext;
            plusDeepSearch.classList.toggle('active', Axon.deepSearchNext);
            if (Axon.deepSearchNext) {
                plusDeepSearch.querySelector('span').textContent = 'Deep search ✓';
            } else {
                plusDeepSearch.querySelector('span').textContent = 'Deep search';
            }
            closePlusMenu();
        });
    }

    if (plusAgent) {
        plusAgent.addEventListener('click', function () {
            var newState = !Axon.features.agent;
            setFeature('agent', newState);
            closePlusMenu();
        });
    }

    if (plusRoblox) {
        plusRoblox.addEventListener('click', function () {
            Axon.robloxMode = !Axon.robloxMode;
            plusRoblox.classList.toggle('active', Axon.robloxMode);
            if (plusRobloxBadge) {
                plusRobloxBadge.textContent = Axon.robloxMode ? 'ON' : 'OFF';
                plusRobloxBadge.classList.toggle('on', Axon.robloxMode);
                plusRobloxBadge.classList.toggle('off', !Axon.robloxMode);
            }
            // Switch to Slot 7 automatically when enabling Roblox mode
            if (Axon.robloxMode) setActiveSlot(7);
            closePlusMenu();
        });
    }

    // ── Feature Toggle Helpers ────────────────────────
    function saveSetting(key, value) {
        fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: key, value: String(value) }),
        });
    }

    function setFeature(name, enabled) {
        Axon.features[name] = enabled;
        saveSetting('enable_' + name, enabled ? 'true' : 'false');
        syncSettingsToggle(name, enabled);
        syncPlusMenu(name, enabled);
        applyFeatureEffects(name, enabled);
    }

    // ── Sync settings toggle state ────────────────────
    function syncSettingsToggle(name, enabled) {
        var toggle = document.querySelector('.toggle[data-key="' + name + '"]');
        if (!toggle) return;
        toggle.classList.toggle('on', enabled);
    }

    // ── Sync plus menu badge ──────────────────────────
    function syncPlusMenu(name, enabled) {
        if (name === 'agent' && plusAgentBadge) {
            plusAgentBadge.textContent = enabled ? 'ON' : 'OFF';
            plusAgentBadge.classList.toggle('on', enabled);
            plusAgentBadge.classList.toggle('off', !enabled);
        }
    }

    // ── Apply feature side-effects in UI ──────────────
    function applyFeatureEffects(name, enabled) {
        if (name === 'voice') {
            var btnVoice = document.getElementById('btn-voice');
            if (btnVoice) {
                btnVoice.disabled = !enabled;
                btnVoice.title = enabled ? 'Voice input' : 'Voice disabled';
            }
            var voiceSection = document.getElementById('settings-voice-section');
            if (voiceSection) voiceSection.classList.toggle('disabled-section', !enabled);
        }
        if (name === 'memory') {
            var memSection = document.getElementById('settings-memory-section');
            if (memSection) memSection.classList.toggle('disabled-section', !enabled);
        }
        if (name === 'rag') {
            var ragSection = document.getElementById('settings-rag-section');
            if (ragSection) ragSection.classList.toggle('disabled-section', !enabled);
        }
        if (name === 'agent') {
            syncPlusMenu('agent', enabled);
        }
    }

    // ── Settings toggle click handlers ────────────────
    document.querySelectorAll('.toggle[data-key]').forEach(function (toggle) {
        toggle.addEventListener('click', function () {
            var name = toggle.dataset.key;
            var newState = !Axon.features[name];
            setFeature(name, newState);
        });
    });

    // ── Load settings from API ────────────────────────
    function loadSettings() {
        fetch('/api/settings')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                // Apply toggles
                var toggles = data.toggles || {};
                for (var key in toggles) {
                    if (Axon.features.hasOwnProperty(key)) {
                        Axon.features[key] = toggles[key];
                        syncSettingsToggle(key, toggles[key]);
                        syncPlusMenu(key, toggles[key]);
                        applyFeatureEffects(key, toggles[key]);
                    }
                }

                // Apply LM Studio URL
                var urlInput = document.getElementById('settings-lm-url');
                if (urlInput && data.lm_studio_url) {
                    urlInput.value = data.lm_studio_url;
                }

                // Apply Roblox project root
                var robloxPathInput = document.getElementById('roblox-project-path');
                if (robloxPathInput && data.roblox_project_root) {
                    robloxPathInput.value = data.roblox_project_root;
                    Axon.robloxProjectRoot = data.roblox_project_root;
                }

                // Cache and render slots
                Axon.slotData = data.slots || [];
                renderSlotEditors(Axon.slotData);

                // Load memories
                loadMemories();

                // Load RAG folders
                loadRagFolders();
            });
    }

    // ── Initial load on page start ────────────────────
    fetch('/api/settings')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var toggles = data.toggles || {};
            for (var key in toggles) {
                if (Axon.features.hasOwnProperty(key)) {
                    Axon.features[key] = toggles[key];
                    syncSettingsToggle(key, toggles[key]);
                    syncPlusMenu(key, toggles[key]);
                    applyFeatureEffects(key, toggles[key]);
                }
            }
            // Load roblox project root into memory for chat routing
            if (data.roblox_project_root) {
                Axon.robloxProjectRoot = data.roblox_project_root;
            }
        })
        .catch(function () { /* defaults are fine */ });

    // ── Test Connection button ────────────────────────
    var btnTestConn = document.getElementById('btn-test-connection');
    var connIndicator = document.getElementById('settings-conn-indicator');

    if (btnTestConn) {
        btnTestConn.addEventListener('click', function () {
            var urlInput = document.getElementById('settings-lm-url');
            var url = urlInput ? urlInput.value.trim() : '';
            if (!url) return;

            btnTestConn.textContent = '...';
            connIndicator.className = 'settings-conn-indicator';

            fetch('/api/connection/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url }),
            })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    btnTestConn.textContent = 'Test';
                    if (d.connected) {
                        connIndicator.className = 'settings-conn-indicator success';
                        // Save the new URL
                        saveSetting('lm_studio_url', url);
                    } else {
                        connIndicator.className = 'settings-conn-indicator fail';
                    }
                    // Clear indicator after 3s
                    setTimeout(function () {
                        connIndicator.className = 'settings-conn-indicator';
                    }, 3000);
                })
                .catch(function () {
                    btnTestConn.textContent = 'Test';
                    connIndicator.className = 'settings-conn-indicator fail';
                    setTimeout(function () {
                        connIndicator.className = 'settings-conn-indicator';
                    }, 3000);
                });
        });
    }

    // ── LM Studio URL — save on blur if changed ──────
    var urlInput = document.getElementById('settings-lm-url');
    if (urlInput) {
        var _lastUrl = urlInput.value;
        urlInput.addEventListener('blur', function () {
            var newUrl = urlInput.value.trim();
            if (newUrl && newUrl !== _lastUrl) {
                // Test first, only save if connected
                fetch('/api/connection/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: newUrl }),
                })
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d.connected) {
                            saveSetting('lm_studio_url', newUrl);
                            _lastUrl = newUrl;
                        } else {
                            // Revert
                            urlInput.value = _lastUrl;
                        }
                    })
                    .catch(function () {
                        urlInput.value = _lastUrl;
                    });
            }
        });
    }

    // ── Roblox project path — save on button click ────
    var btnRobloxSave = document.getElementById('btn-roblox-path-save');
    if (btnRobloxSave) {
        btnRobloxSave.addEventListener('click', function () {
            var pathInput = document.getElementById('roblox-project-path');
            var path = pathInput ? pathInput.value.trim() : '';
            saveSetting('roblox_project_root', path);
            Axon.robloxProjectRoot = path;
            btnRobloxSave.textContent = 'Saved!';
            setTimeout(function () { btnRobloxSave.textContent = 'Save'; }, 1500);
        });
    }

    // ── Render Model Slot Editors ─────────────────────
    function renderSlotEditors(slots) {
        var container = document.getElementById('settings-slots-list');
        if (!container) return;
        container.innerHTML = '';

        slots.forEach(function (slot) {
            var div = document.createElement('div');
            div.className = 'settings-slot-edit';
            div.innerHTML =
                '<div class="settings-slot-edit-header">' +
                    '<div class="settings-slot-edit-left">' +
                        '<span class="model-dot" style="background: ' + slot.accent + ';"></span>' +
                        '<span class="settings-slot-edit-name">' + slot.name + '</span>' +
                    '</div>' +
                    '<div class="settings-slot-edit-actions">' +
                        '<button class="settings-btn settings-btn-save slot-save-btn" data-slot-id="' + slot.id + '">Save</button>' +
                        '<button class="settings-btn slot-reset-btn" data-slot-id="' + slot.id + '">Reset</button>' +
                    '</div>' +
                '</div>' +
                '<div class="settings-slot-field-label">Model ID</div>' +
                '<input class="settings-slot-input slot-model-input" data-slot-id="' + slot.id + '" value="' + escapeAttr(slot.model_id) + '">' +
                '<div class="settings-slot-field-label">System Prompt</div>' +
                '<textarea class="settings-slot-textarea slot-prompt-input" data-slot-id="' + slot.id + '">' + escapeHtml(slot.system_prompt) + '</textarea>';
            container.appendChild(div);
        });

        // Save buttons
        container.querySelectorAll('.slot-save-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var sid = parseInt(btn.dataset.slotId, 10);
                var modelInput = container.querySelector('.slot-model-input[data-slot-id="' + sid + '"]');
                var promptInput = container.querySelector('.slot-prompt-input[data-slot-id="' + sid + '"]');
                if (modelInput) saveSetting('slot_' + sid + '_model_id', modelInput.value.trim());
                if (promptInput) saveSetting('slot_' + sid + '_system_prompt', promptInput.value);
                btn.textContent = 'Saved!';
                setTimeout(function () { btn.textContent = 'Save'; }, 1500);
            });
        });

        // Reset buttons
        container.querySelectorAll('.slot-reset-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var sid = parseInt(btn.dataset.slotId, 10);
                fetch('/api/settings/reset-slot', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ slot_id: sid }),
                })
                    .then(function () {
                        // Find matching default
                        var def = null;
                        for (var i = 0; i < (Axon.slotData || []).length; i++) {
                            if (Axon.slotData[i].id === sid) { def = Axon.slotData[i]; break; }
                        }
                        var modelInput = container.querySelector('.slot-model-input[data-slot-id="' + sid + '"]');
                        var promptInput = container.querySelector('.slot-prompt-input[data-slot-id="' + sid + '"]');
                        if (def && modelInput) modelInput.value = def.default_model_id;
                        if (def && promptInput) promptInput.value = def.default_system_prompt;
                        btn.textContent = 'Reset!';
                        setTimeout(function () { btn.textContent = 'Reset'; }, 1500);
                    });
            });
        });
    }

    // ── Memory list ───────────────────────────────────
    function loadMemories() {
        var container = document.getElementById('settings-memory-list');
        if (!container) return;

        fetch('/api/memory')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var memories = d.memories || [];
                if (memories.length === 0) {
                    container.innerHTML = '<p class="settings-empty">No memories stored yet.</p>';
                    return;
                }
                container.innerHTML = '';
                memories.forEach(function (mem) {
                    var item = document.createElement('div');
                    item.className = 'settings-memory-item';
                    item.innerHTML =
                        '<span class="settings-memory-key">' + escapeHtml(mem.key) + '</span>' +
                        '<span class="settings-memory-value">' + escapeHtml(mem.value) + '</span>' +
                        '<button class="btn-icon-sm memory-delete-btn" data-id="' + mem.id + '" title="Delete">' +
                            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
                        '</button>';
                    container.appendChild(item);
                });

                container.querySelectorAll('.memory-delete-btn').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var id = btn.dataset.id;
                        fetch('/api/memory/' + encodeURIComponent(id), { method: 'DELETE' })
                            .then(function () { loadMemories(); });
                    });
                });
            });
    }

    // ── Clear All Memories ────────────────────────────
    var btnClearMem = document.getElementById('btn-clear-memories');
    if (btnClearMem) {
        btnClearMem.addEventListener('click', function () {
            if (!confirm('Delete all stored memories? This cannot be undone.')) return;
            fetch('/api/memory/all', { method: 'DELETE' })
                .then(function () { loadMemories(); });
        });
    }

    // ── RAG / Documents ───────────────────────────────
    var btnRagIndex = document.getElementById('btn-rag-index');
    var ragFolderInput = document.getElementById('rag-folder-input');
    var ragFoldersList = document.getElementById('rag-folders-list');
    var ragStatus = document.getElementById('rag-index-status');

    function loadRagFolders() {
        if (!ragFoldersList) return;
        fetch('/api/rag/folders')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var folders = d.folders || [];
                if (folders.length === 0) {
                    ragFoldersList.innerHTML = '<p class="settings-empty">No folders indexed yet.</p>';
                    return;
                }
                ragFoldersList.innerHTML = '';
                folders.forEach(function (f) {
                    var item = document.createElement('div');
                    item.className = 'settings-memory-item';
                    item.innerHTML =
                        '<span class="settings-memory-key" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeAttr(f.folder) + '">' + escapeHtml(f.folder) + '</span>' +
                        '<span class="settings-memory-value" style="flex-shrink:0;">' + f.file_count + ' files, ' + f.chunk_count + ' chunks</span>' +
                        '<button class="settings-btn settings-btn-sm rag-reindex-btn" data-folder="' + escapeAttr(f.folder) + '" title="Re-index" style="margin-left:4px;">Re-index</button>' +
                        '<button class="btn-icon-sm rag-delete-btn" data-folder="' + escapeAttr(f.folder) + '" title="Remove" style="margin-left:4px;">' +
                            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
                        '</button>';
                    ragFoldersList.appendChild(item);
                });

                // Re-index buttons
                ragFoldersList.querySelectorAll('.rag-reindex-btn').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        indexFolder(btn.dataset.folder);
                    });
                });

                // Delete buttons
                ragFoldersList.querySelectorAll('.rag-delete-btn').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var folder = btn.dataset.folder;
                        fetch('/api/rag/folder', {
                            method: 'DELETE',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ folder: folder }),
                        }).then(function () { loadRagFolders(); });
                    });
                });
            });
    }

    function indexFolder(folderPath) {
        if (!ragStatus) return;
        ragStatus.style.display = '';
        ragStatus.textContent = 'Indexing ' + folderPath + '...';
        if (btnRagIndex) btnRagIndex.disabled = true;

        fetch('/api/rag/index', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder: folderPath }),
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.error) {
                    ragStatus.textContent = 'Error: ' + d.error;
                } else {
                    ragStatus.textContent = 'Indexed ' + d.files_indexed + ' files (' + d.total_chunks + ' chunks)';
                }
                loadRagFolders();
                setTimeout(function () { ragStatus.style.display = 'none'; }, 4000);
            })
            .catch(function () {
                ragStatus.textContent = 'Indexing failed.';
                setTimeout(function () { ragStatus.style.display = 'none'; }, 4000);
            })
            .finally(function () {
                if (btnRagIndex) btnRagIndex.disabled = false;
            });
    }

    if (btnRagIndex) {
        btnRagIndex.addEventListener('click', function () {
            var folder = ragFolderInput ? ragFolderInput.value.trim() : '';
            if (!folder) return;
            indexFolder(folder);
            ragFolderInput.value = '';
        });
    }

    // Load RAG folders when settings panel opens
    // (already handled inside loadSettings)

    // ── Voice settings ─────────────────────────────────
    var voiceLangSelect  = document.getElementById('voice-lang-select');
    var voiceSelect      = document.getElementById('voice-select');
    var voiceRateRange   = document.getElementById('voice-rate-range');
    var voiceRateLabel   = document.getElementById('voice-rate-label');
    var btnVoiceTest     = document.getElementById('btn-voice-test');

    function populateVoiceList() {
        if (!window.speechSynthesis || !voiceSelect) return;
        var voices = window.speechSynthesis.getVoices();
        if (!voices.length) return;
        var vs   = window.Axon && window.Axon.voiceSettings;
        var lang = vs ? vs.lang : 'en-US';
        voiceSelect.innerHTML = '<option value="">Default</option>';
        voices.forEach(function (v) {
            var opt = document.createElement('option');
            opt.value = v.name;
            opt.textContent = v.name + ' (' + v.lang + ')';
            if (vs && v.name === vs.voiceName) opt.selected = true;
            voiceSelect.appendChild(opt);
        });
    }

    function syncVoiceUI() {
        var vs = window.Axon && window.Axon.voiceSettings;
        if (!vs) return;
        if (voiceLangSelect) voiceLangSelect.value = vs.lang;
        if (voiceRateRange)  voiceRateRange.value  = vs.rate;
        if (voiceRateLabel)  voiceRateLabel.textContent = vs.rate.toFixed(1) + '×';
        populateVoiceList();
    }

    // Populate voice list when voices become available
    if (window.speechSynthesis) {
        window.speechSynthesis.addEventListener('voiceschanged', populateVoiceList);
        populateVoiceList();
    }

    if (voiceLangSelect) {
        voiceLangSelect.addEventListener('change', function () {
            var vs = window.Axon && window.Axon.voiceSettings;
            if (!vs) return;
            vs.lang = voiceLangSelect.value;
            vs.save();
            populateVoiceList();
        });
    }

    if (voiceSelect) {
        voiceSelect.addEventListener('change', function () {
            var vs = window.Axon && window.Axon.voiceSettings;
            if (!vs) return;
            vs.voiceName = voiceSelect.value;
            vs.save();
        });
    }

    if (voiceRateRange) {
        voiceRateRange.addEventListener('input', function () {
            var val = parseFloat(voiceRateRange.value);
            if (voiceRateLabel) voiceRateLabel.textContent = val.toFixed(1) + '×';
            var vs = window.Axon && window.Axon.voiceSettings;
            if (vs) { vs.rate = val; vs.save(); }
        });
    }

    if (btnVoiceTest) {
        btnVoiceTest.addEventListener('click', function () {
            var tts = window.Axon && window.Axon.tts;
            if (tts) tts.speak("Hello, I'm Axon. Voice output is working.");
        });
    }

    // Sync voice UI when settings panel opens
    var origSettingsOpen = document.getElementById('btn-settings');
    if (origSettingsOpen) {
        origSettingsOpen.addEventListener('click', function () {
            // small delay so the DOM is visible before we sync
            setTimeout(syncVoiceUI, 50);
            // Fetch LAN URL each time settings opens
            fetchAndDisplayLanUrl();
        });
    }

    // ── LAN URL detection ─────────────────────────────
    function fetchAndDisplayLanUrl() {
        fetch('/api/network-info')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                _lanUrl = d.url || '';
                var el = document.getElementById('settings-lan-url');
                if (el) el.textContent = _lanUrl || 'Unavailable';
            })
            .catch(function () {
                var el = document.getElementById('settings-lan-url');
                if (el) el.textContent = 'Unavailable';
            });
    }

    var btnCopyLan = document.getElementById('btn-copy-lan-url');
    if (btnCopyLan) {
        btnCopyLan.addEventListener('click', function () {
            if (!_lanUrl) return;
            navigator.clipboard.writeText(_lanUrl).then(function () {
                var orig = btnCopyLan.textContent;
                btnCopyLan.textContent = 'Copied!';
                setTimeout(function () { btnCopyLan.textContent = orig; }, 2000);
            }).catch(function () {
                // Fallback for browsers without clipboard API
                var ta = document.createElement('textarea');
                ta.value = _lanUrl;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                var orig = btnCopyLan.textContent;
                btnCopyLan.textContent = 'Copied!';
                setTimeout(function () { btnCopyLan.textContent = orig; }, 2000);
            });
        });
    }

    // ── Reset All Settings ────────────────────────────
    var btnResetSettings = document.getElementById('btn-reset-settings');
    if (btnResetSettings) {
        btnResetSettings.addEventListener('click', function () {
            if (!confirm('Reset all settings to defaults? This cannot be undone.')) return;
            fetch('/api/settings/reset', { method: 'POST' })
                .then(function () { location.reload(); })
                .catch(function () { alert('Failed to reset settings.'); });
        });
    }

    // ── Connection status polling ─────────────────────
    var _lanUrl = '';

    function checkConnection() {
        fetch('/api/connection')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var sendBtn = document.getElementById('btn-send');
                if (d.connected) {
                    connDot.className = 'connection-dot online';
                    connText.textContent = 'LM Studio Connected';
                    Axon.isOffline = false;
                    // Re-enable send if there's text (main.js will handle this on input events,
                    // but we restore it now if the input has content)
                    if (sendBtn && !Axon.streaming) {
                        var inp = document.getElementById('chat-input');
                        sendBtn.disabled = !(inp && inp.value.trim());
                    }
                } else {
                    connDot.className = 'connection-dot offline';
                    connText.textContent = 'LM Studio Offline';
                    Axon.isOffline = true;
                    if (sendBtn && !Axon.streaming) sendBtn.disabled = true;
                }
            })
            .catch(function () {
                connDot.className = 'connection-dot offline';
                connText.textContent = 'LM Studio Offline';
                Axon.isOffline = true;
                var sendBtn = document.getElementById('btn-send');
                if (sendBtn && !Axon.streaming) sendBtn.disabled = true;
            });
    }

    checkConnection();
    setInterval(checkConnection, 10000);

    // ── HTML escape helpers ───────────────────────────
    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
    function escapeAttr(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
})();
