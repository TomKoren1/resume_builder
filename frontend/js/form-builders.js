// ---------- Shared resume-form building blocks ----------
// Used by both the master-resume editor and the per-history-entry editor -
// same underlying schema (see backend/schemas.py's MasterResume), just
// different save endpoints and, for history entries, section order/
// visibility controls layered on top (see history-editor.js).

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

// A dynamic list of full-size textareas (one per pasted old resume) -
// same add/remove convention as makeListEditor above, just card-wrapped
// since these hold multi-line text rather than a single value.
export function makeTextBlockList(initialCount) {
    const wrap = document.createElement('div');

    function addBlock() {
        const card = document.createElement('div');
        card.className = 'card';
        const header = document.createElement('div');
        header.className = 'card-header';
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '×';
        removeBtn.title = 'Remove';
        removeBtn.addEventListener('click', () => card.remove());
        header.appendChild(removeBtn);
        const textarea = document.createElement('textarea');
        textarea.placeholder = 'Paste an old resume here...';
        card.appendChild(header);
        card.appendChild(textarea);
        wrap.appendChild(card);
    }

    for (let i = 0; i < (initialCount || 1); i++) addBlock();
    wrap._addBlock = addBlock;
    return wrap;
}

export function slugifyCustomId(title, index) {
    const slug = (title || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
    return 'custom-' + (slug || ('section-' + index));
}

// User-defined sections beyond the fixed set (Volunteer Work, Publications,
// etc.) - each one is either a bulleted list (reuses makeListEditor) or a
// free-text block, picked per-section via a type <select>. id is derived
// from the title (slugifyCustomId) rather than stored/tracked separately,
// so it stays stable across repeated saves as long as the title doesn't
// change - see backend/schemas.py's CustomSection and app/render_resume.py
// for how that id then drives section_order/hidden_sections.
function makeCustomSectionsEditor(container, sections) {
    container.innerHTML = '';

    function addCard(sec) {
        const data = sec || { title: '', type: 'bullets', items: [], text: '' };
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

        const { group: titleGroup, input: titleInput } = makeTextField('Section Title', data.title);
        titleInput.dataset.fieldKey = 'title';
        // A blank title has nothing to show as a heading and nothing for
        // section_order to reference, so collectCustomSections() drops it
        // silently on save - required forces the browser to block
        // submission and point at the empty field instead of losing it
        // with no explanation.
        titleInput.required = true;
        titleInput.placeholder = 'e.g. Volunteer Work';
        card.appendChild(titleGroup);

        const typeLabel = document.createElement('label');
        typeLabel.textContent = 'Type';
        card.appendChild(typeLabel);
        const typeSelect = document.createElement('select');
        typeSelect.dataset.fieldKey = 'type';
        [['bullets', 'Bulleted list'], ['text', 'Free text']].forEach(([value, label]) => {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = label;
            if (value === data.type) opt.selected = true;
            typeSelect.appendChild(opt);
        });
        card.appendChild(typeSelect);

        const itemsLabel = document.createElement('label');
        itemsLabel.textContent = 'Items';
        const itemsEditor = makeListEditor(data.items);
        itemsEditor.dataset.fieldKey = 'items';
        card.appendChild(itemsLabel);
        card.appendChild(itemsEditor);

        const textLabel = document.createElement('label');
        textLabel.textContent = 'Text';
        const textArea = document.createElement('textarea');
        textArea.dataset.fieldKey = 'text';
        textArea.value = data.text || '';
        textArea.style.height = '90px';
        card.appendChild(textLabel);
        card.appendChild(textArea);

        function syncVisibility() {
            const isBullets = typeSelect.value === 'bullets';
            itemsLabel.hidden = !isBullets;
            itemsEditor.hidden = !isBullets;
            textLabel.hidden = isBullets;
            textArea.hidden = isBullets;
        }
        typeSelect.addEventListener('change', syncVisibility);
        syncVisibility();

        // Always insert right before the (already-appended) add button,
        // never container.lastElementChild directly - during the initial
        // forEach below, the first card's insertBefore(card, null) is a
        // no-op append, but every card after that would land BEFORE the
        // previous one (lastElementChild was the last-inserted card, not
        // the end of the list), silently rotating the display order on
        // every reload for anyone with 2+ custom sections.
        container.insertBefore(card, addBtn);
    }

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'add-btn';
    addBtn.textContent = '+ Add Custom Section';
    addBtn.addEventListener('click', () => addCard(null));
    container.appendChild(addBtn);

    (sections || []).forEach(addCard);
}

function collectCustomSections(container) {
    return Array.from(container.querySelectorAll(':scope > .card')).map((card, i) => {
        const title = card.querySelector('[data-field-key="title"]').value.trim();
        return {
            id: slugifyCustomId(title, i),
            title,
            type: card.querySelector('[data-field-key="type"]').value,
            items: collectListEditor(card.querySelector('[data-field-key="items"]')),
            text: card.querySelector('[data-field-key="text"]').value.trim(),
        };
    }).filter(s => s.title); // an unnamed section can't be shown/targeted - drop it rather than save junk
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
export function renderResumeFields(container, resume) {
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

    const customBlock = renderSectionHeader(container, 'Custom Sections');
    const customContainer = document.createElement('div');
    customBlock.appendChild(customContainer);
    makeCustomSectionsEditor(customContainer, resume.custom_sections);
    container._customContainer = customContainer;
}

export function collectResumeFields(container) {
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
        custom_sections: collectCustomSections(container._customContainer),
    };
}
