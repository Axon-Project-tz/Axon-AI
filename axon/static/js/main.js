// main.js — Core UI initialization and global state

var Axon = Axon || {};

(function () {
    // ── Global state ──────────────────────────────────
    Axon.activeSlotId = 1;
    Axon.activeChatId = null;
    Axon.chats = [];
    Axon.streaming = false;

    // ── Textarea auto-resize ──────────────────────────
    var body = document.body;
    var input = document.getElementById('chat-input');
    var sendBtn = document.getElementById('btn-send');
    if (!input) return;

    function autoResize() {
        input.style.height = 'auto';
        var maxH = parseFloat(getComputedStyle(input).maxHeight) || 150;
        if (input.scrollHeight > maxH) {
            input.style.height = maxH + 'px';
            input.style.overflowY = 'auto';
        } else {
            input.style.height = input.scrollHeight + 'px';
            input.style.overflowY = 'hidden';
        }
    }

    function syncComposerState() {
        var hasValue = !!input.value.trim();
        if (body) body.classList.toggle('composer-has-value', hasValue);
        if (sendBtn) sendBtn.disabled = !hasValue;
    }

    Axon.resetInput = function () {
        input.value = '';
        input.style.height = 'auto';
        input.style.overflowY = 'hidden';
        if (body) body.classList.remove('composer-has-value');
        if (sendBtn) sendBtn.disabled = true;
    };

    input.addEventListener('input', function () {
        autoResize();
        syncComposerState();
    });

    input.addEventListener('focus', function () {
        if (body) body.classList.add('composer-focused');
    });

    input.addEventListener('blur', function () {
        if (body) body.classList.remove('composer-focused');
    });

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (input.value.trim() && !Axon.streaming) {
                Axon.sendMessage();
            }
        }
    });

    if (sendBtn) {
        sendBtn.addEventListener('click', function () {
            if (Axon.streaming) {
                if (typeof Axon.stopStreaming === 'function') Axon.stopStreaming();
                return;
            }
            if (input.value.trim()) {
                Axon.sendMessage();
            }
        });
    }

    // ── Slot accent on input bar ──────────────────────
    Axon.activeAccent = '#3B82F6';

    Axon.getActiveAccent = function () {
        return Axon.activeAccent || '#3B82F6';
    };

    requestAnimationFrame(function () {
        requestAnimationFrame(function () {
            if (body) body.classList.add('app-ready');
            autoResize();
            syncComposerState();
        });
    });
})();
