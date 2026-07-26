class APIClient {
    static getBaseUrl() {
        if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
            return '';
        }
        return localStorage.getItem('api_base_url') || 'http://127.0.0.1:8000';
    }

    static getHeaders() {
        return {
            Accept: 'application/json',
            'Content-Type': 'application/json',
        };
    }

    static async request(method, path, body = null) {
        const url = `${this.getBaseUrl()}${path}`;
        const config = {
            method: method.toUpperCase(),
            headers: this.getHeaders(),
        };

        if (body) {
            config.body = JSON.stringify(body);
        }

        const response = await fetch(url, config);
        let responseBody;
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            responseBody = await response.json();
        } else {
            responseBody = await response.text();
        }

        if (!response.ok) {
            const msg =
                (responseBody && (responseBody.message || responseBody.detail)) ||
                `HTTP error ${response.status}`;
            const err = new Error(msg);
            err.status = response.status;
            err.errors = responseBody && responseBody.errors;
            throw err;
        }

        return responseBody;
    }

    static get(path) {
        return this.request('GET', path);
    }

    static post(path, body) {
        return this.request('POST', path, body);
    }

    static put(path, body) {
        return this.request('PUT', path, body);
    }

    static async download(path, filename) {
        const response = await fetch(`${this.getBaseUrl()}${path}`, {
            method: 'GET',
            headers: { Accept: '*/*' },
        });
        if (!response.ok) {
            throw new Error('Download failed');
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }
}

window.APIClient = APIClient;
