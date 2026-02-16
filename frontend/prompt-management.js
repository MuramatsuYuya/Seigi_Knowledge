/**
 * Prompt Template Management System - Frontend Application
 * 
 * Features:
 * - CRUD operations for output format templates
 * - Agent type switching (VERIFICATION, SPECIFICATION, QUERY_SUPPORT)
 * - Editable output format templates (system prompts are in Bedrock Agent Instructions)
 * - Template preview
 * - Default template management
 */

class PromptManagementApp {
    constructor(config = {}) {
        this.apiEndpoint = config.apiEndpoint || '';
        this.currentAgentType = 'VERIFICATION';
        this.currentTemplate = null;  // Currently loaded template
        this.templates = [];          // List of templates for current agent type
        this.authManager = null;

        this.initializeElements();
        this.attachEventListeners();
        this.initializeAuthManager();
        this.loadData();
    }

    // =====================================================
    // Initialization
    // =====================================================

    initializeAuthManager() {
        const checkAuthManager = () => {
            if (window.promptMgmtAuthManager) {
                this.authManager = window.promptMgmtAuthManager;
                console.log('[PromptMgmt] Auth manager initialized');
            } else {
                setTimeout(checkAuthManager, 100);
            }
        };
        checkAuthManager();
    }

    initializeElements() {
        this.elements = {
            // Tabs
            agentTabs: document.querySelectorAll('.agent-type-tab'),
            
            // Template controls
            templateDropdown: document.getElementById('templateDropdown'),
            loadTemplateBtn: document.getElementById('loadTemplateBtn'),
            newTemplateBtn: document.getElementById('newTemplateBtn'),
            deleteTemplateBtn: document.getElementById('deleteTemplateBtn'),
            
            // Template info
            templateName: document.getElementById('templateName'),
            templateDesc: document.getElementById('templateDesc'),
            isDefaultCheckbox: document.getElementById('isDefaultCheckbox'),
            
            // Prompt sections
            editablePromptEditor: document.getElementById('editablePromptEditor'),
            charCount: document.getElementById('charCount'),
            
            // Action buttons
            saveTemplateBtn: document.getElementById('saveTemplateBtn'),
            previewBtn: document.getElementById('previewBtn'),
            
            // Preview modal
            previewModal: document.getElementById('previewModal'),
            previewBody: document.getElementById('previewBody'),
            closePreviewBtn: document.getElementById('closePreviewBtn'),
            
            // Toast
            statusToast: document.getElementById('statusToast')
        };
    }

    attachEventListeners() {
        // Agent type tabs
        this.elements.agentTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchAgentType(tab.dataset.agent);
            });
        });

        // Template controls
        this.elements.loadTemplateBtn.addEventListener('click', () => this.loadSelectedTemplate());
        this.elements.newTemplateBtn.addEventListener('click', () => this.resetForm());
        this.elements.deleteTemplateBtn.addEventListener('click', () => this.deleteTemplate());

        // Template dropdown - auto-load on change
        this.elements.templateDropdown.addEventListener('change', () => {
            const templateId = this.elements.templateDropdown.value;
            if (templateId) {
                this.loadSelectedTemplate();
            }
        });

        // Save
        this.elements.saveTemplateBtn.addEventListener('click', () => this.saveTemplate());

        // Character counter
        this.elements.editablePromptEditor.addEventListener('input', () => {
            this.updateCharCount();
        });

        // Preview
        this.elements.previewBtn.addEventListener('click', () => this.showPreview());
        this.elements.closePreviewBtn.addEventListener('click', () => this.hidePreview());
        this.elements.previewModal.addEventListener('click', (e) => {
            if (e.target === this.elements.previewModal) this.hidePreview();
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                this.saveTemplate();
            }
        });
    }

    // =====================================================
    // API Communication
    // =====================================================

    /**
     * API request helper with authentication token (有効期限チェック付き)
     */
    async apiRequest(url, options = {}) {
        const headers = options.headers || {};

        // Cognito トークンを取得（期限切れの場合は自動リフレッシュ）
        let accessToken = null;
        if (this.authManager) {
            accessToken = await this.authManager.getAccessToken();
            if (!accessToken) {
                console.error('[PromptMgmt][apiRequest] Failed to get valid access token - refresh token may be expired');
                window.location.href = 'index.html';
                throw new Error('認証セッションが切れました');
            }
        } else {
            // フォールバック: 直接LocalStorageから取得（非推奨）
            const idToken = localStorage.getItem('cognito_id_token');
            accessToken = localStorage.getItem('cognito_access_token');
            accessToken = idToken || accessToken;
        }

        if (accessToken) {
            headers['Authorization'] = `Bearer ${accessToken}`;
        }

        // Content-Typeが指定されていない場合、デフォルトを設定
        if (!headers['Content-Type'] && options.body && typeof options.body === 'string') {
            headers['Content-Type'] = 'application/json';
        }

        try {
            const response = await fetch(url, {
                ...options,
                headers: headers
            });

            // 401エラーの場合、トークンをリフレッシュして再試行
            if (response.status === 401) {
                console.warn('[PromptMgmt][apiRequest] 401 Unauthorized - Attempting token refresh...');

                if (this.authManager) {
                    const refreshResult = await this.authManager.refreshAccessToken();
                    if (refreshResult.success) {
                        console.log('[PromptMgmt][apiRequest] Token refreshed successfully, retrying request...');
                        const newAccessToken = await this.authManager.getAccessToken();
                        headers['Authorization'] = `Bearer ${newAccessToken}`;

                        const retryResponse = await fetch(url, {
                            ...options,
                            headers: headers
                        });

                        if (retryResponse.ok) {
                            console.log('[PromptMgmt][apiRequest] Retry successful after token refresh');
                            return retryResponse;
                        }
                    }
                }

                // リフレッシュ失敗または再試行も失敗
                console.error('[PromptMgmt][apiRequest] Token refresh failed or retry failed');
                window.location.href = 'index.html';
                throw new Error('認証エラー: セッションが切れました');
            }

            return response;
        } catch (error) {
            console.error('[PromptMgmt][apiRequest] Request failed:', error);
            throw error;
        }
    }

    // =====================================================
    // Data Loading
    // =====================================================

    async loadData() {
        await this.loadTemplates();
    }

    async loadTemplates() {
        try {
            const response = await this.apiRequest(
                `${this.apiEndpoint}/prompt-templates?agentType=${this.currentAgentType}`
            );
            if (response.ok) {
                const data = await response.json();
                this.templates = data.templates || [];
                this.populateDropdown();
                
                // Auto-load default template
                const defaultTemplate = this.templates.find(t => t.isDefault);
                if (defaultTemplate && !this.currentTemplate) {
                    this.elements.templateDropdown.value = defaultTemplate.templateId;
                    this.loadTemplateData(defaultTemplate);
                }
            } else {
                console.error('[PromptMgmt] Failed to load templates');
            }
        } catch (error) {
            console.error('[PromptMgmt] Error loading templates:', error);
        }
    }

    populateDropdown() {
        const dropdown = this.elements.templateDropdown;
        // Keep first option (新規作成)
        while (dropdown.options.length > 1) {
            dropdown.remove(1);
        }

        this.templates.forEach(template => {
            const option = document.createElement('option');
            option.value = template.templateId;
            const defaultMarker = template.isDefault ? ' ★' : '';
            option.textContent = `${template.name}${defaultMarker}`;
            dropdown.appendChild(option);
        });
    }

    // =====================================================
    // Template Operations
    // =====================================================

    loadSelectedTemplate() {
        const templateId = this.elements.templateDropdown.value;
        if (!templateId) {
            this.resetForm();
            return;
        }

        const template = this.templates.find(t => t.templateId === templateId);
        if (template) {
            this.loadTemplateData(template);
        }
    }

    loadTemplateData(template) {
        this.currentTemplate = template;
        this.elements.templateName.value = template.name || '';
        this.elements.templateDesc.value = template.description || '';
        this.elements.editablePromptEditor.value = template.editablePrompt || '';
        this.elements.isDefaultCheckbox.checked = template.isDefault || false;
        this.updateCharCount();
        this.showToast('テンプレートを読み込みました', 'info');
    }

    resetForm() {
        this.currentTemplate = null;
        this.elements.templateDropdown.value = '';
        this.elements.templateName.value = '';
        this.elements.templateDesc.value = '';
        this.elements.editablePromptEditor.value = '';
        this.elements.isDefaultCheckbox.checked = false;
        this.updateCharCount();
    }

    async saveTemplate() {
        const name = this.elements.templateName.value.trim();
        const description = this.elements.templateDesc.value.trim();
        const editablePrompt = this.elements.editablePromptEditor.value.trim();
        const isDefault = this.elements.isDefaultCheckbox.checked;

        if (!name) {
            this.showToast('テンプレート名を入力してください', 'error');
            this.elements.templateName.focus();
            return;
        }

        if (!editablePrompt) {
            this.showToast('編集可能部分を入力してください', 'error');
            this.elements.editablePromptEditor.focus();
            return;
        }

        const body = {
            agentType: this.currentAgentType,
            name: name,
            description: description,
            editablePrompt: editablePrompt,
            isDefault: isDefault
        };

        try {
            let response;
            
            if (this.currentTemplate) {
                // Update existing template
                body.templateId = this.currentTemplate.templateId;
                response = await this.apiRequest(`${this.apiEndpoint}/prompt-templates`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
            } else {
                // Create new template
                response = await this.apiRequest(`${this.apiEndpoint}/prompt-templates`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
            }

            if (response.ok) {
                const data = await response.json();
                this.currentTemplate = data;
                this.showToast('テンプレートを保存しました ✓', 'success');
                await this.loadTemplates();
                
                // Re-select the saved template
                if (data.templateId) {
                    this.elements.templateDropdown.value = data.templateId;
                }
            } else {
                const errorData = await response.json();
                this.showToast(`保存に失敗しました: ${errorData.error || '不明なエラー'}`, 'error');
            }
        } catch (error) {
            console.error('[PromptMgmt] Error saving template:', error);
            this.showToast('保存中にエラーが発生しました', 'error');
        }
    }

    async deleteTemplate() {
        if (!this.currentTemplate) {
            this.showToast('削除するテンプレートを選択してください', 'error');
            return;
        }

        const confirmed = confirm(`テンプレート「${this.currentTemplate.name}」を削除しますか？\nこの操作は取り消せません。`);
        if (!confirmed) return;

        try {
            const response = await this.apiRequest(
                `${this.apiEndpoint}/prompt-templates?agentType=${this.currentAgentType}&templateId=${this.currentTemplate.templateId}`,
                { method: 'DELETE' }
            );

            if (response.ok) {
                this.showToast('テンプレートを削除しました', 'success');
                this.resetForm();
                await this.loadTemplates();
            } else {
                const errorData = await response.json();
                this.showToast(`削除に失敗しました: ${errorData.error || '不明なエラー'}`, 'error');
            }
        } catch (error) {
            console.error('[PromptMgmt] Error deleting template:', error);
            this.showToast('削除中にエラーが発生しました', 'error');
        }
    }

    // =====================================================
    // Agent Type Switching
    // =====================================================

    switchAgentType(agentType) {
        this.currentAgentType = agentType;
        this.currentTemplate = null;

        // Update tab UI
        this.elements.agentTabs.forEach(tab => {
            tab.classList.toggle('active', tab.dataset.agent === agentType);
        });

        // Reset form and reload
        this.resetForm();
        this.loadData();
    }

    // =====================================================
    // Preview
    // =====================================================

    showPreview() {
        const editablePrompt = this.elements.editablePromptEditor.value;
        const combinedPrompt = this.fixedPrompt + '\n\n' + editablePrompt;
        
        this.elements.previewBody.textContent = combinedPrompt;
        this.elements.previewModal.classList.add('active');
    }

    hidePreview() {
        this.elements.previewModal.classList.remove('active');
    }

    // =====================================================
    // UI Helpers
    // =====================================================

    updateCharCount() {
        const count = this.elements.editablePromptEditor.value.length;
        this.elements.charCount.textContent = count.toLocaleString();
    }

    showToast(message, type = 'info') {
        const toast = this.elements.statusToast;
        toast.textContent = message;
        toast.className = `status-toast ${type} visible`;
        
        setTimeout(() => {
            toast.classList.remove('visible');
        }, 3000);
    }
}

// =====================================================
// Initialize Application
// =====================================================
document.addEventListener('DOMContentLoaded', () => {
    const apiEndpoint = AppConfig ? AppConfig.getApiEndpoint() : '/api';
    
    const app = new PromptManagementApp({
        apiEndpoint: apiEndpoint
    });
    
    console.log('[PromptMgmt] Application initialized');
});
