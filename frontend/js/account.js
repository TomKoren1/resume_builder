import { apiFetch, formatApiError } from './utils.js';

// ---------- Account ----------
export async function loadAccount() {
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
