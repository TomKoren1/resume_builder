// ---------- Tab switching ----------
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('view-' + btn.dataset.view).classList.add('active');
        if (btn.dataset.view === 'history') loadHistory();
        if (btn.dataset.view === 'edit') loadMasterResume();
    });
});

// ---------- Generate ----------
document.getElementById('resumeForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const btn = e.target.querySelector('button');
    const responseDiv = document.getElementById('response');
    const jobDesc = document.getElementById('jobDescription').value;

    btn.textContent = 'Generating...';
    btn.disabled = true;
    responseDiv.style.display = 'block';
    responseDiv.textContent = 'Contacting AWS Bedrock...';

    try {
        const res = await fetch('/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_description: jobDesc })
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
        const res = await fetch('/history');
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

            row.appendChild(meta);
            row.appendChild(right);
            el.appendChild(row);
        }
    } catch (error) {
        el.textContent = `Error loading history: ${error.message}`;
    }
}

// ---------- Edit Master Resume ----------

// Schema for the repeatable "card" sections: plain text fields + list
// (bullet/notes) sub-fields. Drives both rendering and collection so each
// section doesn't need its own bespoke add/remove logic.
const CARD_SCHEMAS = {
    experience: {
        fields: [
            { key: 'company', label: 'Company' },
            { key: 'role', label: 'Role' },
            { key: 'start_date', label: 'Start date' },
            { key: 'end_date', label: 'End date' },
            { key: 'location', label: 'Location' },
        ],
        listFields: [{ key: 'bullets', label: 'Bullets' }],
        emptyItem: { company: '', role: '', start_date: '', end_date: '', location: '', bullets: [] },
    },
    projects: {
        fields: [
            { key: 'name', label: 'Name' },
            { key: 'url', label: 'URL' },
        ],
        listFields: [{ key: 'bullets', label: 'Bullets' }],
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

function makeListEditor(items) {
    const wrap = document.createElement('div');
    wrap.className = 'list-editor';

    function addRow(value) {
        const row = document.createElement('div');
        row.className = 'list-item-row';
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'list-item';
        input.value = value || '';
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', () => row.remove());
        row.appendChild(input);
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
            const editor = makeListEditor(itemData[lf.key]);
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

function renderSectionHeader(form, title) {
    const block = document.createElement('div');
    block.className = 'section-block';
    const h4 = document.createElement('h4');
    h4.textContent = title;
    block.appendChild(h4);
    form.appendChild(block);
    return block;
}

async function loadMasterResume() {
    const form = document.getElementById('masterResumeForm');
    form.innerHTML = 'Loading...';
    try {
        const res = await fetch('/master-resume');
        const resume = await res.json();
        renderMasterResumeForm(resume);
        loadVersions();
    } catch (error) {
        form.innerHTML = `Error loading master resume: ${error.message}`;
    }
}

function renderMasterResumeForm(resume) {
    const form = document.getElementById('masterResumeForm');
    form.innerHTML = '';

    const basics = renderSectionHeader(form, 'Basics');
    const nameField = makeTextField('Name', resume.name);
    const titleField = makeTextField('Title', resume.title);
    const row = document.createElement('div');
    row.className = 'field-row';
    row.appendChild(nameField.group);
    row.appendChild(titleField.group);
    basics.appendChild(row);
    form._nameInput = nameField.input;
    form._titleInput = titleField.input;

    const contactBlock = renderSectionHeader(form, 'Contact');
    const contact = resume.contact || {};
    const contactFields = {};
    ['email', 'phone', 'location', 'linkedin', 'github'].forEach(key => {
        const { group, input } = makeTextField(key[0].toUpperCase() + key.slice(1), contact[key]);
        contactFields[key] = input;
        contactBlock.appendChild(group);
    });
    form._contactFields = contactFields;

    const summaryBlock = renderSectionHeader(form, 'Summary');
    const summaryLabel = document.createElement('label');
    summaryLabel.textContent = 'Summary (use **word** to bold)';
    const summaryTextarea = document.createElement('textarea');
    summaryTextarea.value = resume.summary || '';
    summaryTextarea.style.height = '110px';
    summaryBlock.appendChild(summaryLabel);
    summaryBlock.appendChild(summaryTextarea);
    form._summaryInput = summaryTextarea;

    const skillsBlock = renderSectionHeader(form, 'Skills (one "Category: item, item" line each)');
    const skillsEditor = makeListEditor(resume.skills);
    skillsBlock.appendChild(skillsEditor);
    form._skillsEditor = skillsEditor;

    const langBlock = renderSectionHeader(form, 'Languages');
    const langEditor = makeListEditor(resume.languages);
    langBlock.appendChild(langEditor);
    form._langEditor = langEditor;

    const expBlock = renderSectionHeader(form, 'Experience');
    const expContainer = document.createElement('div');
    expBlock.appendChild(expContainer);
    makeCardList(expContainer, resume.experience, CARD_SCHEMAS.experience, 'Experience');
    form._expContainer = expContainer;

    const projBlock = renderSectionHeader(form, 'Projects');
    const projContainer = document.createElement('div');
    projBlock.appendChild(projContainer);
    makeCardList(projContainer, resume.projects, CARD_SCHEMAS.projects, 'Project');
    form._projContainer = projContainer;

    const eduBlock = renderSectionHeader(form, 'Education');
    const eduContainer = document.createElement('div');
    eduBlock.appendChild(eduContainer);
    makeCardList(eduContainer, resume.education, CARD_SCHEMAS.education, 'Education');
    form._eduContainer = eduContainer;

    const certBlock = renderSectionHeader(form, 'Certifications');
    const certEditor = makeListEditor(resume.certifications);
    certBlock.appendChild(certEditor);
    form._certEditor = certEditor;

    const saveBtn = document.createElement('button');
    saveBtn.type = 'submit';
    saveBtn.textContent = 'Save New Version';
    form.appendChild(saveBtn);
}

document.getElementById('masterResumeForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const statusEl = document.getElementById('editStatus');

    const resume = {
        name: form._nameInput.value.trim(),
        title: form._titleInput.value.trim(),
        contact: Object.fromEntries(
            Object.entries(form._contactFields).map(([k, input]) => [k, input.value.trim()])
        ),
        summary: form._summaryInput.value.trim(),
        skills: collectListEditor(form._skillsEditor),
        languages: collectListEditor(form._langEditor),
        experience: collectCardList(form._expContainer, CARD_SCHEMAS.experience),
        projects: collectCardList(form._projContainer, CARD_SCHEMAS.projects),
        education: collectCardList(form._eduContainer, CARD_SCHEMAS.education),
        certifications: collectListEditor(form._certEditor),
    };

    try {
        const res = await fetch('/master-resume', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(resume),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Save failed');
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
        const res = await fetch('/master-resume/versions');
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
        const res = await fetch(`/master-resume/versions/${id}/restore`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Restore failed');
        statusEl.className = 'success';
        statusEl.textContent = 'Restored - now the current version.';
        loadMasterResume();
    } catch (error) {
        statusEl.className = 'error';
        statusEl.textContent = `Error: ${error.message}`;
    }
}
