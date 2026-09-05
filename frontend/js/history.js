import { apiFetch, formatApiError } from './utils.js';
import { openHistoryEditor } from './history-editor.js';

// ---------- History ----------

// Swaps the name/job-description display for an inline text input (value
// pre-filled with the current name, or blank if unnamed - the job
// description stays visible as the placeholder so it's clear what an
// empty save reverts to). Mirrors the rest of this app's "reload the list
// after a mutation" convention (see loadVersions()/loadMasterResume())
// rather than patching the row's DOM in place.
function startRenaming(item, meta) {
    meta.innerHTML = '';

    const input = document.createElement('input');
    input.type = 'text';
    input.value = item.name || '';
    input.placeholder = item.job_description;

    const statusEl = document.createElement('div');
    statusEl.className = 'hint';

    const actions = document.createElement('div');
    actions.className = 'edit-actions';

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', async () => {
        try {
            const res = await apiFetch(`/history/${item.id}/name`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: input.value }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(formatApiError(data, 'Rename failed'));
            loadHistory();
        } catch (error) {
            statusEl.textContent = `Error: ${error.message}`;
            statusEl.style.color = 'var(--error)';
        }
    });

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'secondary';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => loadHistory());

    actions.appendChild(saveBtn);
    actions.appendChild(cancelBtn);
    meta.appendChild(input);
    meta.appendChild(actions);
    meta.appendChild(statusEl);
    input.focus();
}

async function deleteHistoryEntry(item) {
    if (!confirm('Delete this resume? This cannot be undone.')) return;
    try {
        const res = await apiFetch(`/history/${item.id}`, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) throw new Error(formatApiError(data, 'Delete failed'));
        loadHistory();
    } catch (error) {
        const el = document.getElementById('historyList');
        el.textContent = `Error deleting: ${error.message}`;
    }
}

export async function loadHistory() {
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
            if (item.name) {
                const name = document.createElement('div');
                name.className = 'history-name';
                name.textContent = item.name;
                meta.appendChild(name);
            }
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
            right.appendChild(document.createElement('br'));
            const renameBtn = document.createElement('button');
            renameBtn.type = 'button';
            renameBtn.className = 'secondary';
            renameBtn.textContent = 'Rename';
            renameBtn.addEventListener('click', () => startRenaming(item, meta));
            right.appendChild(renameBtn);

            right.appendChild(document.createElement('br'));
            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'danger-outline';
            deleteBtn.textContent = 'Delete';
            deleteBtn.addEventListener('click', () => deleteHistoryEntry(item));
            right.appendChild(deleteBtn);

            row.appendChild(meta);
            row.appendChild(right);
            el.appendChild(row);
        }
    } catch (error) {
        el.textContent = `Error loading history: ${error.message}`;
    }
}
