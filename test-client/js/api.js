/**
 * Centralized API client wrapper using Fetch API.
 * Automatically injects authorization tokens and triggers custom events for the developer console panel.
 */
class APIClient {
    static getBaseUrl() {
        return localStorage.getItem('api_base_url') || 'http://localhost:8000';
    }

    static getHeaders() {
        const headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        };
        const authMethod = localStorage.getItem('auth_method') || 'token';
        
        if (authMethod === 'basic') {
            const user = localStorage.getItem('auth_username') || '';
            const pass = localStorage.getItem('auth_password') || '';
            if (user && pass) {
                headers['Authorization'] = 'Basic ' + btoa(user + ':' + pass);
            }
        } else if (authMethod === 'token') {
            const token = localStorage.getItem('auth_token');
            if (token) {
                headers['Authorization'] = token.trim();
            }
        }
        return headers;
    }

    /**
     * Executes the HTTP request and logs metrics to the dev panel.
     */
    static async request(method, path, body = null) {
        const baseUrl = this.getBaseUrl();
        const url = `${baseUrl}${path}`;
        const headers = this.getHeaders();
        const config = {
            method: method.toUpperCase(),
            headers: headers
        };
        
        const authMethod = localStorage.getItem('auth_method') || 'token';
        if (authMethod === 'session') {
            config.credentials = 'include';
        }

        if (body) {
            config.body = JSON.stringify(body);
        }

        const startTime = performance.now();
        let responseStatus = 0;
        let responseBody = null;
        let errorMsg = null;

        try {
            const response = await fetch(url, config);
            responseStatus = response.status;
            
            // Check content type before parsing JSON
            const contentType = response.headers.get("content-type");
            if (contentType && contentType.includes("application/json")) {
                responseBody = await response.json();
            } else {
                responseBody = await response.text();
            }

            if (!response.ok) {
                // If it is a standardized error wrapper, parse message
                const msg = (responseBody && (responseBody.message || responseBody.detail)) || `HTTP error ${response.status}`;
                const err = new Error(msg);
                err.status = response.status;
                err.errors = responseBody && responseBody.errors;
                err.detail = responseBody && responseBody.detail;
                throw err;
            }

            return responseBody;
        } catch (error) {
            errorMsg = error.message;
            if (!responseBody) {
                responseBody = { success: false, message: errorMsg, errors: error.errors || {} };
            }
            throw error;
        } finally {
            const endTime = performance.now();
            const duration = Math.round(endTime - startTime);

            // Dispatch global event for the Developer Debug Panel
            const logEvent = new CustomEvent('crm-api-log', {
                detail: {
                    timestamp: new Date().toLocaleTimeString(),
                    method: method.toUpperCase(),
                    url: url,
                    headers: headers,
                    requestBody: body,
                    status: responseStatus,
                    duration: duration,
                    responseBody: responseBody,
                    errorMessage: errorMsg
                }
            });
            window.dispatchEvent(logEvent);
        }
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

    static patch(path, body) {
        return this.request('PATCH', path, body);
    }

    static delete(path, body = null) {
        return this.request('DELETE', path, body);
    }
}

// Bind to window to allow global reuse across modules
window.APIClient = APIClient;
