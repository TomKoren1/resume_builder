// FastAPI returns `detail` as a plain string for hand-raised HTTPExceptions,
// but as an array of {loc, msg} field errors for Pydantic 422 validation
// failures - normalize both into one readable string.
export function formatApiError(data, fallback) {
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

// Downscales+recompresses an uploaded photo client-side before it ever
// becomes a base64 string - an unresized phone photo can be several MB,
// which would bloat the generation_history row (and every JSON payload
// touching it) for a resume that only ever displays it at ~84px. Caps
// the longest edge at 300px and re-encodes as JPEG.
export function resizeImageToDataUrl(file, maxDim = 300, quality = 0.82) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const img = new Image();
            img.onload = () => {
                let { width, height } = img;
                if (width > height) {
                    if (width > maxDim) { height = Math.round(height * maxDim / width); width = maxDim; }
                } else if (height > maxDim) {
                    width = Math.round(width * maxDim / height); height = maxDim;
                }
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                canvas.getContext('2d').drawImage(img, 0, 0, width, height);
                resolve(canvas.toDataURL('image/jpeg', quality));
            };
            img.onerror = () => reject(new Error('Could not read that image.'));
            img.src = reader.result;
        };
        reader.onerror = () => reject(new Error('Could not read that file.'));
        reader.readAsDataURL(file);
    });
}

export function showView(viewName) {
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
export async function apiFetch(url, opts = {}) {
    const res = await fetch(url, { ...opts, credentials: 'include' });
    if (res.status === 401) {
        showView('login');
        throw new Error('Not logged in.');
    }
    return res;
}
