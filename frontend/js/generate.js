import { apiFetch, resizeImageToDataUrl } from './utils.js';

// ---------- Generate ----------
document.getElementById('resumeForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const btn = e.target.querySelector('button');
    const responseDiv = document.getElementById('response');
    const jobDesc = document.getElementById('jobDescription').value;
    const theme = document.getElementById('themeSelect').value;
    const color = document.getElementById('colorPicker').value;
    const photoFile = document.getElementById('photoInput').files[0];

    btn.textContent = 'Generating...';
    btn.disabled = true;
    responseDiv.style.display = 'block';
    responseDiv.textContent = 'Contacting AWS Bedrock...';

    try {
        const photo = photoFile ? await resizeImageToDataUrl(photoFile) : '';
        const res = await apiFetch('/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_description: jobDesc, theme, color, photo })
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
