import { apiFetch, formatApiError } from './utils.js';
import { renderResumeFields, collectResumeFields, makeTextBlockList } from './form-builders.js';

// ---------- Edit Master Resume ----------

// ---------- Import master resume from existing resumes ----------
let importTextBlocksEl = null;

function resetImportInputs() {
    const container = document.getElementById('importTextBlocks');
    container.innerHTML = '';
    importTextBlocksEl = makeTextBlockList(1);
    container.appendChild(importTextBlocksEl);
    document.getElementById('importFiles').value = '';
}

export function initImportSection() {
    resetImportInputs();
    const statusEl = document.getElementById('importStatus');
    statusEl.className = '';
    statusEl.textContent = '';
}

document.getElementById('addImportTextBtn').addEventListener('click', () => {
    importTextBlocksEl._addBlock();
});

document.getElementById('importResumesBtn').addEventListener('click', async () => {
    const statusEl = document.getElementById('importStatus');
    const btn = document.getElementById('importResumesBtn');
    const texts = Array.from(importTextBlocksEl.querySelectorAll('textarea'))
        .map(t => t.value.trim()).filter(Boolean);
    const files = Array.from(document.getElementById('importFiles').files);

    if (!texts.length && !files.length) {
        statusEl.className = 'error';
        statusEl.textContent = 'Paste at least one resume or upload a PDF first.';
        return;
    }

    const formData = new FormData();
    texts.forEach(t => formData.append('texts', t));
    files.forEach(f => formData.append('files', f));

    btn.textContent = 'Extracting...';
    btn.disabled = true;
    statusEl.className = '';
    statusEl.textContent = '';

    try {
        const res = await apiFetch('/master-resume/import', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(formatApiError(data, 'Import failed'));

        statusEl.className = 'success';
        statusEl.textContent = data.message;

        // Either way, the form now shows the freshly-extracted data and
        // the import inputs reset - so it's obvious something happened,
        // rather than a status line appearing above an unchanged screen.
        if (data.auto_saved) {
            await loadMasterResume();
        } else {
            renderMasterResumeForm(data.data);
        }
        document.getElementById('masterResumeForm').scrollIntoView({ behavior: 'smooth' });
        resetImportInputs();
    } catch (error) {
        statusEl.className = 'error';
        statusEl.textContent = `Error: ${error.message}`;
    } finally {
        btn.textContent = 'Auto-fill Master Resume';
        btn.disabled = false;
    }
});

export async function loadMasterResume() {
    const form = document.getElementById('masterResumeForm');
    form.innerHTML = 'Loading...';
    try {
        const res = await apiFetch('/master-resume');
        const resume = await res.json();
        renderMasterResumeForm(resume);
        loadVersions();
    } catch (error) {
        form.innerHTML = `Error loading master resume: ${error.message}`;
    }
}

function renderMasterResumeForm(resume) {
    const form = document.getElementById('masterResumeForm');
    renderResumeFields(form, resume);

    const saveBtn = document.createElement('button');
    saveBtn.type = 'submit';
    saveBtn.textContent = 'Save New Version';
    form.appendChild(saveBtn);
}

document.getElementById('masterResumeForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const statusEl = document.getElementById('editStatus');
    const resume = collectResumeFields(form);

    try {
        const res = await apiFetch('/master-resume', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(resume),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(formatApiError(data, 'Save failed'));
        statusEl.className = 'success';
        statusEl.textContent = 'Saved as a new version.';
        loadVersions();
    } catch (error) {
        statusEl.className = 'error';
        statusEl.textContent = `Error: ${error.message}`;
    }
});

async function loadVersions() {
    const el = document.getElementById('versionList');
    el.textContent = 'Loading...';
    try {
        const res = await apiFetch('/master-resume/versions');
        const versions = await res.json();
        el.innerHTML = '';
        for (const v of versions) {
            const row = document.createElement('div');
            row.className = 'version-item';

            const label = document.createElement('span');
            label.textContent = new Date(v.created_at).toLocaleString() + (v.is_current ? ' (current)' : '');
            row.appendChild(label);

            if (!v.is_current) {
                const restoreBtn = document.createElement('button');
                restoreBtn.type = 'button';
                restoreBtn.className = 'secondary';
                restoreBtn.textContent = 'Restore';
                restoreBtn.addEventListener('click', () => restoreVersion(v.id));
                row.appendChild(restoreBtn);
            }

            el.appendChild(row);
        }
    } catch (error) {
        el.textContent = `Error loading versions: ${error.message}`;
    }
}

async function restoreVersion(id) {
    const statusEl = document.getElementById('editStatus');
    try {
        const res = await apiFetch(`/master-resume/versions/${id}/restore`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(formatApiError(data, 'Restore failed'));
        statusEl.className = 'success';
        statusEl.textContent = 'Restored - now the current version.';
        loadMasterResume();
    } catch (error) {
        statusEl.className = 'error';
        statusEl.textContent = `Error: ${error.message}`;
    }
}
