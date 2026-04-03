// sidebar.js — Sidebar chat session management

(function () {
    var app = document.getElementById('app');
    var sidebarChats = document.querySelector('.sidebar-chats');
    var btnNewChat = document.getElementById('btn-new-chat');
    var btnSidebarToggle = document.getElementById('btn-sidebar-toggle');
    var searchInput = document.querySelector('.sidebar-search-input');
    var sidebar = document.getElementById('sidebar');
    var sidebarOverlay = document.getElementById('sidebar-overlay');
    var btnHamburger = document.getElementById('btn-hamburger');

    var allChats = []; // cached list

    // ── Date grouping helpers ─────────────────────────
    function getDateGroup(dateStr) {
        var d = new Date(dateStr + (dateStr.indexOf('Z') === -1 ? 'Z' : ''));
        var now = new Date();
        var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        var yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
        var week = new Date(today); week.setDate(week.getDate() - 7);

        if (d >= today) return 'Today';
        if (d >= yesterday) return 'Yesterday';
        if (d >= week) return 'Last 7 days';
        return 'Older';
    }

    function getSlotAccent(slotId) {
        for (var i = 0; i < MODEL_SLOTS.length; i++) {
            if (MODEL_SLOTS[i].id === slotId) return MODEL_SLOTS[i].accent;
        }
        return '#3B82F6';
    }

    // ── Render sidebar chat list ──────────────────────
    function renderChats(chats) {
        sidebarChats.innerHTML = '';
        if (!chats.length) {
            sidebarChats.innerHTML = '<p style="padding:16px;color:#555;font-size:13px;">No chats yet</p>';
            return;
        }

        var groups = {};
        var groupOrder = ['Today', 'Yesterday', 'Last 7 days', 'Older'];
        chats.forEach(function (c) {
            var g = getDateGroup(c.updated_at || c.created_at);
            if (!groups[g]) groups[g] = [];
            groups[g].push(c);
        });

        groupOrder.forEach(function (label) {
            if (!groups[label]) return;
            var group = document.createElement('div');
            group.className = 'chat-group';

            var lbl = document.createElement('div');
            lbl.className = 'chat-group-label';
            lbl.textContent = label;
            group.appendChild(lbl);

            groups[label].forEach(function (chat) {
                var item = document.createElement('div');
                item.className = 'chat-item' + (chat.id === Axon.activeChatId ? ' active' : '');
                item.style.setProperty('--item-accent', getSlotAccent(chat.slot_id || 1));
                item.dataset.chatId = chat.id;

                var title = document.createElement('span');
                title.className = 'chat-item-title';
                title.textContent = chat.title || 'New conversation';
                item.appendChild(title);

                var del = document.createElement('button');
                del.className = 'chat-item-delete btn-icon-sm';
                del.title = 'Delete';
                del.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';

                var actions = document.createElement('div');
                actions.className = 'chat-item-actions';
                actions.appendChild(del);
                item.appendChild(actions);

                // Click to switch chat
                item.addEventListener('click', function (e) {
                    if (e.target.closest('.chat-item-actions')) return;
                    switchToChat(chat.id);
                    closeMobileSidebar();
                });

                // Delete — show confirmation first
                del.addEventListener('click', function (e) {
                    e.stopPropagation();
                    confirmDeleteChat(chat.id, chat.title);
                });

                group.appendChild(item);
            });

            sidebarChats.appendChild(group);
        });
    }

    // ── Load chats from backend ───────────────────────
    Axon.loadChats = function () {
        fetch('/api/chats')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                allChats = d.chats || [];
                renderChats(allChats);
            })
            .catch(function () {
                allChats = [];
                renderChats([]);
            });
    };

    // ── Switch to a chat ──────────────────────────────
    function switchToChat(chatId) {
        Axon.activeChatId = chatId;

        // Highlight in sidebar
        document.querySelectorAll('.chat-item').forEach(function (el) {
            el.classList.toggle('active', el.dataset.chatId === chatId);
        });

        // Load messages
        fetch('/api/chats/' + encodeURIComponent(chatId))
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var msgs = d.messages || [];
                if (msgs.length === 0) {
                    Axon.showWelcome();
                } else {
                    Axon.renderMessages(msgs);
                }
            });
    }

    // ── New chat ──────────────────────────────────────
    function newChat() {
        fetch('/api/chats/new', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ slot_id: Axon.activeSlotId }),
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                Axon.activeChatId = d.chat.id;
                Axon.showWelcome();
                Axon.loadChats();
            });
    }

    // ── Delete chat ───────────────────────────────────
    function confirmDeleteChat(chatId, chatTitle) {
        // Build modal overlay
        var overlay = document.createElement('div');
        overlay.className = 'delete-confirm-overlay';

        var dialog = document.createElement('div');
        dialog.className = 'delete-confirm-dialog';

        var msg = document.createElement('p');
        msg.className = 'delete-confirm-msg';
        msg.innerHTML =
            'Are you sure you want to delete <strong>' +
            escapeHtmlBasic(chatTitle || 'this chat') +
            '</strong>?<br><span>This cannot be undone.</span>';

        var btnRow = document.createElement('div');
        btnRow.className = 'delete-confirm-btns';

        var btnCancel = document.createElement('button');
        btnCancel.className = 'delete-confirm-cancel';
        btnCancel.textContent = 'Cancel';

        var btnConfirm = document.createElement('button');
        btnConfirm.className = 'delete-confirm-ok';
        btnConfirm.textContent = 'Delete';

        btnRow.appendChild(btnCancel);
        btnRow.appendChild(btnConfirm);
        dialog.appendChild(msg);
        dialog.appendChild(btnRow);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Animate in
        requestAnimationFrame(function () { overlay.classList.add('visible'); });

        function close() {
            overlay.classList.remove('visible');
            setTimeout(function () { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); }, 200);
        }

        btnCancel.addEventListener('click', close);
        overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });

        btnConfirm.addEventListener('click', function () {
            close();
            doDeleteChat(chatId);
        });
    }

    function doDeleteChat(chatId) {
        fetch('/api/chats/' + encodeURIComponent(chatId), { method: 'DELETE' })
            .then(function () {
                if (Axon.activeChatId === chatId) {
                    Axon.activeChatId = null;
                    // Switch to the most recent remaining chat, or create a fresh one
                    fetch('/api/chats')
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            var remaining = d.chats || [];
                            if (remaining.length) {
                                switchToChat(remaining[0].id);
                                Axon.loadChats();
                            } else {
                                newChat();
                            }
                        })
                        .catch(function () { newChat(); });
                } else {
                    Axon.loadChats();
                }
            });
    }

    function escapeHtmlBasic(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ── Search filter ─────────────────────────────────
    if (searchInput) {
        searchInput.addEventListener('input', function () {
            var q = searchInput.value.toLowerCase().trim();
            if (!q) {
                renderChats(allChats);
                return;
            }
            var filtered = allChats.filter(function (c) {
                return (c.title || '').toLowerCase().indexOf(q) !== -1;
            });
            renderChats(filtered);
        });
    }

    // ── Mobile sidebar toggle ─────────────────────────
    function closeMobileSidebar() {
        sidebar.classList.remove('open');
        sidebarOverlay.classList.remove('active');
    }

    function updateSidebarToggleState() {
        if (!btnSidebarToggle || !app) return;
        var collapsed = app.classList.contains('sidebar-collapsed');
        btnSidebarToggle.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
        btnSidebarToggle.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    }

    function toggleDesktopSidebar() {
        if (!app || window.innerWidth <= 768) return;
        app.classList.toggle('sidebar-collapsed');
        updateSidebarToggleState();
    }

    if (btnHamburger) {
        btnHamburger.addEventListener('click', function () {
            sidebar.classList.add('open');
            sidebarOverlay.classList.add('active');
        });
    }
    if (btnSidebarToggle) {
        btnSidebarToggle.addEventListener('click', function () {
            if (window.innerWidth <= 768) {
                if (sidebar.classList.contains('open')) {
                    closeMobileSidebar();
                } else {
                    sidebar.classList.add('open');
                    sidebarOverlay.classList.add('active');
                }
                return;
            }
            toggleDesktopSidebar();
        });
    }
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', closeMobileSidebar);
    }

    // Close sidebar on any touch outside the sidebar element (most reliable mobile fix)
    document.addEventListener('touchstart', function (e) {
        if (sidebar && sidebar.classList.contains('open') &&
            !sidebar.contains(e.target) &&
            !(btnHamburger && btnHamburger.contains(e.target))) {
            closeMobileSidebar();
        }
    }, { passive: true });

    window.addEventListener('resize', function () {
        if (window.innerWidth > 768) {
            closeMobileSidebar();
        }
        updateSidebarToggleState();
    });

    // ── Events ────────────────────────────────────────
    if (btnNewChat) {
        btnNewChat.addEventListener('click', function () {
            newChat();
            closeMobileSidebar();
        });
    }

    // ── Init ──────────────────────────────────────────
    // On load: resume the most recent existing chat; only create a new one if
    // there are no chats at all.
    updateSidebarToggleState();
    fetch('/api/chats')
        .then(function (r) { return r.json(); })
        .then(function (d) {
            var chats = d.chats || [];
            allChats = chats;
            renderChats(chats);
            if (chats.length) {
                switchToChat(chats[0].id);
            } else {
                newChat();
            }
        })
        .catch(function () { newChat(); });
})();
