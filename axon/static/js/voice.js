// voice.js — Voice input and output handling
(function () {
    'use strict';

    // ── Voice settings (persisted in localStorage) ────────
    var VS = {
        lang:      localStorage.getItem('voice_lang')  || 'en-US',
        voiceName: localStorage.getItem('voice_name')  || '',
        rate:      parseFloat(localStorage.getItem('voice_rate') || '1.0'),
        save: function () {
            localStorage.setItem('voice_lang',  VS.lang);
            localStorage.setItem('voice_name',  VS.voiceName);
            localStorage.setItem('voice_rate',  String(VS.rate));
        }
    };
    window.Axon = window.Axon || {};
    window.Axon.voiceSettings = VS;

    function voiceOn() {
        return window.Axon && window.Axon.features && window.Axon.features.voice;
    }

    // ── Strip markdown so TTS reads clean prose ──────────
    function stripMarkdown(text) {
        return text
            .replace(/```[\s\S]*?```/g, ', code block, ')
            .replace(/`([^`]+)`/g, '$1')
            .replace(/^#{1,6}\s+/gm, '')
            .replace(/\*\*(.*?)\*\*/g, '$1')
            .replace(/\*(.*?)\*/g, '$1')
            .replace(/__(.*?)__/g, '$1')
            .replace(/_(.*?)_/g, '$1')
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
            .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
            .replace(/^[-*+]\s+/gm, '')
            .replace(/^\d+\.\s+/gm, '')
            .replace(/^>\s+/gm, '')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    // ── VoiceOutput (Text-to-Speech) ──────────────────────
    var synth = window.speechSynthesis;
    var VoiceOutput = {
        speaking: false,
        speak: function (text, onEnd) {
            if (!synth || !voiceOn()) return;
            if (synth.speaking) synth.cancel();
            var clean = stripMarkdown(text);
            if (!clean.trim()) return;

            var utter = new SpeechSynthesisUtterance(clean);
            utter.lang = VS.lang;
            utter.rate = VS.rate;

            if (VS.voiceName) {
                // getVoices may need a moment to populate
                var voices = synth.getVoices();
                var found = voices.find(function (v) { return v.name === VS.voiceName; });
                if (found) utter.voice = found;
            }

            utter.onstart = function () { VoiceOutput.speaking = true; };
            utter.onend   = function () { VoiceOutput.speaking = false; if (onEnd) onEnd(); };
            utter.onerror = function () { VoiceOutput.speaking = false; if (onEnd) onEnd(); };
            synth.speak(utter);
        },
        stop: function () {
            if (synth) synth.cancel();
            VoiceOutput.speaking = false;
        }
    };

    // ── VoiceInput (Speech-to-Text) ───────────────────────
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var recognition = null;

    // Callbacks kept across restarts
    var _onFinal   = null;
    var _onInterim = null;
    // Set when the user explicitly clicks stop — prevents auto-restart
    var _userStopped = false;

    function buildRecognition() {
        var r = new SR();
        r.lang           = VS.lang;
        r.interimResults = true;
        r.continuous     = true;

        r.onstart = function () {
            VoiceInput.active = true;
            setMicListening(true);
        };

        r.onresult = function (evt) {
            var interim = '', final_ = '';
            for (var i = evt.resultIndex; i < evt.results.length; i++) {
                if (evt.results[i].isFinal) final_ += evt.results[i][0].transcript;
                else interim += evt.results[i][0].transcript;
            }
            if (interim && _onInterim) _onInterim(interim);
            if (final_  && _onFinal)   _onFinal(final_);
        };

        r.onerror = function (evt) {
            console.warn('[Axon Voice] STT error:', evt.error);
            if (evt.error === 'not-allowed' || evt.error === 'service-not-allowed') {
                _userStopped = true;
                VoiceInput.active = false;
                setMicListening(false);
                recognition = null;
                showMicError('Microphone access denied. Please allow microphone permission in your browser and try again.');
            }
            // 'no-speech' and other transient errors: let onend handle the restart
        };

        r.onend = function () {
            // If the user hasn't explicitly stopped, restart to keep listening
            if (!_userStopped && VoiceInput.active) {
                try {
                    recognition = buildRecognition();
                    recognition.start();
                } catch (e) {
                    console.warn('[Axon Voice] restart failed:', e);
                    VoiceInput.active = false;
                    setMicListening(false);
                    recognition = null;
                }
            } else {
                VoiceInput.active = false;
                setMicListening(false);
                recognition = null;
            }
        };

        return r;
    }

    var VoiceInput = {
        active: false,
        start: function (onFinal, onInterim) {
            if (!SR || !voiceOn()) return;
            if (recognition) { recognition.abort(); recognition = null; }
            _onFinal     = onFinal;
            _onInterim   = onInterim;
            _userStopped = false;
            recognition  = buildRecognition();
            recognition.start();
        },
        stop: function () {
            _userStopped = true;
            VoiceInput.active = false;
            setMicListening(false);
            if (recognition) { recognition.stop(); recognition = null; }
        }
    };

    // ── Mic button visual state ───────────────────────────
    function setMicListening(on) {
        var btn = document.getElementById('btn-voice');
        if (!btn) return;
        btn.classList.toggle('listening', on);
        btn.title = on ? 'Stop listening' : (voiceOn() ? 'Voice input' : 'Voice disabled');
    }

    // ── Mic permission error message ─────────────────────
    function showMicError(msg) {
        var existing = document.getElementById('mic-error-toast');
        if (existing) existing.remove();
        var toast = document.createElement('div');
        toast.id = 'mic-error-toast';
        toast.textContent = msg;
        toast.style.cssText =
            'position:fixed;bottom:90px;left:50%;transform:translateX(-50%);' +
            'background:#1a0a0a;border:1px solid rgba(239,68,68,0.4);color:#f87171;' +
            'font-size:13px;padding:10px 16px;border-radius:10px;z-index:9999;' +
            'max-width:360px;text-align:center;pointer-events:none;' +
            'animation:fadeInUp 0.2s ease;';
        document.body.appendChild(toast);
        setTimeout(function () {
            toast.style.transition = 'opacity 0.3s';
            toast.style.opacity = '0';
            setTimeout(function () { toast.remove(); }, 350);
        }, 5000);
    }

    // ── Wire #btn-voice click ─────────────────────────────
    var btnVoice  = document.getElementById('btn-voice');
    var chatInput = document.getElementById('chat-input');

    if (btnVoice) {
        btnVoice.addEventListener('click', function () {
            if (!voiceOn()) return;
            if (VoiceInput.active) {
                VoiceInput.stop();
            } else {
                VoiceInput.start(
                    function (finalText) {
                        if (!chatInput) return;
                        var cur = chatInput.value.trimEnd();
                        chatInput.value = cur ? cur + ' ' + finalText : finalText;
                        chatInput.dispatchEvent(new Event('input', { bubbles: true }));
                        chatInput.focus();
                    },
                    null
                );
            }
        });
    }

    // ── Expose to window.Axon ────────────────────────────
    window.Axon.voice = VoiceInput;
    window.Axon.tts   = VoiceOutput;
}());
