import { apiFetch, showView } from './utils.js';
import { loadHistory } from './history.js';
import { loadMasterResume, initImportSection } from './master-resume.js';
import { loadAccount } from './account.js';
import './generate.js';

// ---------- Tab switching ----------
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        showView(btn.dataset.view);
        if (btn.dataset.view === 'history') loadHistory();
        if (btn.dataset.view === 'edit') { loadMasterResume(); initImportSection(); }
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
