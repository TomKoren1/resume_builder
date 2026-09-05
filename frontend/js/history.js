import { apiFetch } from './utils.js';
import { openHistoryEditor } from './history-editor.js';

// ---------- History ----------
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
