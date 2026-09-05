import { apiFetch, formatApiError, showView, resizeImageToDataUrl } from './utils.js';
import { slugifyCustomId } from './form-builders.js';
// Circular with history.js (which imports openHistoryEditor from here) -
// safe because both sides only call the other's export from inside an
// event listener, never at module-evaluation time, so by the time either
// runs, both modules have already finished initializing.
import { loadHistory } from './history.js';

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
let currentPhoto = '';

// The <img class="profile-photo"> only exists in the DOM at all when a
// photo is set (template.html wraps it in {% if photo %}) - avoids a
// broken-image icon showing up in the actual PDF for photo-less resumes.
// So adding/removing a photo here means inserting/removing the element,
// not just updating a src that may not exist yet.
function applyPhotoToPreview(doc, dataUrl) {
    if (!doc || !doc.body) return;
    const header = doc.querySelector('header');
    if (!header) return;
    let img = header.querySelector('.profile-photo');
    if (dataUrl) {
        if (!img) {
            img = doc.createElement('img');
            img.className = 'profile-photo';
            img.alt = '';
            header.insertBefore(img, header.firstChild);
        }
        img.src = dataUrl;
    } else if (img) {
        img.remove();
    }
}

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
        // Custom sections aren't in the fixed SECTION_LABELS map - fall
        // back to whatever title was last saved on the master resume.
        const customSection = (currentOriginalResume.custom_sections || []).find(cs => cs.id === id);
        label.textContent = SECTION_LABELS[id] || (customSection && customSection.title) || id;

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

function newSkillEntry(doc) {
    return dEl(doc, 'li', { class: 'skill-row', 'data-entry': 'skill' }, [
        editableSpan(doc, 'text', 'New skill'),
        removeBtnEl(doc),
    ]);
}

function newCustomItemEntry(doc) {
    return dEl(doc, 'li', { 'data-entry': 'custom-item' }, [
        editableSpan(doc, 'text', 'New item'),
        removeBtnEl(doc),
    ]);
}

// Mirrors app/template.html's section_heading macro exactly (the ".bar"
// wrapper + contenteditable <h2 data-field="section_title">) - serializeIframeResume
// below reads section_titles/custom section titles back out via that
// same selector, so a freshly-added section needs the identical shape,
// not just visually similar markup.
function sectionHeadingEl(doc, title) {
    const h2 = dEl(doc, 'h2', { 'data-field': 'section_title', contenteditable: 'true' });
    h2.textContent = title;
    return dEl(doc, 'div', { class: 'bar' }, [h2]);
}

// Mirrors app/template.html's section_custom macro - a brand-new section
// added here (as opposed to one the server already rendered) needs the
// exact same DOM shape wireEditorControls()/serializeIframeResume() and
// the real PDF render both expect, or it would look right on screen but
// silently fail to save or print correctly.
function newCustomSectionEl(doc, section) {
    const children = [sectionHeadingEl(doc, section.title)];
    if (section.type === 'text') {
        const p = dEl(doc, 'p', { class: 'profile-text', 'data-field': 'custom_text', contenteditable: 'true' });
        p.textContent = section.text || '';
        children.push(p);
    } else {
        children.push(dEl(doc, 'ul', { class: 'line-list', 'data-list': `custom-${section.id}` }));
        const addBtn = dEl(doc, 'button', { type: 'button', class: 'editor-only add-entry-btn', 'data-add-entry': `custom-${section.id}` });
        addBtn.textContent = '+ Item';
        children.push(addBtn);
    }
    // Starts empty, so mark it .section-empty like the server does for any
    // empty section - only hides it from the printed PDF (@media print in
    // template.html), stays visible here in the editor.
    return dEl(doc, 'section', { 'data-section': section.id, 'data-custom-type': section.type, class: 'section-empty' }, children);
}

const ADD_ENTRY_CONFIG = {
    experience: { listSelector: '[data-list="experience"]', factory: newExperienceEntry },
    project: { listSelector: '[data-list="projects"]', factory: newProjectEntry },
    education: { listSelector: '[data-list="education"]', factory: newEducationEntry },
    certification: { listSelector: '[data-list="certifications"]', factory: newCertificationEntry },
    language: { listSelector: '[data-list="languages"]', factory: newLanguageEntry },
    skill: { listSelector: '[data-list="skills"]', factory: newSkillEntry },
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
            const key = addEntryBtn.dataset.addEntry;
            // Custom sections have a dynamic id (data-add-entry="custom-<id>"),
            // so they can't be pre-registered in the static config above -
            // the list selector is directly derivable from that same value.
            const config = key.startsWith('custom-')
                ? { listSelector: `[data-list="${key}"]`, factory: newCustomItemEntry }
                : ADD_ENTRY_CONFIG[key];
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
    // Unlike certifications/languages, skills already supports **bold**
    // (highlight_text() is applied to skills_flat server-side) - use
    // htmlToMarkdown so an edit made here round-trips that formatting
    // instead of flattening it to plain text.
    const skills = Array.from(doc.querySelectorAll('[data-entry="skill"] [data-field="text"]'))
        .map(htmlToMarkdown).filter(Boolean);

    const section_titles = { ...(original.section_titles || {}) };
    DEFAULT_SECTION_ORDER.forEach(id => {
        const heading = doc.querySelector(`[data-section="${id}"] [data-field="section_title"]`);
        if (heading) section_titles[id] = heading.textContent.trim();
    });

    // id/type are preserved from the original entry (never re-derived
    // from the on-page title) - section_order/hidden_sections reference
    // a custom section by id, so regenerating it from a possibly-edited
    // title would orphan it from its own ordering/visibility state.
    const custom_sections = (original.custom_sections || []).map(cs => {
        const sectionEl = doc.querySelector(`[data-section="${cs.id}"]`);
        if (!sectionEl) return cs;
        const headingEl = sectionEl.querySelector('[data-field="section_title"]');
        const editedTitle = headingEl ? headingEl.textContent.trim() : cs.title;
        if (cs.type === 'text') {
            const textEl = sectionEl.querySelector('[data-field="custom_text"]');
            return { ...cs, title: editedTitle, text: textEl ? htmlToMarkdown(textEl) : cs.text };
        }
        const items = Array.from(sectionEl.querySelectorAll('[data-entry="custom-item"] [data-field="text"]'))
            .map(htmlToMarkdown).filter(Boolean);
        return { ...cs, title: editedTitle, items };
    });

    return { name, title, contact, summary, experience, projects, education, certifications, languages, skills, custom_sections, section_titles };
}

export async function openHistoryEditor(id) {
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
        // A freshly generated resume has no stored section_order at all
        // (routers/generate.py never sets one) - so the fallback above
        // only ever had the 7 fixed ids, and any custom section silently
        // had no row in the sections panel below (no checkbox, no
        // reorder), even though it renders fine in the iframe preview
        // itself (app/render_resume.py's build_resume_html appends it
        // there server-side). Mirror that same append here so it always
        // has a control, whether section_order was missing entirely or
        // just predates this custom section being added.
        (currentOriginalResume.custom_sections || []).forEach(cs => {
            if (!currentSectionOrder.includes(cs.id)) currentSectionOrder.push(cs.id);
        });
        currentHiddenSections = new Set(currentOriginalResume.hidden_sections || []);
        renderSectionControls();
        // The iframe's initial load already renders with this theme/color/
        // photo (server-side, from the same stored data) - this just syncs
        // the controls to match what's already on screen.
        document.getElementById('historyThemeSelect').value = currentOriginalResume.theme || 'classic';
        document.getElementById('historyColorPicker').value = currentOriginalResume.color || '#2b4f77';
        document.getElementById('historyPhotoInput').value = '';
        currentPhoto = currentOriginalResume.photo || '';

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

document.getElementById('historyColorPicker').addEventListener('input', (e) => {
    const doc = getPreviewDoc();
    if (doc && doc.body) doc.body.style.setProperty('--accent', e.target.value);
});

document.getElementById('historyPhotoInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
        currentPhoto = await resizeImageToDataUrl(file);
        applyPhotoToPreview(getPreviewDoc(), currentPhoto);
    } catch (error) {
        const statusEl = document.getElementById('historyEditStatus');
        statusEl.className = 'error';
        statusEl.textContent = `Error: ${error.message}`;
    }
});

document.getElementById('removeHistoryPhotoBtn').addEventListener('click', () => {
    currentPhoto = '';
    document.getElementById('historyPhotoInput').value = '';
    applyPhotoToPreview(getPreviewDoc(), '');
});

// Adds a brand-new custom section directly to *this* history entry - the
// Master Resume's "Custom Sections" editor only ever affects future
// generations (see routers/generate.py, which now carries custom_sections
// through verbatim at generate time), so a resume that already exists had
// no way to gain one short of regenerating it from scratch.
document.getElementById('addCustomSectionBtn').addEventListener('click', () => {
    const statusEl = document.getElementById('historyEditStatus');
    const doc = getPreviewDoc();
    if (!doc || !doc.body) {
        statusEl.className = 'error';
        statusEl.textContent = 'Preview is still loading - try again in a moment.';
        return;
    }

    const titleInput = document.getElementById('newCustomSectionTitle');
    const title = titleInput.value.trim();
    if (!title) {
        statusEl.className = 'error';
        statusEl.textContent = 'Enter a title for the new section first.';
        return;
    }

    let id = slugifyCustomId(title, currentSectionOrder.length);
    // slugifyCustomId only disambiguates a *blank* title (via the index
    // fallback) - two different titles that slugify to the same id (or
    // adding "Volunteer Work" twice) still need de-duplicating here, or
    // the second one would silently overwrite/merge with the first.
    let suffix = 2;
    const baseId = id;
    while (currentSectionOrder.includes(id)) {
        id = `${baseId}-${suffix++}`;
    }

    const type = document.getElementById('newCustomSectionType').value;
    const section = { id, title, type, items: [], text: '' };

    currentOriginalResume.custom_sections = [...(currentOriginalResume.custom_sections || []), section];
    currentSectionOrder.push(id);
    currentHiddenSections.delete(id);

    doc.body.appendChild(newCustomSectionEl(doc, section));
    renderSectionControls();
    applySectionOrderToPreview();

    titleInput.value = '';
    document.getElementById('newCustomSectionType').value = 'bullets';

    const heading = doc.querySelector(`[data-section="${id}"] [data-field="section_title"]`);
    if (heading) heading.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
    resume.section_order = currentSectionOrder;
    resume.hidden_sections = Array.from(currentHiddenSections);
    resume.theme = document.getElementById('historyThemeSelect').value;
    resume.color = document.getElementById('historyColorPicker').value;
    resume.photo = currentPhoto;

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
