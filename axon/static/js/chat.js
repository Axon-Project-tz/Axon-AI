// chat.js — Chat sending, streaming responses, message rendering

(function () {
    var chatArea = document.getElementById('chat-area');
    var welcome = document.getElementById('welcome');

    // ── Markdown config ───────────────────────────────
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
        });
    }

    function applySyntaxHighlighting(container) {
        if (!container || typeof hljs === 'undefined') return;
        var codeBlocks = container.querySelectorAll('pre code');
        codeBlocks.forEach(function (codeEl) {
            var classNames = (codeEl.className || '').split(' ');
            var languageClass = '';
            for (var i = 0; i < classNames.length; i++) {
                if (classNames[i].indexOf('language-') === 0) {
                    languageClass = classNames[i];
                    break;
                }
            }

            var lang = languageClass ? languageClass.replace('language-', '') : '';
            if (lang && !hljs.getLanguage(lang)) {
                codeEl.classList.remove(languageClass);
            }

            hljs.highlightElement(codeEl);
        });
    }

    function renderMarkdown(text) {
        if (typeof marked !== 'undefined') {
            return marked.parse(text);
        }
        // Fallback — escape HTML and convert newlines
        return text
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>');
    }

    // ── Parse <think> blocks into collapsible reasoning ──
    function renderWithThinking(text, thinkSeconds) {
        var thinkRegex = /^<think>([\s\S]*?)<\/think>\s*/;
        var match = text.match(thinkRegex);
        if (!match) return renderMarkdown(text);

        var thinkContent = match[1].trim();
        var answer = text.substring(match[0].length);
        var html = '';

        if (thinkContent) {
            var label = thinkSeconds
                ? 'Thought for ' + thinkSeconds + 's'
                : 'Thought process';
            html += '<details class="think-block">' +
                '<summary class="think-toggle">' +
                '<svg class="think-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>' +
                label + '</summary>' +
                '<div class="think-content">' + renderMarkdown(thinkContent) + '</div>' +
                '</details>';
        }

        if (answer) {
            html += renderMarkdown(answer);
        }
        return html;
    }

    // Streaming version — handles incomplete <think> tags mid-stream
    function renderStreamingWithThinking(text) {
        // Still inside an unclosed <think> block
        if (text.indexOf('<think>') !== -1 && text.indexOf('</think>') === -1) {
            var thinkBody = text.substring(text.indexOf('<think>') + 7).trim();
            if (!thinkBody) return '<div class="think-streaming">Thinking...</div>';
            return '<details class="think-block" open>' +
                '<summary class="think-toggle">' +
                '<svg class="think-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>' +
                'Thinking...</summary>' +
                '<div class="think-content">' + renderMarkdown(thinkBody) + '</div>' +
                '</details>';
        }
        // Has complete <think>...</think> — render fully
        return renderWithThinking(text);
    }

    // ── Add copy + run buttons and language labels to code blocks ──
    function enhanceCodeBlocks(container) {
        var pres = container.querySelectorAll('pre');
        pres.forEach(function (pre) {
            if (pre.querySelector('.code-header')) return; // already enhanced
            var codeEl = pre.querySelector('code');
            if (!codeEl) return;

            // Detect language from class
            var lang = '';
            var classes = codeEl.className.split(' ');
            for (var i = 0; i < classes.length; i++) {
                if (classes[i].indexOf('language-') === 0 || classes[i].indexOf('hljs') === -1 && classes[i]) {
                    lang = classes[i].replace('language-', '').replace('hljs', '').trim();
                    if (lang) break;
                }
            }

            // Determine if this is a runnable language
            var runnableLangs = ['python', 'py', 'powershell', 'ps1', 'batch', 'bat', 'cmd', 'bash', 'sh'];
            var isRunnable = Axon.features && Axon.features.agent && runnableLangs.indexOf(lang.toLowerCase()) !== -1;

            var header = document.createElement('div');
            header.className = 'code-header';
            header.innerHTML =
                '<span class="code-lang">' + (lang || 'code') + '</span>' +
                '<div class="code-actions">' +
                (isRunnable ? '<button class="code-run-btn" title="Run code">Run</button>' : '') +
                '<button class="code-copy-btn" title="Copy code">Copy</button>' +
                '</div>';

            pre.insertBefore(header, pre.firstChild);

            header.querySelector('.code-copy-btn').addEventListener('click', function () {
                var text = codeEl.textContent;
                navigator.clipboard.writeText(text).then(function () {
                    var btn = header.querySelector('.code-copy-btn');
                    btn.textContent = 'Copied!';
                    setTimeout(function () { btn.textContent = 'Copy'; }, 1500);
                });
            });

            var runBtn = header.querySelector('.code-run-btn');
            if (runBtn) {
                runBtn.addEventListener('click', function () {
                    var code = codeEl.textContent;
                    runBtn.textContent = 'Running...';
                    runBtn.disabled = true;

                    fetch('/api/agent/run-code', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            code: code,
                            language: lang || 'py',
                        }),
                    })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            runBtn.textContent = 'Run';
                            runBtn.disabled = false;
                            // Show output inline below the code block
                            var existing = pre.parentElement.querySelector('.agent-output-inline');
                            if (existing) existing.remove();

                            var outputText = d.output || d.error || '(no output)';
                            var isErr = !d.success || (d.error && !d.output);
                            var outputBox = document.createElement('div');
                            outputBox.className = 'agent-output-inline';
                            outputBox.innerHTML =
                                '<div class="agent-output-header">' +
                                '<span class="agent-output-label">Output</span>' +
                                '<span class="agent-output-file">' + escapeHtml(d.filename || '') + '</span>' +
                                '</div>' +
                                '<pre class="agent-output-pre"><code class="' + (isErr ? 'agent-output-error' : '') + '">' + escapeHtml(outputText) + '</code></pre>';
                            pre.insertAdjacentElement('afterend', outputBox);
                            scrollToBottom();
                        })
                        .catch(function () {
                            runBtn.textContent = 'Run';
                            runBtn.disabled = false;
                        });
                });
            }
        });

        applySyntaxHighlighting(container);
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ── Render a message bubble ───────────────────────
    function createMessageEl(role, content, attachedFile) {
        var msg = document.createElement('div');
        msg.className = 'message message-' + role;

        // Show file attachment card inside user bubble
        if (role === 'user' && attachedFile) {
            var card = document.createElement('div');
            card.className = 'msg-file-card';
            card.innerHTML =
                '<div class="msg-file-icon">' +
                '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' +
                '</div>' +
                '<div class="msg-file-info">' +
                '<span class="msg-file-name">' + escapeHtml(attachedFile.filename) + '</span>' +
                '<span class="msg-file-type">' + escapeHtml(attachedFile.type || 'Document') + '</span>' +
                '</div>';
            msg.appendChild(card);
        }

        var bubble = document.createElement('div');
        bubble.className = 'message-content';

        if (role === 'user') {
            bubble.textContent = content;
        } else {
            bubble.innerHTML = renderWithThinking(content, 0);
            enhanceCodeBlocks(bubble);
        }

        msg.appendChild(bubble);

        // Speaker button for assistant messages
        if (role === 'assistant') {
            var actions = document.createElement('div');
            actions.className = 'message-actions';
            var speakBtn = document.createElement('button');
            speakBtn.className = 'msg-speak-btn';
            speakBtn.title = 'Read aloud';
            speakBtn.innerHTML =
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>' +
                '<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>' +
                '<path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>' +
                '</svg>';
            speakBtn.addEventListener('click', function () {
                var tts = window.Axon && window.Axon.tts;
                if (!tts) return;
                if (speakBtn.classList.contains('speaking')) {
                    tts.stop();
                    speakBtn.classList.remove('speaking');
                } else {
                    tts.speak(content, function () {
                        speakBtn.classList.remove('speaking');
                    });
                    speakBtn.classList.add('speaking');
                }
            });
            actions.appendChild(speakBtn);
            msg.appendChild(actions);
        }

        return msg;
    }

    // ── Typing indicator ──────────────────────────────
    function createTypingIndicator() {
        var accent = Axon.getActiveAccent();
        var msg = document.createElement('div');
        msg.className = 'message message-assistant';
        msg.id = 'typing-indicator';

        var bubble = document.createElement('div');
        bubble.className = 'message-content typing-dots';
        bubble.innerHTML =
            '<span class="dot" style="background:' + accent + '"></span>' +
            '<span class="dot" style="background:' + accent + '"></span>' +
            '<span class="dot" style="background:' + accent + '"></span>';
        msg.appendChild(bubble);
        return msg;
    }

    function removeTypingIndicator() {
        var el = document.getElementById('typing-indicator');
        if (el) el.remove();
    }

    // ── Smart auto-scroll ─────────────────────────────
    var userHasScrolledUp = false;

    function isNearBottom() {
        return chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 80;
    }

    chatArea.addEventListener('scroll', function () {
        if (!Axon.streaming) return;
        if (isNearBottom()) {
            userHasScrolledUp = false;
        } else {
            userHasScrolledUp = true;
        }
    });

    function scrollToBottom(force) {
        if (force || !userHasScrolledUp) {
            chatArea.scrollTop = chatArea.scrollHeight;
        }
    }

    function bindWelcomeActions(container) {
        if (!container) return;
        container.querySelectorAll('.suggestion-card').forEach(function (card) {
            card.addEventListener('click', function () {
                var titleEl = card.querySelector('.suggestion-title');
                var promptMap = {
                    'Research AI hardware': 'Research the latest AI hardware and compare the strongest options right now.',
                    'Write and run code': 'Write and run a Python script that solves a useful real-world task.',
                    'Analyze an image': 'Analyze an uploaded image and explain the most important details.',
                    'Ask anything': 'Help me think through a difficult question clearly and directly.'
                };
                var title = titleEl ? titleEl.textContent.trim() : '';
                var input = document.getElementById('chat-input');
                if (!input) return;
                input.value = promptMap[title] || card.textContent.trim();
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.focus();
            });
        });
    }

    function createWelcomeEl() {
        var w = welcome.cloneNode(true);
        w.style.display = '';
        bindWelcomeActions(w);
        return w;
    }

    bindWelcomeActions(welcome);

    // ── Render all messages for a chat ────────────────
    Axon.renderMessages = function (messages) {
        // Clear chat area
        chatArea.innerHTML = '';
        if (!messages || messages.length === 0) {
            chatArea.appendChild(createWelcomeEl());
            return;
        }
        welcome.style.display = 'none';
        messages.forEach(function (m) {
            chatArea.appendChild(createMessageEl(m.role, m.content));
        });
        scrollToBottom(true);
    };

    // ── Show welcome screen ───────────────────────────
    Axon.showWelcome = function () {
        chatArea.innerHTML = '';
        chatArea.appendChild(createWelcomeEl());
    };

    // ── DeepThink trigger detection ───────────────────
    // Regex patterns that match the FULL phrase, not individual words.
    // 'research' alone is only matched when it starts the message (as a verb command)
    // or is followed by 'for/about/on/into', to avoid false-positives like
    // "write a research paper" or "I need to research for class".
    var DEEPTHINK_PATTERNS = [
        /\bsearch\s+for\b/i,
        /\bsearch\s+the\s+web\b/i,
        /\bdo\s+a\s+deep\s+search\b/i,
        /\bdeep\s+search\b/i,
        /\blook\s+up\b/i,
        /\bfind\s+information\s+about\b/i,
        /\bwhat\s+does\s+the\s+internet\s+say\b/i,
        /^\s*research\s+\w/i,
        /\bresearch\s+(?:for|about|on|into)\b/i,
        /^\/deep\b/,
        /^\/search\b/,
    ];

    function shouldDeepThink(text) {
        if (!Axon.features || !Axon.features.deepthink) return false;
        for (var i = 0; i < DEEPTHINK_PATTERNS.length; i++) {
            if (DEEPTHINK_PATTERNS[i].test(text)) return true;
        }
        return false;
    }

    // ── DeepThink status indicator (single updating line) ──
    function showDeepThinkStatus(text) {
        var el = document.getElementById('deepthink-status');
        if (!el) {
            el = document.createElement('div');
            el.id = 'deepthink-status';
            el.className = 'deepthink-status';
            chatArea.appendChild(el);
        }
        el.textContent = text;
        scrollToBottom();
    }

    function removeDeepThinkStatus() {
        var el = document.getElementById('deepthink-status');
        if (el) el.remove();
    }

    // ── DeepThink sources panel ───────────────────────
    function appendSourcesPanel(container, urls) {
        if (!urls || !urls.length) return;
        var panel = document.createElement('div');
        panel.className = 'deepthink-sources';

        var toggle = document.createElement('button');
        toggle.className = 'deepthink-sources-toggle';
        toggle.innerHTML =
            '<span class="deepthink-sources-icon">\uD83D\uDD0D</span>' +
            '<span>Sources (' + urls.length + ')</span>' +
            '<span class="deepthink-sources-chevron">\u203A</span>';

        var list = document.createElement('div');
        list.className = 'deepthink-sources-list';

        urls.forEach(function (url) {
            var a = document.createElement('a');
            a.href = url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.className = 'deepthink-sources-url';
            var display = url;
            try { display = new URL(url).hostname; } catch (e) {}
            a.textContent = display;
            a.title = url;
            list.appendChild(a);
        });

        toggle.addEventListener('click', function () {
            var open = list.style.display !== 'none';
            list.style.display = open ? 'none' : 'flex';
            toggle.classList.toggle('open', !open);
        });

        panel.appendChild(toggle);
        panel.appendChild(list);
        container.appendChild(panel);
    }

    // ── Agent file-operation helpers ────────────────────
    var agentContext = null; // tracks what agent action was used for the current message

    function detectAndReadFile(message, callback) {
        // If agent mode is off, skip detection
        agentContext = null;
        if (!Axon.features || !Axon.features.agent) {
            callback(message);
            return;
        }

        fetch('/api/agent/detect-intent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message }),
        })
            .then(function (r) { return r.json(); })
            .then(function (intent) {
                if (intent.type === 'read') {
                    // Actually read the file from disk
                    fetch('/api/agent/file-read', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ path: intent.path }),
                    })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (d.success) {
                                agentContext = { type: 'file-read', path: d.path };
                                var augmented = '[File contents of ' + intent.path + ']\n\n' +
                                    d.content +
                                    (d.truncated ? '\n\n[Truncated — file is larger than 50KB]' : '') +
                                    '\n\n[User request]: ' + message;
                                callback(augmented);
                            } else {
                                var augmented = '[Tried to read ' + intent.path + ' but failed: ' + d.error + ']\n\n' + message;
                                callback(augmented);
                            }
                        })
                        .catch(function () { callback(message); });
                } else if (intent.type === 'list') {
                    // Actually list the directory
                    fetch('/api/agent/file-list', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ path: intent.path }),
                    })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (d.success) {
                                agentContext = { type: 'dir-list', path: d.path };
                                var listing = d.entries.map(function (e) {
                                    return (e.is_dir ? '[DIR] ' : '      ') + e.name + (e.size ? ' (' + e.size + ' bytes)' : '');
                                }).join('\n');
                                var augmented = '[Directory listing of ' + intent.path + ']\n\n' + listing + '\n\n[User request]: ' + message;
                                callback(augmented);
                            } else {
                                var augmented = '[Tried to list ' + intent.path + ' but failed: ' + d.error + ']\n\n' + message;
                                callback(augmented);
                            }
                        })
                        .catch(function () { callback(message); });
                } else if (intent.type === 'calculate') {
                    // Compute the math expression on the server
                    fetch('/api/agent/calculate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ expression: intent.expression }),
                    })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (d.success) {
                                agentContext = { type: 'calculate', expression: intent.expression, result: d.result };
                                var augmented = '[Computed: ' + intent.expression + ' = ' + d.result + ']\n\n[User request]: ' + message;
                                callback(augmented);
                            } else {
                                callback(message);
                            }
                        })
                        .catch(function () { callback(message); });
                } else {
                    // No file operation detected, or it's a write (handled after AI responds)
                    callback(message);
                }
            })
            .catch(function () { callback(message); });
    }

    function createAgentContextEl() {
        if (!agentContext) return null;
        var el = document.createElement('div');
        el.className = 'agent-context-indicator';
        var icon = '';
        var label = '';
        if (agentContext.type === 'file-read') {
            icon = '\uD83D\uDCC4';
            label = 'Read file: ' + agentContext.path;
        } else if (agentContext.type === 'dir-list') {
            icon = '\uD83D\uDCC2';
            label = 'Listed: ' + agentContext.path;
        } else if (agentContext.type === 'calculate') {
            icon = '\uD83E\uDDEE';
            label = agentContext.expression + ' = ' + agentContext.result;
        }
        el.innerHTML = '<span class="agent-context-icon">' + icon + '</span><span class="agent-context-text">' + escapeHtml(label) + '</span>';
        return el;
    }

    function executeFileWrites(responseText) {
        // Detect file-write blocks in the AI response and actually write them to disk
        if (!Axon.features || !Axon.features.agent) return;

        // Find code blocks with filename indicators and write them
        // Pattern: ```lang\n# filename.ext\ncontent\n``` or prose "save to filename.ext" before block
        var writePattern = /(?:(?:save|write|create|put)\s+(?:this\s+)?(?:to|in|as|into)\s+[`"']?(\S+\.\w{1,10})[`"']?\s*:?\s*\n*)?```\w*\s*\n(?:(?:#|\/\/|--)\s*(?:filename?:?\s*)?(\S+\.\w{1,10})\s*\n)?([\s\S]*?)\n```/gi;
        var match;
        var writes = [];

        while ((match = writePattern.exec(responseText)) !== null) {
            var filename = match[1] || match[2];
            var content = match[3];
            if (filename && content && content.trim()) {
                writes.push({ path: filename, content: content.trim() });
            }
        }

        // Execute each write
        writes.forEach(function (w) {
            fetch('/api/agent/file-write', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: w.path, content: w.content }),
            })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d.success) {
                        // Show confirmation in chat
                        var notice = document.createElement('div');
                        notice.className = 'message message-assistant';
                        var bubble = document.createElement('div');
                        bubble.className = 'message-content agent-output';
                        bubble.innerHTML =
                            '<div class="agent-output-header">' +
                            '<span class="agent-output-label">File Written</span>' +
                            '</div>' +
                            '<pre class="agent-output-pre"><code>' + escapeHtml(d.path) + ' (' + d.bytes_written + ' bytes)</code></pre>';
                        notice.appendChild(bubble);
                        chatArea.appendChild(notice);
                        scrollToBottom();
                    }
                })
                .catch(function () { /* silent */ });
        });
    }

    // Expose enhanceCodeBlocks for other scripts (deep_research.js)
    Axon._enhanceCodeBlocks = enhanceCodeBlocks;

    // ── Send message ──────────────────────────────────
    Axon.sendMessage = function () {
        var input = document.getElementById('chat-input');
        var text = input.value.trim();
        if (!text || Axon.streaming) return;

        // Prepend attached file content if present
        var displayText = text;
        var sendText = text;
        if (Axon.attachedFile) {
            sendText = '[File: ' + Axon.attachedFile.filename + ']\n\n' +
                       Axon.attachedFile.text + '\n\n[User question]: ' + text;
        }

        // Check if message triggers DeepThink via phrase detection or manual toggle
        var useDeepThink = shouldDeepThink(text) || Axon.deepSearchNext;
        if (Axon.deepSearchNext) {
            Axon.deepSearchNext = false;
            var dsBtn = document.getElementById('plus-deepsearch');
            if (dsBtn) {
                dsBtn.classList.remove('active');
                dsBtn.querySelector('span').textContent = 'Deep search';
            }
        }

        Axon.streaming = true;
        userHasScrolledUp = false;

        // Fade out welcome smoothly
        var w = chatArea.querySelector('.welcome');
        if (w) {
            w.classList.add('fade-out');
            setTimeout(function () { if (w.parentNode) w.parentNode.removeChild(w); }, 200);
        }

        // Capture file info for the user bubble before clearing
        var sentFile = Axon.attachedFile ? { filename: Axon.attachedFile.filename, type: getFileTypeLabel(Axon.attachedFile.filename) } : null;

        // Render user bubble
        chatArea.appendChild(createMessageEl('user', displayText, sentFile));
        scrollToBottom(true);

        // Clear input and attachment — must happen before showStopButton so
        // resetInput() doesn't re-disable the button after we enable it
        Axon.resetInput();
        if (Axon.clearAttachment) Axon.clearAttachment();
        showStopButton(true);

        // Detect file-read intent and augment message, then proceed
        detectAndReadFile(sendText, function (augmentedText) {
            sendText = augmentedText;

            // Check for memory commands (remember/forget/recall)
            if (Axon.features.memory) {
                fetch('/api/memory/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text }),
                })
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d.handled) {
                            // Show the memory response as an assistant bubble
                            var memMsg = createMessageEl('assistant', d.response || 'Done.');
                            chatArea.appendChild(memMsg);
                            enhanceCodeBlocks(memMsg.querySelector('.message-content'));
                            Axon.streaming = false;
                            showStopButton(false);
                            scrollToBottom(true);
                            return;
                        }
                        // Not a memory command — proceed with normal chat
                        startChat();
                    })
                    .catch(function () {
                        startChat();
                    });
            } else {
                startChat();
            }

            function startChat() {
                // Ensure we have a chat, then fire the request
                if (!Axon.activeChatId) {
                    fetch('/api/chats/new', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ slot_id: Axon.activeSlotId }),
                    })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            doChat(d.chat.id);
                        })
                        .catch(function () {
                            showError('Failed to create a new chat.');
                            Axon.streaming = false;
                        });
                } else {
                    doChat(Axon.activeChatId);
                }
            }
        });

        // Core chat execution
        function doChat(chatId) {
            Axon.activeChatId = chatId;

            // Create assistant message container
            var assistantMsg = document.createElement('div');
            assistantMsg.className = 'message message-assistant';

            // Insert agent context indicator (file read, calculate, etc.)
            var ctxEl = createAgentContextEl();
            if (ctxEl) assistantMsg.appendChild(ctxEl);

            // DeepThink: build a live collapsible research block above the answer
            var dtBlock = null;
            var dtBody = null;
            var dtStepsEl = null;
            var dtSummaryText = null;

            if (useDeepThink) {
                dtBlock = document.createElement('details');
                dtBlock.className = 'dt-block';
                dtBlock.open = true;

                var dtSummaryEl = document.createElement('summary');
                dtSummaryEl.className = 'dt-summary';
                dtSummaryEl.innerHTML =
                    '<svg class="think-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none"' +
                    ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                    '<polyline points="6 9 12 15 18 9"/></svg>' +
                    '<span class="dt-summary-text">Searching…</span>';
                dtSummaryText = dtSummaryEl.querySelector('.dt-summary-text');

                dtBody = document.createElement('div');
                dtBody.className = 'dt-body';

                dtStepsEl = document.createElement('div');
                dtStepsEl.className = 'dt-steps';
                dtBody.appendChild(dtStepsEl);

                dtBlock.appendChild(dtSummaryEl);
                dtBlock.appendChild(dtBody);
                assistantMsg.appendChild(dtBlock);
                assistantMsg.style.display = '';
                chatArea.appendChild(assistantMsg);
            } else {
                assistantMsg.style.display = 'none';
                chatArea.appendChild(createTypingIndicator());
            }
            scrollToBottom();

            // Answer bubble — always rendered below the DT block
            var assistantBubble = document.createElement('div');
            assistantBubble.className = 'message-content';
            assistantMsg.appendChild(assistantBubble);

            var fullText = '';
            var firstToken = true;
            var thinkStartTime = null;
            var thinkDuration = 0;
            var pendingSources = null;
            var routedSlotId = null;

            // Choose endpoint based on mode
            var endpoint = '/api/chat';
            var body = { chat_id: chatId, slot_id: Axon.activeSlotId, message: sendText };

            if (useDeepThink) {
                endpoint = '/api/deepthink';
                body = { query: sendText, chat_id: chatId, slot_id: Axon.activeSlotId };
            } else if (Axon.robloxMode || Axon.activeSlotId === 7) {
                endpoint = '/roblox-chat';
                body = {
                    chat_id: chatId,
                    message: sendText,
                    project_root: Axon.robloxProjectRoot || '',
                };
            }

            // SSE fetch
            var abortController = new AbortController();
            Axon._currentAbort = abortController;

            fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: abortController.signal,
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error('Server error: ' + response.status);
                }
                var reader = response.body.getReader();
                Axon._currentReader = reader;
                var decoder = new TextDecoder();
                var buffer = '';

                function readChunk() {
                    reader.read().then(function (result) {
                        if (result.done) {
                            finalize();
                            return;
                        }
                        buffer += decoder.decode(result.value, { stream: true });

                        // Process each SSE line
                        var lines = buffer.split('\n');
                        buffer = lines.pop(); // keep incomplete line

                        lines.forEach(function (line) {
                            if (line.indexOf('data: ') !== 0) return;
                            var payload = line.substring(6);
                            try {
                                var data = JSON.parse(payload);
                                if (data.type === 'status' || (data.step && !data.type)) {
                                    // DeepThink progress — append step to live research block
                                    if (dtStepsEl) {
                                        var _sl = document.createElement('div');
                                        _sl.className = 'dt-step-line';
                                        _sl.textContent = data.step;
                                        dtStepsEl.appendChild(_sl);
                                        if (dtSummaryText) dtSummaryText.textContent = data.step;
                                        scrollToBottom();
                                    }
                                } else if (data.type === 'sources') {
                                    // Store source URLs for the research block
                                    pendingSources = data.urls;
                                } else if (data.token) {
                                    if (firstToken) {
                                        if (useDeepThink) {
                                            // Collapse research block — answer is starting to stream
                                            if (dtBlock) dtBlock.open = false;
                                        } else {
                                            removeTypingIndicator();
                                            chatArea.appendChild(assistantMsg);
                                            assistantMsg.style.display = '';
                                        }
                                        removeDeepThinkStatus();
                                        firstToken = false;
                                    }
                                    fullText += data.token;
                                    // Track think block timing
                                    if (fullText.indexOf('<think>') !== -1 && !thinkStartTime) {
                                        thinkStartTime = Date.now();
                                    }
                                    if (fullText.indexOf('</think>') !== -1 && thinkStartTime && !thinkDuration) {
                                        thinkDuration = Math.round((Date.now() - thinkStartTime) / 1000);
                                    }
                                    assistantBubble.innerHTML = renderStreamingWithThinking(fullText);
                                    applySyntaxHighlighting(assistantBubble);
                                    scrollToBottom();
                                } else if (data.done) {
                                    if (data.routed_slot_id) routedSlotId = data.routed_slot_id;
                                    finalize();
                                    return;
                                } else if (data.error) {
                                    removeTypingIndicator();
                                    if (data.error_type === 'model_unloaded') {
                                        showModelUnloadedError(data.model_id, routedSlotId);
                                    } else {
                                        showError(data.error);
                                    }
                                    Axon.streaming = false;
                                    return;
                                }
                            } catch (e) { /* skip malformed */ }
                        });

                        readChunk();
                    }).catch(function (err) {
                        if (err.name === 'AbortError') {
                            finalize();
                            return;
                        }
                        removeTypingIndicator();
                        showError('Stream interrupted. Check your connection.');
                        Axon.streaming = false;
                        showStopButton(false);
                    });
                }

                readChunk();
            }).catch(function (err) {
                if (err.name === 'AbortError') {
                    finalize();
                    return;
                }
                removeTypingIndicator();
                showError('Could not reach LM Studio. Make sure it is running.');
                Axon.streaming = false;
                showStopButton(false);
            });

            function _getSlotInfo(slotId) {
                if (typeof MODEL_SLOTS !== 'undefined') {
                    for (var i = 0; i < MODEL_SLOTS.length; i++) {
                        if (MODEL_SLOTS[i].id === slotId) return MODEL_SLOTS[i];
                    }
                }
                return null;
            }

            function showRoutingPill(slotId) {
                var slotInfo = _getSlotInfo(slotId);
                var accent = slotInfo ? slotInfo.accent : '#5b8dee';
                var name = slotInfo ? slotInfo.name : ('Slot ' + slotId);
                var modelId = slotInfo ? slotInfo.model_id : '';
                var pill = document.createElement('div');
                pill.className = 'auto-route-pill';
                pill.style.color = accent;
                pill.style.borderColor = accent;
                pill.title = modelId ? ('Model: ' + modelId) : '';
                pill.innerHTML = '\u26a1 Routed to ' + name +
                    (modelId ? ' <span class="auto-route-model">' + escapeHtml(modelId) + '</span>' : '');
                chatArea.insertBefore(pill, assistantMsg);
                setTimeout(function () {
                    pill.style.opacity = '0';
                    pill.style.transform = 'translateY(-4px)';
                    setTimeout(function () { if (pill.parentNode) pill.parentNode.removeChild(pill); }, 400);
                }, 3000);
            }

            function showModelUnloadedError(modelId, slotId) {
                var slotInfo = slotId ? _getSlotInfo(slotId) : null;
                var slotName = slotInfo ? slotInfo.name : null;
                var mid = modelId || (slotInfo && slotInfo.model_id) || 'this model';
                var msg = document.createElement('div');
                msg.className = 'message message-assistant';
                var bubble = document.createElement('div');
                bubble.className = 'message-content message-error model-unloaded-error';
                var slotNote = slotName ? ' (routed to ' + slotName + ' slot)' : '';
                bubble.innerHTML =
                    '<strong>Model not loaded' + slotNote + '</strong><br>' +
                    'The model <code>' + escapeHtml(mid) + '</code> is not currently loaded in LM Studio.<br>' +
                    'Please load it in LM Studio and try again.';
                msg.appendChild(bubble);
                chatArea.appendChild(msg);
                scrollToBottom(true);
            }

            function finalize() {
                removeDeepThinkStatus();
                removeTypingIndicator();
                Axon._currentReader = null;
                Axon._currentAbort = null;
                if (fullText) {
                    if (!thinkDuration && thinkStartTime) {
                        thinkDuration = Math.round((Date.now() - thinkStartTime) / 1000);
                    }
                    assistantBubble.innerHTML = renderWithThinking(fullText, thinkDuration || 0);
                    enhanceCodeBlocks(assistantBubble);

                    // Execute real file writes if agent mode is on
                    executeFileWrites(fullText);
                }
                // Finalize DeepThink research block
                if (useDeepThink && dtBlock) {
                    var srcCount = pendingSources ? pendingSources.length : 0;
                    if (dtSummaryText) {
                        dtSummaryText.textContent = 'Searched ' + srcCount + ' source' + (srcCount !== 1 ? 's' : '');
                    }
                    if (pendingSources && pendingSources.length && dtBody) {
                        var dtSourcesEl = document.createElement('div');
                        dtSourcesEl.className = 'dt-sources';
                        pendingSources.forEach(function (url) {
                            var a = document.createElement('a');
                            a.href = url;
                            a.target = '_blank';
                            a.rel = 'noopener noreferrer';
                            a.className = 'dt-source-url';
                            var display = url;
                            try { display = new URL(url).hostname; } catch (e) {}
                            a.textContent = display;
                            a.title = url;
                            dtSourcesEl.appendChild(a);
                        });
                        dtBody.appendChild(dtSourcesEl);
                    }
                    dtBlock.open = false;
                    pendingSources = null;
                }
                // Show routing indicator if auto-routed to a different slot
                if (routedSlotId && routedSlotId !== Axon.activeSlotId) {
                    showRoutingPill(routedSlotId);
                }
                Axon.streaming = false;
                showStopButton(false);
                scrollToBottom(true);
                // Refresh sidebar to reflect new title / order
                if (typeof Axon.loadChats === 'function') {
                    Axon.loadChats();
                }
            }
        }
    };

    // ── Stop streaming ─────────────────────────────────
    Axon.stopStreaming = function () {
        if (!Axon.streaming) return;
        if (Axon._currentAbort) {
            Axon._currentAbort.abort();
            Axon._currentAbort = null;
        }
        if (Axon._currentReader) {
            try { Axon._currentReader.cancel(); } catch (e) { /* ok */ }
            Axon._currentReader = null;
        }
        removeDeepThinkStatus();
        removeTypingIndicator();
        Axon.streaming = false;
        showStopButton(false);
        scrollToBottom(true);
        if (typeof Axon.loadChats === 'function') {
            Axon.loadChats();
        }
    };

    // ── Toggle send / stop button ─────────────────────
    function showStopButton(show) {
        var btn = document.getElementById('btn-send');
        if (!btn) return;
        if (show) {
            btn.disabled = false;
            btn.classList.add('is-stop');
            btn.title = 'Stop generating';
            btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';
        } else {
            btn.classList.remove('is-stop');
            btn.title = 'Send message';
            btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
            var input = document.getElementById('chat-input');
            btn.disabled = !(input && input.value.trim());
        }
    }

    // ── File type label helper ─────────────────────────
    function getFileTypeLabel(name) {
        if (!name) return 'Document';
        var ext = name.split('.').pop().toLowerCase();
        var map = { pdf: 'PDF', txt: 'Text', csv: 'CSV', json: 'JSON', xml: 'XML', md: 'Markdown', py: 'Python', js: 'JavaScript', html: 'HTML', css: 'CSS', doc: 'Word', docx: 'Word', xls: 'Excel', xlsx: 'Excel', pptx: 'PowerPoint' };
        return map[ext] || ext.toUpperCase() + ' file';
    }

    // ── Error message in chat ─────────────────────────
    function showError(text) {
        var msg = document.createElement('div');
        msg.className = 'message message-assistant';
        var bubble = document.createElement('div');
        bubble.className = 'message-content message-error';
        bubble.textContent = text;
        msg.appendChild(bubble);
        chatArea.appendChild(msg);
        scrollToBottom(true);
    }
})();
