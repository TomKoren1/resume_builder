// FastAPI returns `detail` as a plain string for hand-raised HTTPExceptions,
// but as an array of {loc, msg} field errors for Pydantic 422 validation
// failures - normalize both into one readable string.
function formatApiError(data, fallback) {
    const detail = data && data.detail;
    if (!detail) return fallback;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        return detail.map(e => {
            const field = Array.isArray(e.loc) ? e.loc.slice(1).join('.') : '';
            return field ? `${field}: ${e.msg}` : e.msg;
        }).join('; ');
    }
    return fallback;
}

function showView(viewName) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const tabBtn = document.querySelector(`.tab-btn[data-view="${viewName}"]`);
    if (tabBtn) tabBtn.classList.add('active');
    document.getElementById('view-' + viewName).classList.add('active');
}

// Wraps fetch() with the one thing every backend call needs now: sending
// the session cookie (httpOnly, so JS can't read/attach it manually) and
// bouncing to the login view on a 401 instead of every call site having
// to check for that itself. Drop-in replacement for fetch() - still
// returns the Response, callers still do their own res.json()/res.ok.
async function apiFetch(url, opts = {}) {
    const res = await fetch(url, { ...opts, credentials: 'include' });
    if (res.status === 401) {
        showView('login');
        throw new Error('Not logged in.');
    }
    return res;
}

// ---------- Tab switching ----------
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        showView(btn.dataset.view);
        if (btn.dataset.view === 'history') loadHistory();
        if (btn.dataset.view === 'edit') loadMasterResume();
        if (btn.dataset.view === 'account') loadAccount();
    });
});

// ---------- Session check (app init) ----------
// Gates the whole app behind login: on load, ask the backend who (if
// anyone) is signed in. A 401 here throws inside apiFetch and lands in
// the catch below - showView('login') already ran by the time we get
// there, so this is just "don't also try to render the generate view".
(async () => {
    try {
        const res = await apiFetch('/auth/me');
        await res.json();
    } catch (e) {
        // Already on the login view via apiFetch's 401 handling.
    }
})();

// ---------- Generate ----------
document.getElementById('resumeForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const btn = e.target.querySelector('button');
    const responseDiv = document.getElementById('response');
    const jobDesc = document.getElementById('jobDescription').value;
    const theme = document.getElementById('themeSelect').value;

    btn.textContent = 'Generating...';
    btn.disabled = true;
    responseDiv.style.display = 'block';
    responseDiv.textContent = 'Contacting AWS Bedrock...';

    try {
        const res = await apiFetch('/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_description: jobDesc, theme })
        });

        const data = await res.json();
        responseDiv.textContent = data.message || JSON.stringify(data, null, 2);

        if (data.download_url) {
            const link = document.createElement('a');
            link.href = data.download_url;
            link.textContent = 'Download PDF';
            responseDiv.appendChild(link);
        }
    } catch (error) {
        responseDiv.textContent = `Error: ${error.message}`;
    } finally {
        btn.textContent = 'Generate Resume';
        btn.disabled = false;
    }
});

// ---------- History ----------
async function loadHistory() {
    const el = document.getElementById('historyList');
    el.textContent = 'Loading...';
    try {
        const res = await apiFetch('/history');
        const items = await res.json();
        if (!items.length) {
            el.textContent = 'No resumes generated yet.';
            return;
        }
        el.innerHTML = '';
        for (const item of items) {
            const row = document.createElement('div');
            row.className = 'history-item';

            const meta = document.createElement('div');
            meta.className = 'history-meta';
            const date = document.createElement('div');
            date.className = 'history-date';
            date.textContent = new Date(item.created_at).toLocaleString();
            const job = document.createElement('div');
            job.className = 'history-job';
            job.textContent = item.job_description;
            meta.appendChild(date);
            meta.appendChild(job);
            if (item.status === 'error' && item.error_message) {
                const err = document.createElement('div');
                err.className = 'history-date';
                err.style.color = 'var(--error)';
                err.textContent = item.error_message;
                meta.appendChild(err);
            }

            const right = document.createElement('div');
            right.style.textAlign = 'right';
            const badge = document.createElement('span');
            badge.className = 'badge ' + (item.status === 'success' ? 'success' : 'error');
            badge.textContent = item.status;
            right.appendChild(badge);
            if (item.has_pdf) {
                right.appendChild(document.createElement('br'));
                const link = document.createElement('a');
                link.href = `/history/${item.id}/download`;
                link.textContent = 'Download PDF';
                right.appendChild(link);
            }
            if (item.status === 'success') {
                right.appendChild(document.createElement('br'));
                const editBtn = document.createElement('button');
                editBtn.type = 'button';
                editBtn.className = 'secondary';
                editBtn.textContent = 'Edit';
                editBtn.addEventListener('click', () => openHistoryEditor(item.id));
                right.appendChild(editBtn);
            }

            row.appendChild(meta);
            row.appendChild(right);
            el.appendChild(row);
        }
    } catch (error) {
        el.textContent = `Error loading history: ${error.message}`;
    }
}

// ---------- Account ----------
async function loadAccount() {
    const infoEl = document.getElementById('accountInfo');
    infoEl.textContent = 'Loading...';
    try {
        const res = await apiFetch('/auth/me');
        const user = await res.json();
        infoEl.innerHTML = '';
        const name = document.createElement('p');
        name.textContent = user.display_name || user.email || `User #${user.id}`;
        const email = document.createElement('p');
        email.className = 'hint';
        email.textContent = user.email || '';
        infoEl.appendChild(name);
        infoEl.appendChild(email);

        const apiKeyInput = document.getElementById('apiKeyInput');
        apiKeyInput.value = '';
        apiKeyInput.placeholder = user.has_api_key ? 'Key saved - enter a new one to replace it' : 'sk-ant-...';
        document.getElementById('removeApiKeyBtn').disabled = !user.has_api_key;
    } catch (error) {
        infoEl.textContent = `Error loading account: ${error.message}`;
    }
}

function setAccountStatus(message, isError) {
    const statusEl = document.getElementById('accountStatus');
    statusEl.textContent = message;
    statusEl.className = isError ? 'error' : 'success';
}

document.getElementById('saveApiKeyBtn').addEventListener('click', async () => {
    const input = document.getElementById('apiKeyInput');
    const key = input.value.trim();
    if (!key) {
        setAccountStatus('Enter an API key first.', true);
        return;
    }
    try {
        const res = await apiFetch('/auth/api-key', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ anthropic_api_key: key }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(formatApiError(data, 'Failed to save key.'));
        setAccountStatus(`Saved (${data.masked}).`, false);
        loadAccount();
    } catch (error) {
        setAccountStatus(`Error: ${error.message}`, true);
    }
});

document.getElementById('removeApiKeyBtn').addEventListener('click', async () => {
    try {
        await apiFetch('/auth/api-key', { method: 'DELETE' });
        setAccountStatus('Key removed.', false);
        loadAccount();
    } catch (error) {
        setAccountStatus(`Error: ${error.message}`, true);
    }
});

document.getElementById('logoutBtn').addEventListener('click', async () => {
    await apiFetch('/auth/logout', { method: 'POST' });
    location.reload();
});

// ---------- Shared resume-form building blocks ----------
// Used by both the master-resume editor and the per-history-entry editor -
// same underlying schema (see backend/schemas.py's MasterResume), just
// different save endpoints and, for history entries, section order/
// visibility controls layered on top.

// Wraps/unwraps the current text-field selection in **markdown** (or
// removes it, if the selection is already wrapped) - a real bold toggle
// without needing a full rich-text editor. Storage format is unchanged:
// still plain **word** markdown, same as render_resume.py's highlight_text
// already parses.
function toggleBoldSelection(el) {
    const start = el.selectionStart;
    const end = el.selectionEnd;
    if (start === end) return; // nothing selected
    const value = el.value;
    const before = value.slice(0, start);
    const selected = value.slice(start, end);
    const after = value.slice(end);
    const alreadyBold = before.endsWith('**') && after.startsWith('**');
    let newValue, newStart, newEnd;
    if (alreadyBold) {
        newValue = before.slice(0, -2) + selected + after.slice(2);
        newStart = start - 2;
        newEnd = end - 2;
    } else {
        newValue = before + '**' + selected + '**' + after;
        newStart = start + 2;
        newEnd = end + 2;
    }
    el.value = newValue;
    el.focus();
    el.setSelectionRange(newStart, newEnd);
}

function makeBoldButton(targetEl) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'bold-btn';
    btn.textContent = 'B';
    btn.title = 'Bold the selected text';
    btn.addEventListener('click', () => toggleBoldSelection(targetEl));
    return btn;
}

// Schema for the repeatable "card" sections: plain text fields + list
// (bullet/notes) sub-fields. Drives both rendering and collection so each
// section doesn't need its own bespoke add/remove logic. `boldable` on a
// listField adds the bold toggle - only bullets go through highlight_text()
// server-side (see app/render_resume.py), so only bullets get it here.
const CARD_SCHEMAS = {
    experience: {
        fields: [
            { key: 'company', label: 'Company' },
            { key: 'role', label: 'Role' },
            { key: 'start_date', label: 'Start date' },
            { key: 'end_date', label: 'End date' },
            { key: 'location', label: 'Location' },
        ],
        listFields: [{ key: 'bullets', label: 'Bullets', boldable: true }],
        emptyItem: { company: '', role: '', start_date: '', end_date: '', location: '', bullets: [] },
    },
    projects: {
        fields: [
            { key: 'name', label: 'Name' },
            { key: 'url', label: 'URL' },
        ],
        listFields: [{ key: 'bullets', label: 'Bullets', boldable: true }],
        emptyItem: { name: '', url: '', bullets: [] },
    },
    education: {
        fields: [
            { key: 'school', label: 'School' },
            { key: 'degree', label: 'Degree' },
            { key: 'start_date', label: 'Start date' },
            { key: 'end_date', label: 'End date' },
        ],
        listFields: [{ key: 'notes', label: 'Notes' }],
        emptyItem: { school: '', degree: '', start_date: '', end_date: '', notes: [] },
    },
};

function makeListEditor(items, options) {
    const opts = options || {};
    const wrap = document.createElement('div');
    wrap.className = 'list-editor';

    function addRow(value) {
        const row = document.createElement('div');
        row.className = 'list-item-row';
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'list-item';
        input.value = value || '';
        row.appendChild(input);
        if (opts.boldable) row.appendChild(makeBoldButton(input));
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', () => row.remove());
        row.appendChild(removeBtn);
        wrap.insertBefore(row, wrap.lastElementChild);
    }

    (items || []).forEach(addRow);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'add-btn';
    addBtn.textContent = '+ Add';
    addBtn.addEventListener('click', () => addRow(''));
    wrap.appendChild(addBtn);

    return wrap;
}

function collectListEditor(wrap) {
    return Array.from(wrap.querySelectorAll(':scope > .list-item-row > input.list-item'))
        .map(i => i.value.trim())
        .filter(v => v.length > 0);
}

function makeTextField(labelText, value) {
    const label = document.createElement('label');
    label.textContent = labelText;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'field';
    input.dataset.field = labelText;
    input.value = value || '';
    const group = document.createElement('div');
    group.appendChild(label);
    group.appendChild(input);
    return { group, input };
}

function makeCardList(container, items, schema, entryLabel) {
    container.innerHTML = '';

    function addCard(itemData) {
        const card = document.createElement('div');
        card.className = 'card';

        const header = document.createElement('div');
        header.className = 'card-header';
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', () => card.remove());
        header.appendChild(removeBtn);
        card.appendChild(header);

        schema.fields.forEach(f => {
            const { group, input } = makeTextField(f.label, itemData[f.key]);
            input.dataset.fieldKey = f.key;
            card.appendChild(group);
        });

        schema.listFields.forEach(lf => {
            const label = document.createElement('label');
            label.textContent = lf.label;
            card.appendChild(label);
            const editor = makeListEditor(itemData[lf.key], { boldable: lf.boldable });
            editor.dataset.fieldKey = lf.key;
            card.appendChild(editor);
        });

        container.insertBefore(card, container.lastElementChild);
    }

    (items || []).forEach(addCard);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'add-btn';
    addBtn.textContent = '+ Add ' + entryLabel;
    addBtn.addEventListener('click', () => addCard({ ...schema.emptyItem }));
    container.appendChild(addBtn);
}

function collectCardList(container, schema) {
    return Array.from(container.querySelectorAll(':scope > .card')).map(card => {
        const obj = {};
        schema.fields.forEach(f => {
            const input = card.querySelector(`.field[data-field-key="${f.key}"]`);
            obj[f.key] = input ? input.value.trim() : '';
        });
        schema.listFields.forEach(lf => {
            const editor = card.querySelector(`.list-editor[data-field-key="${lf.key}"]`);
            obj[lf.key] = editor ? collectListEditor(editor) : [];
        });
        return obj;
    });
}

function renderSectionHeader(container, title) {
    const block = document.createElement('div');
    block.className = 'section-block';
    const h4 = document.createElement('h4');
    h4.textContent = title;
    block.appendChild(h4);
    container.appendChild(block);
    return block;
}

// Renders the full set of resume content fields into `container` (a <form>
// or plain <div>), storing element references as properties on it for
// collectResumeFields() to read back later. No submit button - callers add
// their own Save action(s).
function renderResumeFields(container, resume) {
    container.innerHTML = '';

    const basics = renderSectionHeader(container, 'Basics');
    const nameField = makeTextField('Name', resume.name);
    const titleField = makeTextField('Title', resume.title);
    const row = document.createElement('div');
    row.className = 'field-row';
    row.appendChild(nameField.group);
    row.appendChild(titleField.group);
    basics.appendChild(row);
    container._nameInput = nameField.input;
    container._titleInput = titleField.input;

    const contactBlock = renderSectionHeader(container, 'Contact');
    const contact = resume.contact || {};
    const contactFields = {};
    ['email', 'phone', 'location', 'linkedin', 'github'].forEach(key => {
        const { group, input } = makeTextField(key[0].toUpperCase() + key.slice(1), contact[key]);
        contactFields[key] = input;
        contactBlock.appendChild(group);
    });
    container._contactFields = contactFields;

    const summaryBlock = renderSectionHeader(container, 'Summary');
    const summaryLabel = document.createElement('label');
    summaryLabel.textContent = 'Summary';
    const summaryTextarea = document.createElement('textarea');
    summaryTextarea.value = resume.summary || '';
    summaryTextarea.style.height = '110px';
    summaryBlock.appendChild(summaryLabel);
    const summaryToolbar = document.createElement('div');
    summaryToolbar.className = 'field-toolbar';
    summaryToolbar.appendChild(makeBoldButton(summaryTextarea));
    summaryBlock.appendChild(summaryToolbar);
    summaryBlock.appendChild(summaryTextarea);
    container._summaryInput = summaryTextarea;

    const skillsBlock = renderSectionHeader(container, 'Skills (one "Category: item, item" line each)');
    const skillsEditor = makeListEditor(resume.skills);
    skillsBlock.appendChild(skillsEditor);
    container._skillsEditor = skillsEditor;

    const langBlock = renderSectionHeader(container, 'Languages');
    const langEditor = makeListEditor(resume.languages);
    langBlock.appendChild(langEditor);
    container._langEditor = langEditor;

    const expBlock = renderSectionHeader(container, 'Experience');
    const expContainer = document.createElement('div');
    expBlock.appendChild(expContainer);
    makeCardList(expContainer, resume.experience, CARD_SCHEMAS.experience, 'Experience');
    container._expContainer = expContainer;

    const projBlock = renderSectionHeader(container, 'Projects');
    const projContainer = document.createElement('div');
    projBlock.appendChild(projContainer);
    makeCardList(projContainer, resume.projects, CARD_SCHEMAS.projects, 'Project');
    container._projContainer = projContainer;

    const eduBlock = renderSectionHeader(container, 'Education');
    const eduContainer = document.createElement('div');
    eduBlock.appendChild(eduContainer);
    makeCardList(eduContainer, resume.education, CARD_SCHEMAS.education, 'Education');
    container._eduContainer = eduContainer;

    const certBlock = renderSectionHeader(container, 'Certifications');
    const certEditor = makeListEditor(resume.certifications);
    certBlock.appendChild(certEditor);
    container._certEditor = certEditor;
}

function collectResumeFields(container) {
    return {
        name: container._nameInput.value.trim(),
        title: container._titleInput.value.trim(),
        contact: Object.fromEntries(
            Object.entries(container._contactFields).map(([k, input]) => [k, input.value.trim()])
        ),
        summary: container._summaryInput.value.trim(),
        skills: collectListEditor(container._skillsEditor),
        languages: collectListEditor(container._langEditor),
        experience: collectCardList(container._expContainer, CARD_SCHEMAS.experience),
        projects: collectCardList(container._projContainer, CARD_SCHEMAS.projects),
        education: collectCardList(container._eduContainer, CARD_SCHEMAS.education),
        certifications: collectListEditor(container._certEditor),
    };
}

// ---------- Edit Master Resume ----------

async function loadMasterResume() {
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

// ---------- Edit a past generated resume (from History) ----------
// Canva-like click-to-edit: the iframe loads GET /history/{id}/preview,
// which is rendered through the *real* app/template.html - the exact same
// template Playwright prints to PDF - so what's edited here can never
// visually drift from the actual output. Specific elements in that HTML
// are contenteditable; add/remove controls are wired up from this file
// after the iframe loads (template.html itself stays script-free).

const SECTION_LABELS = {
    summary: 'Summary', experience: 'Experience', projects: 'Projects',
    certifications: 'Certifications', education: 'Education', skills: 'Skills', languages: 'Languages',
};
// Must match app/render_resume.py's DEFAULT_SECTION_ORDER.
const DEFAULT_SECTION_ORDER = ['summary', 'experience', 'projects', 'certifications', 'education', 'skills', 'languages'];

let currentHistoryEditId = null;
let currentSectionOrder = [];
let currentHiddenSections = new Set();
let currentOriginalResume = {};
let skillsEditorEl = null;

function getPreviewDoc() {
    const iframe = document.getElementById('historyPreviewFrame');
    return iframe && iframe.contentDocument;
}

// Reorders/hides the preview's actual [data-section] elements to match
// currentSectionOrder/currentHiddenSections - re-appending an existing
// child moves it rather than duplicating it, so processing sections in
// order leaves them in exactly that order. Safe to call before the iframe
// has finished loading (no-ops until there's a document to act on).
function applySectionOrderToPreview() {
    const doc = getPreviewDoc();
    if (!doc || !doc.body) return;
    currentSectionOrder.forEach(id => {
        const section = doc.querySelector(`[data-section="${id}"]`);
        if (!section) return; // wasn't rendered at all (e.g. originally empty list)
        doc.body.appendChild(section);
        section.hidden = currentHiddenSections.has(id);
    });
}

function renderSectionControls() {
    const el = document.getElementById('sectionControls');
    el.innerHTML = '';
    currentSectionOrder.forEach((id, idx) => {
        const row = document.createElement('div');
        row.className = 'section-control-row';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = !currentHiddenSections.has(id);
        checkbox.title = 'Show this section';
        checkbox.addEventListener('change', () => {
            if (checkbox.checked) currentHiddenSections.delete(id);
            else currentHiddenSections.add(id);
            applySectionOrderToPreview();
        });

        const label = document.createElement('span');
        label.textContent = SECTION_LABELS[id] || id;

        const upBtn = document.createElement('button');
        upBtn.type = 'button';
        upBtn.textContent = '↑';
        upBtn.disabled = idx === 0;
        upBtn.addEventListener('click', () => {
            [currentSectionOrder[idx - 1], currentSectionOrder[idx]] = [currentSectionOrder[idx], currentSectionOrder[idx - 1]];
            renderSectionControls();
            applySectionOrderToPreview();
        });

        const downBtn = document.createElement('button');
        downBtn.type = 'button';
        downBtn.textContent = '↓';
        downBtn.disabled = idx === currentSectionOrder.length - 1;
        downBtn.addEventListener('click', () => {
            [currentSectionOrder[idx + 1], currentSectionOrder[idx]] = [currentSectionOrder[idx], currentSectionOrder[idx + 1]];
            renderSectionControls();
            applySectionOrderToPreview();
        });

        row.appendChild(checkbox);
        row.appendChild(label);
        row.appendChild(upBtn);
        row.appendChild(downBtn);
        el.appendChild(row);
    });
}

function renderSkillsEditor(skills) {
    const container = document.getElementById('skillsEditorContainer');
    container.innerHTML = '';
    skillsEditorEl = makeListEditor(skills);
    container.appendChild(skillsEditorEl);
}

// ----- contenteditable bold toggle -----
// document.execCommand is deprecated but remains the only reliable
// cross-browser way to toggle bold *within* a contenteditable region -
// the alternative (manually splicing <strong> around a Range) is real
// complexity for what's a well-contained, single-purpose need here.
function wireBoldShortcut(doc) {
    doc.addEventListener('keydown', (e) => {
        const isMod = e.ctrlKey || e.metaKey;
        if (isMod && (e.key === 'b' || e.key === 'B')) {
            e.preventDefault();
            doc.execCommand('bold');
        }
    });
}

// Converts one editable element's rendered content back to the
// **bold** markdown string render_resume.py's highlight_text() already
// parses. <strong>/<b> -> **...**; <br> (e.g. from a paste) -> a space,
// since these fields are meant to stay single-line/flowing; any other
// wrapper tag a browser's contenteditable might introduce is stripped,
// keeping its text. Whitespace is collapsed and trimmed.
function htmlToMarkdown(el) {
    function walk(node) {
        if (node.nodeType === Node.TEXT_NODE) return node.textContent;
        if (node.nodeType !== Node.ELEMENT_NODE) return '';
        const tag = node.tagName.toLowerCase();
        if (tag === 'br') return ' ';
        const inner = Array.from(node.childNodes).map(walk).join('');
        if (tag === 'strong' || tag === 'b') return `**${inner}**`;
        return inner;
    }
    return Array.from(el.childNodes).map(walk).join('').replace(/\s+/g, ' ').trim();
}

// ----- add/remove controls -----
// Small DOM-building helpers mirroring template.html's structure for a
// freshly-added (empty) entry, kept in one place per entry type.
function dEl(doc, tag, attrs, children) {
    const node = doc.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
    (children || []).forEach(c => node.appendChild(c));
    return node;
}

function editableSpan(doc, field, text, extraClass) {
    const span = dEl(doc, 'span', { 'data-field': field, contenteditable: 'true' }, [doc.createTextNode(text || '')]);
    if (extraClass) span.className = extraClass;
    return span;
}

function removeBtnEl(doc, title) {
    const btn = dEl(doc, 'button', { type: 'button', class: 'editor-only remove-entry-btn', title: title || 'Remove' });
    btn.textContent = '×';
    return btn;
}

function bulletsListEl(doc) {
    return dEl(doc, 'ul', { class: 'bullets', 'data-list': 'bullets' });
}

function addBulletBtnEl(doc) {
    const btn = dEl(doc, 'button', { type: 'button', class: 'editor-only add-bullet-btn' });
    btn.textContent = '+ bullet';
    return btn;
}

function newExperienceEntry(doc) {
    const dateWrap = dEl(doc, 'div', { class: 'exp-date' }, [
        editableSpan(doc, 'start_date', ''),
        dEl(doc, 'span', { class: 'date-sep' }, [doc.createTextNode(' – ')]),
        editableSpan(doc, 'end_date', ''),
        dEl(doc, 'div', { class: 'exp-location', 'data-field': 'location', contenteditable: 'true' }),
    ]);
    const titleRow = dEl(doc, 'div', { class: 'exp-title' }, [
        editableSpan(doc, 'role', 'New Role'),
        dEl(doc, 'span', { class: 'company' }, [doc.createTextNode('| '), editableSpan(doc, 'company', 'Company')]),
        removeBtnEl(doc, 'Remove this entry'),
    ]);
    const right = dEl(doc, 'div', {}, [titleRow, bulletsListEl(doc), addBulletBtnEl(doc)]);
    return dEl(doc, 'div', { class: 'exp-row', 'data-entry': 'experience' }, [dateWrap, right]);
}

function newProjectEntry(doc) {
    const nameRow = dEl(doc, 'div', { class: 'project-name-row' }, [
        editableSpan(doc, 'name', 'New Project', 'project-name'),
        removeBtnEl(doc, 'Remove this entry'),
    ]);
    return dEl(doc, 'div', { class: 'project-entry', 'data-entry': 'project' }, [nameRow, bulletsListEl(doc), addBulletBtnEl(doc)]);
}

function newEducationEntry(doc) {
    return dEl(doc, 'li', { 'data-entry': 'education' }, [
        editableSpan(doc, 'degree', 'Degree', 'entry-title'),
        doc.createTextNode(' | '),
        editableSpan(doc, 'school', 'School'),
        doc.createTextNode(' '),
        dEl(doc, 'span', { class: 'entry-range' }, [
            doc.createTextNode('('),
            editableSpan(doc, 'start_date', ''),
            doc.createTextNode(' – '),
            editableSpan(doc, 'end_date', ''),
            doc.createTextNode(')'),
        ]),
        removeBtnEl(doc, 'Remove'),
        dEl(doc, 'span', { class: 'entry-notes', 'data-field': 'notes', contenteditable: 'true' }),
    ]);
}

function newCertificationEntry(doc) {
    return dEl(doc, 'li', { class: 'cert-row', 'data-entry': 'certification' }, [
        editableSpan(doc, 'text', 'New certification'),
        removeBtnEl(doc),
    ]);
}

function newLanguageEntry(doc) {
    return dEl(doc, 'li', { class: 'lang-row', 'data-entry': 'language' }, [
        editableSpan(doc, 'text', 'New language'),
        removeBtnEl(doc),
    ]);
}

const ADD_ENTRY_CONFIG = {
    experience: { listSelector: '[data-list="experience"]', factory: newExperienceEntry },
    project: { listSelector: '[data-list="projects"]', factory: newProjectEntry },
    education: { listSelector: '[data-list="education"]', factory: newEducationEntry },
    certification: { listSelector: '[data-list="certifications"]', factory: newCertificationEntry },
    language: { listSelector: '[data-list="languages"]', factory: newLanguageEntry },
};

// Event delegation on the iframe's document - one listener handles every
// add/remove button, including ones added after the fact, rather than
// re-wiring listeners each time an entry is added.
function wireEditorControls(doc) {
    doc.addEventListener('click', (e) => {
        const removeBtn = e.target.closest('.remove-entry-btn');
        if (removeBtn) {
            const entry = removeBtn.closest('[data-entry]');
            if (entry) entry.remove();
            return;
        }

        const addBulletBtn = e.target.closest('.add-bullet-btn');
        if (addBulletBtn) {
            const list = addBulletBtn.previousElementSibling;
            if (list && list.matches('[data-list="bullets"]')) {
                const li = dEl(doc, 'li', { 'data-entry': 'bullet' }, [
                    editableSpan(doc, 'bullet', ''),
                    removeBtnEl(doc, 'Remove bullet'),
                ]);
                list.appendChild(li);
                li.querySelector('[contenteditable]').focus();
            }
            return;
        }

        const addEntryBtn = e.target.closest('.add-entry-btn');
        if (addEntryBtn) {
            const config = ADD_ENTRY_CONFIG[addEntryBtn.dataset.addEntry];
            const list = config && doc.querySelector(config.listSelector);
            if (list) {
                const newEl = config.factory(doc);
                list.appendChild(newEl);
                const firstEditable = newEl.querySelector('[contenteditable]');
                if (firstEditable) firstEditable.focus();
            }
        }
    });
}

// ----- reading edits back out of the preview -----

function fieldText(root, field) {
    const el = root.querySelector(`[data-field="${field}"]`);
    return el ? el.textContent.trim() : '';
}

// DOM order *is* array order (same principle collectCardList() already
// uses for the master-resume form) - starts from a shallow copy of the
// matching original entry (by index) so fields with no visual/editable
// representation on the page (e.g. a project's `url`) survive a save
// unchanged instead of being silently dropped; a freshly-added entry has
// no original counterpart, so unrepresented fields just fall back to
// their Pydantic defaults.
function collectRepeatedEntries(doc, entrySelector, textFields, origArray) {
    return Array.from(doc.querySelectorAll(entrySelector)).map((entryEl, i) => {
        const base = { ...(origArray[i] || {}) };
        textFields.forEach(f => { base[f] = fieldText(entryEl, f); });
        const bulletsUl = entryEl.querySelector('[data-list="bullets"]');
        base.bullets = bulletsUl
            ? Array.from(bulletsUl.querySelectorAll('[data-field="bullet"]')).map(htmlToMarkdown).filter(Boolean)
            : [];
        return base;
    });
}

function collectEducation(doc, origArray) {
    return Array.from(doc.querySelectorAll('[data-entry="education"]')).map((entryEl, i) => {
        const base = { ...(origArray[i] || {}) };
        ['degree', 'school', 'start_date', 'end_date'].forEach(f => { base[f] = fieldText(entryEl, f); });
        const notesText = fieldText(entryEl, 'notes');
        base.notes = notesText ? notesText.split('·').map(s => s.trim()).filter(Boolean) : [];
        return base;
    });
}

function serializeIframeResume(doc, original) {
    // Scoped to <header> explicitly rather than querying data-field="name"
    // against the whole document - project entries have their own
    // data-field="name" span, and while header always precedes every
    // section today (so an unscoped query would happen to still resolve
    // correctly), that's an ordering invariant this shouldn't quietly
    // depend on.
    const headerEl = doc.querySelector('header') || doc;
    const name = fieldText(headerEl, 'name') || original.name;
    const title = fieldText(headerEl, 'title') || original.title;

    // linkedin/github aren't editable in-canvas (only their fixed "LinkedIn"/
    // "GitHub" label is visible - the real URL lives in href, which
    // contenteditable can't touch) - preserved from `original` untouched.
    const contact = { ...(original.contact || {}) };
    ['email', 'phone', 'location'].forEach(k => {
        const el = headerEl.querySelector(`[data-field="contact-${k}"]`);
        if (el) contact[k] = el.textContent.trim();
    });

    const summaryEl = doc.querySelector('[data-field="summary"]');
    const summary = summaryEl ? htmlToMarkdown(summaryEl) : (original.summary || '');

    const experience = collectRepeatedEntries(doc, '[data-entry="experience"]',
        ['role', 'company', 'start_date', 'end_date', 'location'], original.experience || []);
    const projects = collectRepeatedEntries(doc, '[data-entry="project"]',
        ['name'], original.projects || []);
    const education = collectEducation(doc, original.education || []);

    const certifications = Array.from(doc.querySelectorAll('[data-entry="certification"] [data-field="text"]'))
        .map(el => el.textContent.trim()).filter(Boolean);
    const languages = Array.from(doc.querySelectorAll('[data-entry="language"] [data-field="text"]'))
        .map(el => el.textContent.trim()).filter(Boolean);

    const section_titles = { ...(original.section_titles || {}) };
    DEFAULT_SECTION_ORDER.forEach(id => {
        const heading = doc.querySelector(`[data-section="${id}"] [data-field="section_title"]`);
        if (heading) section_titles[id] = heading.textContent.trim();
    });

    return { name, title, contact, summary, experience, projects, education, certifications, languages, section_titles };
}

async function openHistoryEditor(id) {
    showView('history-edit');
    const statusEl = document.getElementById('historyEditStatus');
    statusEl.className = '';
    statusEl.textContent = '';

    try {
        const res = await apiFetch(`/history/${id}`);
        const entry = await res.json();
        if (!res.ok) throw new Error(formatApiError(entry, 'Failed to load'));

        currentHistoryEditId = id;
        currentOriginalResume = entry.data || {};
        currentSectionOrder = (currentOriginalResume.section_order && currentOriginalResume.section_order.length)
            ? [...currentOriginalResume.section_order] : [...DEFAULT_SECTION_ORDER];
        currentHiddenSections = new Set(currentOriginalResume.hidden_sections || []);
        renderSectionControls();
        renderSkillsEditor(currentOriginalResume.skills || []);
        // The iframe's initial load already renders with this theme
        // (server-side, from the same stored data) - this just syncs the
        // dropdown to match what's already on screen.
        document.getElementById('historyThemeSelect').value = currentOriginalResume.theme || 'classic';

        const iframe = document.getElementById('historyPreviewFrame');
        iframe.onload = () => {
            wireBoldShortcut(iframe.contentDocument);
            wireEditorControls(iframe.contentDocument);
            applySectionOrderToPreview();
        };
        iframe.src = `/history/${id}/preview`;
    } catch (error) {
        statusEl.className = 'error';
        statusEl.textContent = `Error: ${error.message}`;
    }
}

document.getElementById('historyThemeSelect').addEventListener('change', (e) => {
    const doc = getPreviewDoc();
    if (doc && doc.body) doc.body.className = 'theme-' + e.target.value;
});

document.getElementById('backToHistoryBtn').addEventListener('click', () => {
    showView('history');
    loadHistory();
});

async function saveHistoryEdit(asNew) {
    const doc = getPreviewDoc();
    const statusEl = document.getElementById('historyEditStatus');
    if (!doc || !doc.body) {
        statusEl.className = 'error';
        statusEl.textContent = 'Preview is still loading - try again in a moment.';
        return;
    }

    const resume = serializeIframeResume(doc, currentOriginalResume);
    resume.skills = collectListEditor(skillsEditorEl);
    resume.section_order = currentSectionOrder;
    resume.hidden_sections = Array.from(currentHiddenSections);
    resume.theme = document.getElementById('historyThemeSelect').value;

    const url = asNew ? `/history/${currentHistoryEditId}/save-as` : `/history/${currentHistoryEditId}`;
    const method = asNew ? 'POST' : 'PUT';

    try {
        const res = await apiFetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(resume),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(formatApiError(data, 'Save failed'));

        statusEl.className = 'success';
        statusEl.textContent = (data.message || 'Saved.') + ' ';
        if (data.download_url) {
            const link = document.createElement('a');
            link.href = data.download_url;
            link.textContent = 'Download PDF';
            statusEl.appendChild(link);
        }
        if (asNew && data.history_id) currentHistoryEditId = data.history_id;
    } catch (error) {
        statusEl.className = 'error';
        statusEl.textContent = `Error: ${error.message}`;
    }
}

document.getElementById('saveHistoryBtn').addEventListener('click', () => saveHistoryEdit(false));
document.getElementById('saveAsHistoryBtn').addEventListener('click', () => saveHistoryEdit(true));
