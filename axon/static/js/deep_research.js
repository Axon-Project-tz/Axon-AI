// deep_research.js — Deep Research mode toggle + SSE rendering

(function () {
    'use strict';

    // ── State ─────────────────────────────────────────
    Axon.deepResearchNext = false;

    // ── + menu toggle ─────────────────────────────────
    var btn = document.getElementById('plus-deep-research');
    if (btn) {
        btn.addEventListener('click', function () {
            Axon.deepResearchNext = !Axon.deepResearchNext;
            btn.classList.toggle('active', Axon.deepResearchNext);
            var spanEl = btn.querySelector('span:not(.plus-menu-badge)');
            if (spanEl) {
                spanEl.textContent = Axon.deepResearchNext ? 'Deep research ✓' : 'Deep research';
            }
            // Update pill indicator
            updateResearchPill();
            // Close + menu
            var menu = document.getElementById('plus-menu');
            if (menu) menu.classList.remove('open');
        });
    }

    function updateResearchPill() {
        var existing = document.querySelector('.deep-research-pill');
        var inputBar = document.querySelector('.input-bar-inner');
        if (Axon.deepResearchNext) {
            if (!existing && inputBar) {
                var pill = document.createElement('span');
                pill.className = 'deep-research-pill';
                pill.textContent = '🔬 Deep Research';
                inputBar.insertBefore(pill, inputBar.querySelector('.chat-input'));
            }
        } else if (existing) {
            existing.remove();
        }
    }

    // ── Intercept sendMessage for deep research routing ──
    // Wrap the original sendMessage to detect deep research mode
    var _origSend = Axon.sendMessage;

    Axon.sendMessage = function () {
        if (!Axon.deepResearchNext) {
            // Normal path
            return _origSend.apply(this, arguments);
        }

        var input = document.getElementById('chat-input');
        var chatArea = document.getElementById('chat-area');
        var text = input.value.trim();
        if (!text || Axon.streaming) return;

        // Reset the toggle
        Axon.deepResearchNext = false;
        if (btn) {
            btn.classList.remove('active');
            var spanEl = btn.querySelector('span:not(.plus-menu-badge)');
            if (spanEl) spanEl.textContent = 'Deep research';
        }
        updateResearchPill();

        Axon.streaming = true;

        // Fade out welcome
        var w = chatArea.querySelector('.welcome');
        if (w) {
            w.classList.add('fade-out');
            setTimeout(function () { if (w.parentNode) w.parentNode.removeChild(w); }, 200);
        }

        // Render user bubble
        var userMsg = document.createElement('div');
        userMsg.className = 'message message-user';
        var userBubble = document.createElement('div');
        userBubble.className = 'message-content';
        userBubble.innerHTML = '<p>' + escapeHtml(text) + '</p>';
        userMsg.appendChild(userBubble);
        chatArea.appendChild(userMsg);

        // Clear input
        Axon.resetInput();
        showStopButton(true);

        // Ensure we have a chat
        if (!Axon.activeChatId) {
            fetch('/api/chats/new', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ slot_id: Axon.activeSlotId }),
            })
                .then(function (r) { return r.json(); })
                .then(function (d) { doDeepResearch(d.chat.id, text); })
                .catch(function () {
                    showError('Failed to create a new chat.');
                    Axon.streaming = false;
                    showStopButton(false);
                });
        } else {
            doDeepResearch(Axon.activeChatId, text);
        }
    };

    // ── Core deep research SSE handler ────────────────
    function doDeepResearch(chatId, topic) {
        Axon.activeChatId = chatId;
        var chatArea = document.getElementById('chat-area');

        // Build assistant message container
        var assistantMsg = document.createElement('div');
        assistantMsg.className = 'message message-assistant';

        // Progress panel
        var progressPanel = document.createElement('div');
        progressPanel.className = 'dr-progress-panel';
        var progressHeader = document.createElement('div');
        progressHeader.className = 'dr-progress-header';
        var pulseDot = document.createElement('span');
        pulseDot.className = 'dr-pulse-dot';
        progressHeader.appendChild(pulseDot);
        var progressHeaderText = document.createElement('span');
        progressHeaderText.textContent = '🔬 Deep Research in progress...';
        progressHeader.appendChild(progressHeaderText);
        progressPanel.appendChild(progressHeader);
        var progressSteps = document.createElement('div');
        progressSteps.className = 'dr-progress-steps';
        progressPanel.appendChild(progressSteps);
        assistantMsg.appendChild(progressPanel);

        // "See my thinking" collapsible (populated as findings arrive)
        var thinkBlock = document.createElement('details');
        thinkBlock.className = 'dt-block dr-thinking-block';
        var thinkSummary = document.createElement('summary');
        thinkSummary.className = 'dt-summary';
        thinkSummary.innerHTML =
            '<svg class="think-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none"' +
            ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<polyline points="6 9 12 15 18 9"/></svg>' +
            '<span class="dt-summary-text">See my thinking</span>';
        var thinkBody = document.createElement('div');
        thinkBody.className = 'dt-body';
        thinkBlock.appendChild(thinkSummary);
        thinkBlock.appendChild(thinkBody);
        assistantMsg.appendChild(thinkBlock);

        // Report container (wider layout, holds sticky bar + answer)
        var reportContainer = document.createElement('div');
        reportContainer.className = 'dr-report-container';
        reportContainer.style.display = 'none';
        assistantMsg.appendChild(reportContainer);

        // Sticky download toolbar at top of report (hidden until download ready)
        var downloadBar = document.createElement('div');
        downloadBar.className = 'dr-download-sticky';
        downloadBar.style.display = 'none';
        reportContainer.appendChild(downloadBar);

        // Answer bubble (inside report container)
        var answerBubble = document.createElement('div');
        answerBubble.className = 'message-content';
        reportContainer.appendChild(answerBubble);

        chatArea.appendChild(assistantMsg);
        scrollToBottom();

        var fullText = '';
        var findingCount = 0;
        var abortController = new AbortController();
        Axon._currentAbort = abortController;

        fetch('/deep-research', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic: topic, chat_id: chatId }),
            signal: abortController.signal,
        })
            .then(function (response) {
                if (!response.ok) throw new Error('Server error: ' + response.status);
                var reader = response.body.getReader();
                Axon._currentReader = reader;
                var decoder = new TextDecoder();
                var buffer = '';

                function readChunk() {
                    reader.read().then(function (result) {
                        if (result.done) { finalize(); return; }
                        buffer += decoder.decode(result.value, { stream: true });
                        var lines = buffer.split('\n');
                        buffer = lines.pop();

                        lines.forEach(function (line) {
                            if (line.indexOf('data: ') !== 0) return;
                            var payload = line.substring(6);
                            try {
                                var data = JSON.parse(payload);
                                handleEvent(data);
                            } catch (e) { /* skip malformed */ }
                        });

                        readChunk();
                    }).catch(function (err) {
                        if (err.name === 'AbortError') { finalize(); return; }
                        showError('Research stream interrupted.');
                        Axon.streaming = false;
                        showStopButton(false);
                    });
                }

                readChunk();
            })
            .catch(function (err) {
                if (err.name === 'AbortError') { finalize(); return; }
                showError('Could not reach server for Deep Research.');
                Axon.streaming = false;
                showStopButton(false);
            });

        function handleEvent(data) {
            if (data.type === 'status') {
                addProgressStep(data.step);
            } else if (data.type === 'plan') {
                // Show the research plan
                var planEl = document.createElement('div');
                planEl.className = 'dr-plan';
                var planTitle = document.createElement('div');
                planTitle.className = 'dr-plan-title';
                planTitle.textContent = 'Research Plan';
                planEl.appendChild(planTitle);
                var planList = document.createElement('ol');
                (data.sub_questions || []).forEach(function (sq) {
                    var li = document.createElement('li');
                    li.textContent = sq.question || sq;
                    planList.appendChild(li);
                });
                planEl.appendChild(planList);
                thinkBody.appendChild(planEl);
            } else if (data.type === 'finding') {
                findingCount++;
                var findEl = document.createElement('div');
                findEl.className = 'dr-finding';
                var findTitle = document.createElement('div');
                findTitle.className = 'dr-finding-title';
                findTitle.textContent = 'Finding ' + data.index + ': ' + (data.question || '');
                findEl.appendChild(findTitle);
                var findSummary = document.createElement('div');
                findSummary.className = 'dr-finding-summary';
                findSummary.innerHTML = renderMarkdown(data.summary || '');
                findEl.appendChild(findSummary);
                if (data.sources && data.sources.length) {
                    var srcEl = document.createElement('div');
                    srcEl.className = 'dr-finding-sources';
                    data.sources.forEach(function (s) {
                        var a = document.createElement('a');
                        a.href = s.url;
                        a.target = '_blank';
                        a.rel = 'noopener noreferrer';
                        a.className = 'dt-source-url';
                        a.textContent = s.title || s.url;
                        a.title = s.url;
                        srcEl.appendChild(a);
                    });
                    findEl.appendChild(srcEl);
                }
                thinkBody.appendChild(findEl);
                scrollToBottom();
            } else if (data.type === 'sources') {
                // Add a "sources" section at bottom of thinking panel
                if (data.urls && data.urls.length) {
                    var srcSection = document.createElement('div');
                    srcSection.className = 'dt-sources';
                    data.urls.forEach(function (url) {
                        var a = document.createElement('a');
                        a.href = url;
                        a.target = '_blank';
                        a.rel = 'noopener noreferrer';
                        a.className = 'dt-source-url';
                        try { a.textContent = new URL(url).hostname; } catch (e) { a.textContent = url; }
                        a.title = url;
                        srcSection.appendChild(a);
                    });
                    thinkBody.appendChild(srcSection);
                }
                // Update thinking summary text
                var summaryText = thinkBlock.querySelector('.dt-summary-text');
                if (summaryText) {
                    summaryText.textContent = 'Research: ' + findingCount + ' findings, ' + (data.urls ? data.urls.length : 0) + ' sources';
                }
            } else if (data.type === 'report') {
                // Show download buttons
                downloadBar.style.display = '';
                if (data.md_file) {
                    var mdBtn = document.createElement('a');
                    mdBtn.href = '/deep-research/report/' + encodeURIComponent(data.md_file);
                    mdBtn.className = 'dr-download-btn';
                    mdBtn.textContent = '📄 Download .md';
                    mdBtn.download = data.md_file;
                    downloadBar.appendChild(mdBtn);
                }
                if (data.pdf_file) {
                    var pdfBtn = document.createElement('a');
                    pdfBtn.href = '/deep-research/report/' + encodeURIComponent(data.pdf_file);
                    pdfBtn.className = 'dr-download-btn';
                    pdfBtn.textContent = '📑 Download PDF';
                    pdfBtn.download = data.pdf_file;
                    downloadBar.appendChild(pdfBtn);
                }
                if (data.word_count) {
                    var stats = document.createElement('span');
                    stats.className = 'dr-stats';
                    var mins = data.elapsed_seconds ? Math.floor(data.elapsed_seconds / 60) : 0;
                    var secs = data.elapsed_seconds ? data.elapsed_seconds % 60 : 0;
                    stats.textContent = data.word_count + ' words · ' + mins + 'm ' + secs + 's';
                    downloadBar.appendChild(stats);
                }
            } else if (data.token) {
                // Stream the report text into the answer bubble
                if (reportContainer.style.display === 'none') {
                    reportContainer.style.display = '';
                    // Stop pulse and update header
                    pulseDot.classList.add('done');
                    progressHeaderText.textContent = '✅ Deep Research complete';
                }
                fullText += data.token;
                answerBubble.innerHTML = renderMarkdown(fullText);
                applySyntaxHighlighting(answerBubble);
                scrollToBottom();
            } else if (data.done) {
                finalize();
            }
        }

        function addProgressStep(text) {
            var step = document.createElement('div');
            step.className = 'dr-progress-step';
            step.textContent = text;
            progressSteps.appendChild(step);
            scrollToBottom();
        }

        function finalize() {
            Axon._currentReader = null;
            Axon._currentAbort = null;
            pulseDot.classList.add('done');
            progressHeaderText.textContent = '✅ Deep Research complete';
            if (fullText) {
                reportContainer.style.display = '';
                answerBubble.innerHTML = renderMarkdown(fullText);
                enhanceCodeBlocks(answerBubble);
            }
            thinkBlock.open = false;
            Axon.streaming = false;
            showStopButton(false);
            scrollToBottom(true);
            if (typeof Axon.loadChats === 'function') Axon.loadChats();
        }
    }

    // ── Expose helpers that exist in chat.js (IIFE) ───
    // These are closured in chat.js; we re-reference the global versions
    function scrollToBottom(force) {
        var chatArea = document.getElementById('chat-area');
        if (!chatArea) return;
        if (force) {
            chatArea.scrollTop = chatArea.scrollHeight;
            return;
        }
        var nearBottom = chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 120;
        if (nearBottom) chatArea.scrollTop = chatArea.scrollHeight;
    }

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

    function showError(msg) {
        var chatArea = document.getElementById('chat-area');
        if (!chatArea) return;
        var el = document.createElement('div');
        el.className = 'message message-assistant';
        var bubble = document.createElement('div');
        bubble.className = 'message-content message-error';
        bubble.textContent = msg;
        el.appendChild(bubble);
        chatArea.appendChild(el);
        scrollToBottom(true);
    }

    function escapeHtml(text) {
        var d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }

    function renderMarkdown(text) {
        if (typeof marked !== 'undefined') return marked.parse(text);
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
    }

    function applySyntaxHighlighting(container) {
        if (!container || typeof hljs === 'undefined') return;
        container.querySelectorAll('pre code').forEach(function (el) { hljs.highlightElement(el); });
    }

    function enhanceCodeBlocks(container) {
        if (typeof Axon._enhanceCodeBlocks === 'function') {
            Axon._enhanceCodeBlocks(container);
        } else {
            applySyntaxHighlighting(container);
        }
    }
})();
