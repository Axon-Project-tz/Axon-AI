// upload.js — File and image upload handling
(function () {
    'use strict';

    var previewArea = document.getElementById('attachment-preview');
    var cardName = document.getElementById('attachment-card-name');
    var cardType = document.getElementById('attachment-card-type');
    var cardRemove = document.getElementById('attachment-card-remove');

    // Hidden file input
    var fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.pdf,.docx,.txt,.md,.csv,.json,.xml,.yaml,.yml,.toml,.ini,.cfg,.log,.py,.js,.ts,.jsx,.tsx,.html,.css,.java,.c,.cpp,.h,.cs,.go,.rs,.rb,.php,.swift,.kt,.lua,.r,.sh,.sql';
    fileInput.style.display = 'none';
    document.body.appendChild(fileInput);

    // State stored on global Axon object
    window.Axon = window.Axon || {};
    Axon.attachedFile = null; // { filename, text }

    // Expose trigger for + menu to call
    Axon.triggerFileUpload = function () {
        if (Axon.streaming) return;
        fileInput.click();
    };

    // File selected → upload
    fileInput.addEventListener('change', function () {
        var file = fileInput.files[0];
        if (!file) return;

        // Show card in loading state
        showCard(file.name, true);

        var formData = new FormData();
        formData.append('file', file);

        fetch('/api/upload', { method: 'POST', body: formData })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.error) {
                    hideCard();
                    alert('Upload failed: ' + d.error);
                    return;
                }
                Axon.attachedFile = { filename: d.filename, text: d.text };
                showCard(d.filename + (d.truncated ? ' (truncated)' : ''), false);
            })
            .catch(function () {
                hideCard();
                alert('Upload failed. Check console for errors.');
            });

        // Reset so same file can be re-selected
        fileInput.value = '';
    });

    // Remove button
    if (cardRemove) {
        cardRemove.addEventListener('click', function () {
            Axon.attachedFile = null;
            hideCard();
        });
    }

    function getFileType(name) {
        var ext = name.split('.').pop().toLowerCase();
        var types = {
            pdf: 'PDF Document', docx: 'Word Document', txt: 'Text File',
            md: 'Markdown', csv: 'CSV Data', json: 'JSON', xml: 'XML',
            py: 'Python', js: 'JavaScript', ts: 'TypeScript', html: 'HTML',
            css: 'CSS', java: 'Java', c: 'C', cpp: 'C++', go: 'Go',
            rs: 'Rust', rb: 'Ruby', php: 'PHP', sh: 'Shell Script',
            sql: 'SQL', yaml: 'YAML', yml: 'YAML'
        };
        return types[ext] || ext.toUpperCase();
    }

    function showCard(name, loading) {
        if (!previewArea || !cardName) return;
        cardName.textContent = loading ? name + ' — uploading...' : name;
        if (cardType) cardType.textContent = loading ? 'Uploading...' : getFileType(name);
        previewArea.style.display = '';
    }

    function hideCard() {
        if (!previewArea) return;
        previewArea.style.display = 'none';
        Axon.attachedFile = null;
    }

    // Expose hideCard for chat.js to call after send
    Axon.clearAttachment = hideCard;
})();
