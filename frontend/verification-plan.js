/**
 * Verification Plan Creation System - Frontend Application
 * 
 * Features:
 * - Query knowledge base with job-specific filtering
 * - Display chat history with user and assistant messages
 * - Show referenced PDF documents in iframe
 * - PDF document navigation (multiple PDFs)
 * - Persistent chat history in DynamoDB
 * - Uses dedicated Verification Plan Agent
 */

class KnowledgeQueryApp {
    constructor(config = {}) {
        this.apiEndpoint = config.apiEndpoint || '';
        this.selectedJobId = null;
        this.selectedFolderPaths = [];  // 複数フォルダ対応
        this.folderDefaultJobIds = {};  // フォルダごとのデフォルトJOB_ID
        this.chatSessionId = null;
        this.useAgent = true;  // Agent利用フラグ（固定: true）
        this.agentType = 'verification';  // 検証計画作成Agent
        
        // Cognito認証マネージャーへの参照
        this.authManager = null;
        
        // Chat state
        this.chatMessages = [];  // {role, content, sources, timestamp}
        
        // PDF state
        this.currentPdfUris = [];  // Array of available PDF URIs
        this.currentPdfIndex = 0;
        
        // Shift+F5（ハードリフレッシュ）検出フラグ
        this.isHardRefresh = this.detectHardRefresh();
        
        this.initializeElements();
        this.initializeChatSession();
        this.loadSettings();  // 設定を読み込み
        this.attachEventListeners();
        this.initializeResizeBar();  // Initialize resize functionality
        this.loadSearchTargetFromStorage();
        this.updateActivityState();  // Initialize activity state
        this.initializeAuthManager();  // 認証マネージャーの初期化
    }
    
    /**
     * Cognito認証マネージャーを初期化
     */
    initializeAuthManager() {
        // window.verificationPlanAuthManagerが利用可能になるまで待機
        const checkAuthManager = () => {
            if (window.verificationPlanAuthManager) {
                this.authManager = window.verificationPlanAuthManager;
                console.log('[VerificationPlanApp] Auth manager initialized');
            } else {
                setTimeout(checkAuthManager, 100);
            }
        };
        checkAuthManager();
    }
    
    /**
     * Detect hard refresh (Shift+F5)
     * performance.navigation.type = 2 means hard refresh
     */
    detectHardRefresh() {
        // performance.navigationを使用してハードリフレッシュを検出
        // type: 0 = Navigate, 1 = Reload, 2 = Back Forward, 3+ = Reserved
        // Shift+F5の場合は type = 1 (Reload) で、キャッシュは無視される
        
        // より確実に検出するため、タイムスタンプをsessionStorageに保存
        const lastLoadTime = sessionStorage.getItem('lastPageLoadTime');
        const currentTime = Date.now();
        
        // 前回のロード時刻から100ms以内の場合は同一セッション、それ以外はリロード
        const isReload = lastLoadTime && (currentTime - parseInt(lastLoadTime)) < 100;
        
        // 今回のロード時刻を保存
        sessionStorage.setItem('lastPageLoadTime', currentTime.toString());
        
        // performance.navigationが利用可能な場合はそちらも確認
        if (performance && performance.navigation) {
            const isPerformanceReload = performance.navigation.type === 1;
            console.log('[detectHardRefresh] performance.navigation.type:', performance.navigation.type, 'isReload:', !isReload);
            return !isReload || isPerformanceReload;
        }
        
        return !isReload;
    }
    
    /**
     * Initialize or retrieve chat session ID
     * Stored in sessionStorage to persist during page session
     * New ID generated on browser refresh or reset
     */
    initializeChatSession() {
        // Generate UUID v4
        const generateUUID = () => {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        };

        // Check if chat session ID exists in sessionStorage（検証計画モード専用）
        let sessionId = sessionStorage.getItem('verificationPlanSessionId');
        if (!sessionId) {
            sessionId = 'verification_' + generateUUID();
            sessionStorage.setItem('verificationPlanSessionId', sessionId);
            console.log('[initializeChatSession] Generated new verification session_id:', sessionId);
        } else {
            console.log('[initializeChatSession] Using existing verification session_id:', sessionId);
        }
        
        this.chatSessionId = sessionId;
    }
    
    /**
     * Load settings from localStorage
     */
    loadSettings() {
        // 検証計画モードでは常にAgentを利用
        this.useAgent = true;
        console.log('[loadSettings] useAgent (fixed):', this.useAgent);
    }
    
    /**
     * Save settings to localStorage
     */
    saveSettings() {
        localStorage.setItem('useAgent', this.useAgent.toString());
        console.log('[saveSettings] Saved useAgent:', this.useAgent);
    }
    
    initializeElements() {
        this.elements = {
            // Modal elements
            openSearchTargetBtn: document.getElementById('openSearchTargetBtn'),
            searchTargetModal: document.getElementById('searchTargetModal'),
            closeSearchTargetBtn: document.getElementById('closeSearchTargetBtn'),
            cancelSearchTargetBtn: document.getElementById('cancelSearchTargetBtn'),
            applySearchTargetBtn: document.getElementById('applySearchTargetBtn'),
            
            // Folder tree elements
            folderTreeContainer: document.getElementById('folderTreeContainer'),
            selectedFolderTags: document.getElementById('selectedFolderTags'),
            
            // Job ID input
            jobIdInputModal: document.getElementById('jobIdInputModal'),
            
            // Current search target display
            currentFolderDisplay: document.getElementById('currentFolderDisplay'),
            
            // Chat elements
            chatHistory: document.getElementById('chatHistory'),
            queryInput: document.getElementById('queryInput'),
            submitQueryBtn: document.getElementById('submitQueryBtn'),
            queryStatus: document.getElementById('queryStatus'),
            resetChatBtn: document.getElementById('resetChatBtn'),
            
            // PDF elements
            pdfSelectorContainer: document.getElementById('pdfSelectorContainer'),
            pdfViewerContainer: document.getElementById('pdfViewerContainer'),
            pdfIndicator: document.getElementById('pdfIndicator'),
            prevPdfBtn: document.getElementById('prevPdfBtn'),
            nextPdfBtn: document.getElementById('nextPdfBtn'),
            
            // Layout elements
            resizeBar: document.querySelector('.resize-bar'),
            chatSection: document.querySelector('.chat-section'),
            pdfSection: document.querySelector('.pdf-section')
        };
        
        // Verify critical elements exist
        const criticalElements = ['openSearchTargetBtn', 'searchTargetModal', 'submitQueryBtn', 'chatHistory'];
        for (const elemId of criticalElements) {
            if (!this.elements[elemId]) {
                console.error(`[initializeElements] Critical element missing: ${elemId}`);
            }
        }
        
        console.log('[initializeElements] Elements initialized:', this.elements);
    }
    
    /**
     * Update the activity state of chat and PDF sections
     * Hides PDF and minimizes chat when no messages exist
     */
    updateActivityState() {
        const chatSection = document.querySelector('.chat-section');
        const pdfSection = document.querySelector('.pdf-section');
        const queryContainer = document.querySelector('.knowledge-query-container');
        
        if (!chatSection || !pdfSection || !queryContainer) {
            console.warn('[updateActivityState] Required elements not found');
            return;
        }
        
        // If there are chat messages, activate both sections
        const hasActivity = this.chatMessages && this.chatMessages.length > 0;
        
        if (hasActivity) {
            // Activate: show full chat history and PDF section
            chatSection.classList.remove('inactive');
            pdfSection.classList.remove('inactive');
            queryContainer.classList.remove('inactive-state');
            console.log('[updateActivityState] Activated - showing chat history and PDF');
        } else {
            // Inactive: minimize chat history and hide PDF section
            chatSection.classList.add('inactive');
            pdfSection.classList.add('inactive');
            queryContainer.classList.add('inactive-state');
            console.log('[updateActivityState] Inactive - minimizing chat history and hiding PDF');
        }
    }
    
    attachEventListeners() {
        console.log('[attachEventListeners] Setting up event listeners...');
        
        // Modal event listeners
        this.elements.openSearchTargetBtn.addEventListener('click', () => {
            console.log('[attachEventListeners] openSearchTargetBtn clicked!');
            this.openSearchTargetModal();
        });
        
        this.elements.closeSearchTargetBtn.addEventListener('click', () => {
            this.closeSearchTargetModal();
        });
        
        this.elements.cancelSearchTargetBtn.addEventListener('click', () => {
            this.closeSearchTargetModal();
        });
        
        this.elements.applySearchTargetBtn.addEventListener('click', () => {
            this.applySearchTarget();
        });
        
        // Close modal when clicking outside
        this.elements.searchTargetModal.addEventListener('click', (e) => {
            if (e.target === this.elements.searchTargetModal) {
                this.closeSearchTargetModal();
            }
        });
        
        // Query submission listeners
        this.elements.submitQueryBtn.addEventListener('click', () => {
            console.log('[submitQueryBtn] Clicked!');
            this.submitQuery();
        });
        
        this.elements.queryInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.submitQuery();
            }
        });
        
        this.elements.prevPdfBtn.addEventListener('click', () => this.previousPdf());
        this.elements.nextPdfBtn.addEventListener('click', () => this.nextPdf());
        
        // Reset chat button listener
        if (this.elements.resetChatBtn) {
            this.elements.resetChatBtn.addEventListener('click', () => this.resetChatSession());
        }
        
        // Navigation buttons
        document.querySelectorAll('.nav-tab').forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                const page = button.getAttribute('data-page');
                if (page === 'knowledge-query') {
                    return;
                } else if (page && page !== 'knowledge-query') {
                    window.location.href = `${page}.html`;
                }
            });
        });
    }
    
    // ===== Resize Bar Methods =====
    
    /**
     * Initialize resize bar functionality for adjusting panel widths
     */
    initializeResizeBar() {
        if (!this.elements.resizeBar || !this.elements.chatSection || !this.elements.pdfSection) {
            console.warn('[initializeResizeBar] Required elements not found');
            return;
        }
        
        // Load saved panel size
        this.loadPanelSizeFromStorage();
        
        let isResizing = false;
        let startX = 0;
        let startChatWidth = 0;
        let startPdfWidth = 0;
        
        const handleMouseDown = (e) => {
            isResizing = true;
            startX = e.clientX;
            
            // Get current widths
            const chatRect = this.elements.chatSection.getBoundingClientRect();
            const pdfRect = this.elements.pdfSection.getBoundingClientRect();
            startChatWidth = chatRect.width;
            startPdfWidth = pdfRect.width;
            
            // Add resizing class for visual feedback
            this.elements.resizeBar.classList.add('resizing');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            
            e.preventDefault();
        };
        
        const handleMouseMove = (e) => {
            if (!isResizing) return;
            
            const deltaX = e.clientX - startX;
            const containerWidth = this.elements.chatSection.parentElement.offsetWidth;
            const resizeBarWidth = 8; // Width of resize bar
            
            // Calculate new widths
            let newChatWidth = startChatWidth + deltaX;
            let newPdfWidth = startPdfWidth - deltaX;
            
            // Set minimum widths (20% of container)
            const minWidth = containerWidth * 0.2;
            const maxChatWidth = containerWidth - minWidth - resizeBarWidth;
            
            // Constrain widths
            newChatWidth = Math.max(minWidth, Math.min(newChatWidth, maxChatWidth));
            newPdfWidth = containerWidth - newChatWidth - resizeBarWidth;
            
            // Calculate flex basis percentages
            const chatPercent = (newChatWidth / containerWidth) * 100;
            const pdfPercent = (newPdfWidth / containerWidth) * 100;
            
            // Apply new flex basis
            this.elements.chatSection.style.flexBasis = `${chatPercent}%`;
            this.elements.pdfSection.style.flexBasis = `${pdfPercent}%`;
        };
        
        const handleMouseUp = () => {
            if (!isResizing) return;
            
            isResizing = false;
            this.elements.resizeBar.classList.remove('resizing');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            
            // Save the new sizes
            this.savePanelSizeToStorage();
        };
        
        // Attach event listeners
        this.elements.resizeBar.addEventListener('mousedown', handleMouseDown);
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
        
        console.log('[initializeResizeBar] Resize bar initialized');
    }
    
    /**
     * Load panel size from localStorage
     */
    loadPanelSizeFromStorage() {
        try {
            const savedChatWidth = localStorage.getItem('verification-plan-chat-width');
            const savedPdfWidth = localStorage.getItem('verification-plan-pdf-width');
            
            if (savedChatWidth && savedPdfWidth) {
                this.elements.chatSection.style.flexBasis = savedChatWidth;
                this.elements.pdfSection.style.flexBasis = savedPdfWidth;
                console.log('[loadPanelSizeFromStorage] Loaded sizes:', savedChatWidth, savedPdfWidth);
            }
        } catch (error) {
            console.error('[loadPanelSizeFromStorage] Error loading panel sizes:', error);
        }
    }
    
    /**
     * Save panel size to localStorage
     */
    savePanelSizeToStorage() {
        try {
            const chatWidth = this.elements.chatSection.style.flexBasis || '40%';
            const pdfWidth = this.elements.pdfSection.style.flexBasis || '60%';
            
            localStorage.setItem('verification-plan-chat-width', chatWidth);
            localStorage.setItem('verification-plan-pdf-width', pdfWidth);
            console.log('[savePanelSizeToStorage] Saved sizes:', chatWidth, pdfWidth);
        } catch (error) {
            console.error('[savePanelSizeToStorage] Error saving panel sizes:', error);
        }
    }
    
    // ===== Search Target Modal Methods =====
    
    openSearchTargetModal() {
        console.log('[openSearchTargetModal] Opening modal...');
        console.log('[openSearchTargetModal] Modal element:', this.elements.searchTargetModal);
        console.log('[openSearchTargetModal] API Endpoint:', this.apiEndpoint);
        
        // モーダルが存在することを確認
        if (!this.elements.searchTargetModal) {
            console.error('[openSearchTargetModal] searchTargetModal element not found!');
            return;
        }
        
        // モーダルオープン時に選択済みのフォルダを表示
        this.updateSelectedFolderTags();
        
        // 保存されたJOB_IDをフィールドに復元
        if (this.selectedJobId) {
            this.elements.jobIdInputModal.value = this.selectedJobId;
        } else {
            this.elements.jobIdInputModal.value = '';
        }
        
        this.elements.searchTargetModal.style.display = 'block';
        console.log('[openSearchTargetModal] Modal display set to block');
        
        // 自動的にフォルダツリーを読み込む
        this.loadFolderTreeInModal();
    }
    
    closeSearchTargetModal() {
        this.elements.searchTargetModal.style.display = 'none';
        console.log('[closeSearchTargetModal] Modal closed');
    }
    
    // ===== Settings Modal Methods =====
    
    openSettingsModal() {
        console.log('[openSettingsModal] Opening settings modal...');
        
        // トグルボタンの状態を現在の設定に合わせる
        this.elements.useAgentToggle.checked = this.useAgent;
        
        // モーダルを表示
        this.elements.settingsModal.style.display = 'block';
        console.log('[openSettingsModal] Settings modal opened, useAgent:', this.useAgent);
    }
    
    closeSettingsModal() {
        this.elements.settingsModal.style.display = 'none';
        console.log('[closeSettingsModal] Settings modal closed');
    }
    
    saveSettingsFromModal() {
        // トグルボタンの状態を取得
        const newUseAgent = this.elements.useAgentToggle.checked;
        
        console.log('[saveSettingsFromModal] Saving settings: useAgent =', newUseAgent);
        
        // 設定が変更されたかチェック
        if (this.useAgent !== newUseAgent) {
            this.useAgent = newUseAgent;
            this.saveSettings();
            
            // 設定変更を通知
            alert(`設定を保存しました。\nAI エンジン: ${this.useAgent ? 'Agent利用（プレビュー）' : 'Knowledgebase直接検索'}`);
        }
        
        // モーダルを閉じる
        this.closeSettingsModal();
    }
    
    async loadFolderTreeInModal() {
        this.elements.folderTreeContainer.innerHTML = '<p class="placeholder-text">フォルダツリーを読み込み中...</p>';
        
        try {
            // knowledge-query.html用: 登録済みフォルダのみ取得
            const response = await this.apiRequest(`${this.apiEndpoint}/folders?registered_only=true`, {
                method: 'GET'
            });
            
            if (!response.ok) {
                throw new Error('フォルダツリーの取得に失敗しました');
            }
            
            const folders = await response.json();
            
            if (!folders || folders.length === 0) {
                this.elements.folderTreeContainer.innerHTML = '<p class="placeholder-text">登録されたフォルダがありません。<br>ステップ0・1でナレッジ化処理を実行してください。</p>';
                return;
            }
            
            this.renderFolderTreeWithCheckboxes(folders, 0);
            
        } catch (error) {
            console.error('[loadFolderTreeInModal] Error:', error);
            this.elements.folderTreeContainer.innerHTML = '<p class="placeholder-text error">フォルダツリーの取得に失敗しました</p>';
        }
    }
    
    renderFolderTreeWithCheckboxes(folders, level) {
        if (!folders || folders.length === 0) {
            this.elements.folderTreeContainer.innerHTML = '<p class="placeholder-text">フォルダが見つかりません</p>';
            return;
        }
        
        // 初回レンダリング時はコンテナをクリア
        if (level === 0) {
            this.elements.folderTreeContainer.innerHTML = '';
        }
        
        folders.forEach(folder => {
            const folderItem = document.createElement('div');
            folderItem.className = `folder-item level-${level}`;
            
            // リーフフォルダのみチェックボックスを表示
            if (folder.is_leaf) {
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.value = folder.path;
                checkbox.id = `folder-${folder.path.replace(/\//g, '-')}`;
                
                // 既に選択されているかチェック
                if (this.selectedFolderPaths.includes(folder.path)) {
                    checkbox.checked = true;
                    folderItem.classList.add('checked');
                }
                
                checkbox.addEventListener('change', (e) => {
                    this.toggleFolderSelection(folder.path, e.target.checked);
                    folderItem.classList.toggle('checked', e.target.checked);
                });
                
                const icon = document.createTextNode('📄 ');
                const label = document.createElement('label');
                label.htmlFor = checkbox.id;
                label.textContent = folder.name;
                label.style.cursor = 'pointer';
                
                folderItem.appendChild(checkbox);
                folderItem.appendChild(icon);
                folderItem.appendChild(label);
                folderItem.classList.add('leaf');
            } else {
                // 親フォルダはチェックボックスなし
                const icon = document.createTextNode('📁 ');
                const text = document.createTextNode(folder.name);
                folderItem.appendChild(icon);
                folderItem.appendChild(text);
                folderItem.classList.add('parent');
                folderItem.style.cursor = 'default';
            }
            
            this.elements.folderTreeContainer.appendChild(folderItem);
            
            // 子フォルダを再帰的にレンダリング
            if (folder.children && folder.children.length > 0) {
                this.renderFolderTreeWithCheckboxes(folder.children, level + 1);
            }
        });
    }
    
    toggleFolderSelection(folderPath, isSelected) {
        if (isSelected) {
            if (!this.selectedFolderPaths.includes(folderPath)) {
                this.selectedFolderPaths.push(folderPath);
            }
        } else {
            this.selectedFolderPaths = this.selectedFolderPaths.filter(p => p !== folderPath);
        }
        
        this.updateSelectedFolderTags();
        console.log('[toggleFolderSelection] Selected folders:', this.selectedFolderPaths);
    }
    
    updateSelectedFolderTags() {
        this.elements.selectedFolderTags.innerHTML = '';
        
        if (this.selectedFolderPaths.length === 0) {
            const noSelection = document.createElement('span');
            noSelection.className = 'no-selection';
            noSelection.textContent = '未選択';
            this.elements.selectedFolderTags.appendChild(noSelection);
            return;
        }
        
        this.selectedFolderPaths.forEach(path => {
            const tag = document.createElement('span');
            tag.className = 'folder-tag';
            
            const text = document.createTextNode(path);
            tag.appendChild(text);
            
            const removeBtn = document.createElement('button');
            removeBtn.className = 'remove-tag';
            removeBtn.textContent = '×';
            removeBtn.addEventListener('click', () => {
                this.toggleFolderSelection(path, false);
                // Update checkbox state
                const checkbox = document.getElementById(`folder-${path.replace(/\//g, '-')}`);
                if (checkbox) {
                    checkbox.checked = false;
                    checkbox.closest('.folder-item').classList.remove('checked');
                }
            });
            
            tag.appendChild(removeBtn);
            this.elements.selectedFolderTags.appendChild(tag);
        });
    }
    
    async applySearchTarget() {
        // フォルダパスが未選択の場合は警告
        if (this.selectedFolderPaths.length === 0) {
            alert('フォルダパスを最低1つ選択してください（必須）');
            return;
        }
        
        // 会話セッションが既に開始されているかチェック
        const hasActiveSession = this.chatMessages && this.chatMessages.length > 0;
        
        // 検索対象が変更されたかチェック
        const previousFolderPaths = JSON.parse(localStorage.getItem('selectedFolderPaths') || '[]');
        const previousJobId = localStorage.getItem('selectedJobId');
        const newJobId = this.elements.jobIdInputModal.value.trim() || null;
        
        const foldersChanged = JSON.stringify(previousFolderPaths.sort()) !== JSON.stringify([...this.selectedFolderPaths].sort());
        const jobIdChanged = previousJobId !== newJobId;
        const searchTargetChanged = foldersChanged || jobIdChanged;
        
        // 会話が存在し、かつ検索対象が変更された場合は確認ダイアログ
        if (hasActiveSession && searchTargetChanged) {
            const confirmed = confirm(
                '現在のチャットをリセットして新しいチャットをスタートしてもよろしいでしょうか?\n' +
                'リセットした場合でもチャット履歴は左サイドバーから確認できます。'
            );
            
            if (!confirmed) {
                // キャンセルされた場合は処理を中断
                console.log('[applySearchTarget] User cancelled reset');
                return;
            }
            
            // ユーザーが[はい]を選択した場合、セッションをリセット
            this.resetChatSession();
        }
        
        // JOB_IDを取得（オプション）
        this.selectedJobId = newJobId;
        
        // localStorageに保存
        localStorage.setItem('selectedFolderPaths', JSON.stringify(this.selectedFolderPaths));
        if (this.selectedJobId) {
            localStorage.setItem('selectedJobId', this.selectedJobId);
        } else {
            localStorage.removeItem('selectedJobId');
        }
        
        // 各フォルダのデフォルトJOB_IDをDynamoDBから取得
        await this.loadDefaultJobIdsForFolders();
        
        // 表示を更新
        this.updateCurrentFolderDisplay();
        
        // textareaを有効化
        this.elements.queryInput.disabled = false;
        
        // placeholderを更新
        this.updateQueryInputPlaceholder();
        
        // レンダリング
        this.renderChatHistory();
        
        // textareaに赤い点滅アニメーションを適用
        this.elements.queryInput.classList.add('blinking');
        
        // textareaに入力されたら点滅を解除
        const removeBlinkingOnInput = () => {
            this.elements.queryInput.classList.remove('blinking');
            this.elements.queryInput.removeEventListener('input', removeBlinkingOnInput);
        };
        this.elements.queryInput.addEventListener('input', removeBlinkingOnInput);
        
        // モーダルを閉じる
        this.closeSearchTargetModal();
        
        console.log('[applySearchTarget] Applied:', {
            folders: this.selectedFolderPaths,
            jobId: this.selectedJobId,
            defaultJobIds: this.folderDefaultJobIds
        });
    }
    
    async loadDefaultJobIdsForFolders() {
        // フォルダごとのデフォルトJOB_IDを格納
        this.folderDefaultJobIds = {};
        
        for (const folderPath of this.selectedFolderPaths) {
            try {
                const response = await this.apiRequest(`${this.apiEndpoint}/default-job?folder_path=${encodeURIComponent(folderPath)}`, {
                    method: 'GET'
                });
                
                if (response.ok) {
                    const data = await response.json();
                    if (data.job_id) {
                        this.folderDefaultJobIds[folderPath] = data.job_id;
                        console.log(`[loadDefaultJobIdsForFolders] Folder: ${folderPath}, Default JOB_ID: ${data.job_id}`);
                    }
                }
            } catch (error) {
                console.error(`[loadDefaultJobIdsForFolders] Error loading default job_id for ${folderPath}:`, error);
            }
        }
    }
    
    updateCurrentFolderDisplay() {
        if (this.selectedFolderPaths.length === 0) {
            this.elements.currentFolderDisplay.textContent = '未選択';
            this.elements.currentFolderDisplay.classList.add('empty');
        } else if (this.selectedFolderPaths.length === 1) {
            this.elements.currentFolderDisplay.textContent = this.selectedFolderPaths[0];
            this.elements.currentFolderDisplay.classList.remove('empty');
        } else {
            this.elements.currentFolderDisplay.textContent = `${this.selectedFolderPaths.length}個のフォルダ: ${this.selectedFolderPaths.join(', ')}`;
            this.elements.currentFolderDisplay.classList.remove('empty');
        }
    }
    
    updateQueryInputPlaceholder() {
        if (this.selectedFolderPaths.length === 0) {
            this.elements.queryInput.placeholder = '検索対象を上のボタンから選択してください。';
        } else {
            this.elements.queryInput.placeholder = '質問を入力してください...';
        }
    }
    
    loadSearchTargetFromStorage() {
        console.log('[loadSearchTargetFromStorage] Starting...');
        console.log('[loadSearchTargetFromStorage] isHardRefresh:', this.isHardRefresh);
        console.log('[loadSearchTargetFromStorage] selectedFolderPaths before:', this.selectedFolderPaths);
        
        // Shift+F5（ハードリフレッシュ）の場合はフォルダ選択をクリア
        if (this.isHardRefresh) {
            console.log('[loadSearchTargetFromStorage] Hard refresh detected. Clearing folder selection.');
            localStorage.removeItem('selectedFolderPaths');
            localStorage.removeItem('selectedJobId');
            this.selectedFolderPaths = [];
            this.selectedJobId = null;
            this.folderDefaultJobIds = {};
            this.updateCurrentFolderDisplay();
            // textareaを無効化
            this.elements.queryInput.disabled = true;
            // placeholderを更新
            this.updateQueryInputPlaceholder();
            // レンダリング
            this.renderChatHistory();
            // 検索対象が未選択の場合は自動でモーダルを開く
            console.log('[loadSearchTargetFromStorage] No folders selected (hard refresh), opening modal automatically');
            setTimeout(() => this.openSearchTargetModal(), 100);
            return;
        }
        
        // 通常のページロード時はlocalStorageから読み込み
        const storedFolders = localStorage.getItem('selectedFolderPaths');
        if (storedFolders) {
            try {
                this.selectedFolderPaths = JSON.parse(storedFolders);
            } catch (e) {
                this.selectedFolderPaths = [];
            }
        }
        
        const storedJobId = localStorage.getItem('selectedJobId');
        if (storedJobId) {
            this.selectedJobId = storedJobId;
        }
        
        // フォルダのデフォルトJOB_IDをロード
        if (this.selectedFolderPaths.length > 0) {
            this.loadDefaultJobIdsForFolders();
            // textareaを有効化
            this.elements.queryInput.disabled = false;
        } else {
            // textareaを無効化
            this.elements.queryInput.disabled = true;
            // 検索対象が未選択の場合は自動でモーダルを開く
            console.log('[loadSearchTargetFromStorage] No folders selected, opening modal automatically');
            setTimeout(() => this.openSearchTargetModal(), 100);
        }
        
        this.updateCurrentFolderDisplay();
        // placeholderを更新
        this.updateQueryInputPlaceholder();
        // レンダリング
        this.renderChatHistory();
        console.log('[loadSearchTargetFromStorage] Loaded:', {
            folders: this.selectedFolderPaths,
            jobId: this.selectedJobId
        });
    }
    
    /**
     * Reset chat session: Clear chat history and generate new session ID
     */
    resetChatSession() {
        console.log('[resetChatSession] Resetting chat session...');
        
        // Clear existing session ID from sessionStorage
        sessionStorage.removeItem('chatSessionId');
        
        // Generate new session ID
        const generateUUID = () => {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        };
        
        this.chatSessionId = generateUUID();
        sessionStorage.setItem('chatSessionId', this.chatSessionId);
        
        // Clear chat messages and UI
        this.chatMessages = [];
        this.currentPdfUris = [];
        this.currentPdfIndex = 0;
        this.renderChatHistory();
        
        // Clear PDF viewer
        if (this.elements.pdfViewerContainer) {
            this.elements.pdfViewerContainer.innerHTML = '';
        }
        
        // チャットのみリセット（フォルダ選択はそのまま）
        this.showMessage('チャットをリセットしました', 'info');
        console.log('[resetChatSession] New chat_session_id:', this.chatSessionId);
    }
    
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
                console.error('[apiRequest] Failed to get valid access token - refresh token may be expired');
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
                console.warn('[apiRequest] 401 Unauthorized - Attempting token refresh...');
                
                if (this.authManager) {
                    const refreshResult = await this.authManager.refreshAccessToken();
                    if (refreshResult.success) {
                        console.log('[apiRequest] Token refreshed successfully, retrying request...');
                        // 新しいトークンで再試行
                        const newAccessToken = await this.authManager.getAccessToken();
                        headers['Authorization'] = `Bearer ${newAccessToken}`;
                        
                        const retryResponse = await fetch(url, {
                            ...options,
                            headers: headers
                        });
                        
                        if (retryResponse.ok) {
                            console.log('[apiRequest] Retry successful after token refresh');
                            return retryResponse;
                        }
                    }
                }
                
                // リフレッシュ失敗または再試行も失敗
                console.error('[apiRequest] Token refresh failed or retry failed');
                window.location.href = 'index.html';
                throw new Error('認証エラー: セッションが切れました');
            }
            
            return response;
        } catch (error) {
            console.error('[apiRequest] Request failed:', error);
            throw error;
        }
    }
    
    /**
     * Load default Job ID from URL → localStorage → display
     */
    async loadChatHistory() {
        console.log('[loadChatHistory] Loading chat history from DynamoDB...');
        
        if (!this.selectedJobId) {
            // ジョブIDがない場合はスキップ
            console.log('[loadChatHistory] No job ID available, skipping history load');
            return;
        }
        
        try {
            // Query chat history from API
            // Use POST for history retrieval because GET with a body is not reliable across browsers
            const response = await fetch(`${this.apiEndpoint}/knowledge-query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    jobId: this.selectedJobId,
                    action: 'get-history',
                    mode: 'verification'
                })
            });
            
            if (response.ok) {
                const data = await response.json();
                this.chatMessages = data.messages || [];
                this.renderChatHistory();
                console.log('[loadChatHistory] Loaded', this.chatMessages.length, 'messages');
            }
        } catch (error) {
            console.error('[loadChatHistory] Error:', error);
            // Don't fail if history load fails
        }
    }
    
    async submitQuery() {
        console.log('[submitQuery] Submitting query...');
        console.log('[submitQuery] chat_session_id:', this.chatSessionId);
        console.log('[submitQuery] selectedFolderPaths:', this.selectedFolderPaths);
        console.log('[submitQuery] selectedJobId:', this.selectedJobId);
        console.log('[submitQuery] apiEndpoint:', this.apiEndpoint);
        
        const query = this.elements.queryInput.value.trim();
        if (!query) {
            this.showMessage('質問を入力してください', 'error');
            return;
        }
        
        // フォルダパスが未選択の場合は警告
        if (!this.selectedFolderPaths || this.selectedFolderPaths.length === 0) {
            this.showMessage('検索対象のフォルダを選択してください（ヘッダーの「検索対象選択」ボタンから）', 'error');
            return;
        }
        
        // Disable input while processing
        this.elements.submitQueryBtn.disabled = true;
        this.elements.queryInput.disabled = true;
        
        // ローディングUIを表示
        this.showLoadingUI('回答を生成中...');
        
        try {
            // Add user message to chat
            this.addChatMessage('user', query);
            this.elements.queryInput.value = '';
            
            // Build request body
            const requestBody = {
                query: query,
                chat_session_id: this.chatSessionId,
                use_agent: this.useAgent,  // Agent利用フラグを追加
                agent_type: this.agentType  // 検証計画作成Agent指定
            };
            
            console.log('[submitQuery] Using Agent:', this.useAgent, 'Type:', this.agentType);
            
            // JOB_IDが設定されている場合は優先
            if (this.selectedJobId) {
                requestBody.jobId = this.selectedJobId;
                requestBody.selected_job_id = this.selectedJobId;  // セッション情報として保存
                console.log('[submitQuery] Using Job ID:', this.selectedJobId);
            } else {
                // フォルダパスを使用（複数対応）
                requestBody.folder_paths = this.selectedFolderPaths;
                console.log('[submitQuery] Using folder paths:', this.selectedFolderPaths);
                
                // デフォルトJOB_IDがある場合は使用
                if (Object.keys(this.folderDefaultJobIds).length > 0) {
                    requestBody.folder_default_job_ids = this.folderDefaultJobIds;
                    console.log('[submitQuery] Using default job_ids:', this.folderDefaultJobIds);
                }
            }
            
            console.log('[submitQuery] Sending request body:', JSON.stringify(requestBody));
            
            // 1. Start async query
            const startResponse = await this.apiRequest(`${this.apiEndpoint}/knowledge-query/start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody)
            });
            
            console.log('[submitQuery] Start response status:', startResponse.status);
            
            if (!startResponse.ok) {
                const errorData = await startResponse.json();
                throw new Error(errorData.error || 'クエリの開始に失敗しました');
            }
            
            const startData = await startResponse.json();
            const queryId = startData.query_id;
            
            console.log('[submitQuery] Query started with ID:', queryId);
            
            // 2. Poll for results (3秒間隔, 最大180秒)
            const maxAttempts = 60; // 180秒 / 3秒
            let attempts = 0;
            let completed = false;
            
            while (attempts < maxAttempts && !completed) {
                attempts++;
                
                // Wait 3 seconds before polling
                await new Promise(resolve => setTimeout(resolve, 3000));
                
                console.log(`[submitQuery] Polling attempt ${attempts}/${maxAttempts}`);
                
                const statusResponse = await this.apiRequest(
                    `${this.apiEndpoint}/knowledge-query/status/${queryId}`,
                    {
                        method: 'GET',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    }
                );
                
                if (!statusResponse.ok) {
                    const errorData = await statusResponse.json();
                    throw new Error(errorData.error || 'ステータス取得に失敗しました');
                }
                
                const statusData = await statusResponse.json();
                console.log('[submitQuery] Status:', statusData.status);
                
                if (statusData.status === 'completed') {
                    // Success!
                    completed = true;
                    
                    const answer = statusData.answer || '';
                    const sources = statusData.sources || [];
                    const messageId = statusData.message_id || null;
                    
                    console.log('[submitQuery] Query completed successfully, message_id:', messageId);
                    
                    // Add assistant message with backend message_id
                    this.addChatMessage('assistant', answer, sources, messageId);
                    
                    // Update PDF list if sources are returned
                    if (sources.length > 0) {
                        this.updatePdfList(sources);
                    }
                    
                    // Hide loading UI
                    this.hideLoadingUI();
                    
                } else if (statusData.status === 'failed') {
                    // Query failed
                    throw new Error(statusData.error || 'クエリ処理に失敗しました');
                }
                // else: still processing, continue polling
            }
            
            if (!completed) {
                // Timeout
                throw new Error('タイムアウトしました。管理者に問い合わせてください');
            }
            
        } catch (error) {
            console.error('[submitQuery] Error:', error);
            this.showMessage('エラー: ' + error.message, 'error');
            this.hideLoadingUI();
        } finally {
            this.elements.submitQueryBtn.disabled = false;
            this.elements.queryInput.disabled = false;
        }
    }
    
    addChatMessage(role, content, sources = null, messageId = null) {
        console.log('[addChatMessage] Adding message:', role, 'messageId:', messageId);
        
        // Generate messageId for assistant messages if not provided
        if (!messageId && role === 'assistant') {
            const timestamp = new Date().toISOString();
            messageId = `${timestamp}#${Math.random().toString(36).substr(2, 9)}`;
        }
        
        const message = {
            role: role,
            content: content,
            sources: sources,
            timestamp: new Date().toLocaleString('ja-JP'),
            messageId: messageId  // Add messageId for feedback tracking
        };
        
        this.chatMessages.push(message);
        this.renderChatHistory();
    }
    
    renderChatHistory() {
        console.log('[renderChatHistory] Rendering', this.chatMessages.length, 'messages');
        
        const chatHtml = this.chatMessages.map((msg, idx) => {
            const roleClass = msg.role === 'user' ? 'user-message' : 'assistant-message';
            const roleLabel = msg.role === 'user' ? 'あなた' : 'AI先輩';
            
            // Convert newlines to <br> tags and escape HTML
            const formattedContent = this.escapeHtml(msg.content).replace(/\n/g, '<br>');
            
            let html = `
                <div class="chat-message ${roleClass}">
                    <strong>${roleLabel}</strong>
                    <p>${formattedContent}</p>
            `;
            
            // Add sources if present
            if (msg.sources && msg.sources.length > 0) {
                html += '<div class="sources-list"><strong>参考資料:</strong><ul>';
                msg.sources.forEach(source => {
                    const fileName = source.fileName || source.pdfFileName || source.title || 'Document';
                    const presignedUrl = source.presignedUrl || source.sourceUri;
                    
                    if (presignedUrl) {
                        html += `<li><a href="${this.escapeHtml(presignedUrl)}" target="_blank" rel="noopener noreferrer" class="source-link">📄 ${this.escapeHtml(fileName)}</a></li>`;
                    } else {
                        html += `<li>📄 ${this.escapeHtml(fileName)}</li>`;
                    }
                });
                html += '</ul></div>';
            }
            
            // Add rating/comment buttons and copy button for assistant messages only
            if (msg.role === 'assistant' && msg.messageId) {
                html += this.createFeedbackHtml(msg.messageId, msg.rating, msg.comment, this.escapeHtml(msg.content).replace(/"/g, '&quot;'));
            }
            
            html += `<small class="timestamp">${msg.timestamp}</small></div>`;
            return html;
        }).join('');
        
        this.elements.chatHistory.innerHTML = chatHtml;
        
        // Attach event listeners to rating and comment buttons
        this.attachFeedbackListeners();
        
        // Auto-scroll to bottom
        this.elements.chatHistory.scrollTop = this.elements.chatHistory.scrollHeight;
        
        // Update activity state based on message count
        this.updateActivityState();
    }
    
    createFeedbackHtml(messageId, existingRating = null, existingComment = null, contentForCopy = '') {
        const ratingNumbers = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'];
        const ratingButtons = ratingNumbers.map((num, idx) => {
            const rating = idx + 1;
            const isSelected = existingRating === rating ? ' active' : '';
            return `<button class="rating-btn${isSelected}" data-message-id="${messageId}" data-rating="${rating}" title="評価: ${num}">${num}</button>`;
        }).join('');
        
        // Build display section for existing rating and comment
        let displayHtml = '';
        
        if (existingRating) {
            const ratingNumbers = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'];
            const ratingSymbol = ratingNumbers[existingRating - 1];
            displayHtml += `<div class="feedback-display">評価: ${ratingSymbol}</div>`;
        }
        
        if (existingComment) {
            displayHtml += `<div class="feedback-display">コメント: ${this.escapeHtml(existingComment)}</div>`;
        }
        
        const html = `
            <div class="feedback-section">
                <div class="rating-group">
                    <span class="rating-label" title="低評価">👎</span>
                    ${ratingButtons}
                    <span class="rating-label" title="高評価">👍</span>
                </div>
                <button class="comment-btn" data-message-id="${messageId}" title="コメントを追加">💬 コメント</button>
                <button class="copy-btn" data-message-id="${messageId}" data-content="${contentForCopy}" title="内容をコピー">コピー</button>
            </div>
            ${displayHtml}
            <div class="comment-panel" id="comment-panel-${messageId}" style="display: none;">
                <textarea class="comment-input" placeholder="コメントを入力..." maxlength="500">${existingComment || ''}</textarea>
                <div class="comment-actions">
                    <button class="btn btn-small comment-submit-btn" data-message-id="${messageId}">送信</button>
                    <button class="btn btn-small comment-cancel-btn" data-message-id="${messageId}">キャンセル</button>
                </div>
            </div>
        `;
        
        return html;
    }
    
    attachFeedbackListeners() {
        // Copy button listeners
        document.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const content = btn.getAttribute('data-content');
                // Decode HTML entities
                const textarea = document.createElement('textarea');
                textarea.innerHTML = content;
                const decodedContent = textarea.value;
                
                try {
                    await navigator.clipboard.writeText(decodedContent);
                    
                    // Show feedback
                    const originalText = btn.innerHTML;
                    btn.innerHTML = '✓ コピーしました';
                    btn.classList.add('copied');
                    
                    setTimeout(() => {
                        btn.innerHTML = originalText;
                        btn.classList.remove('copied');
                    }, 2000);
                } catch (err) {
                    console.error('Failed to copy text:', err);
                    alert('コピーに失敗しました');
                }
            });
        });
        
        // Rating button listeners
        document.querySelectorAll('.rating-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const messageId = btn.getAttribute('data-message-id');
                const rating = parseInt(btn.getAttribute('data-rating'));
                console.log(`[attachFeedbackListeners] Rating button clicked: messageId=${messageId}, rating=${rating}`);
                
                // Update UI: remove active class from siblings, add to current
                const ratingGroup = btn.parentElement;
                ratingGroup.querySelectorAll('.rating-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                // Send to backend
                await this.submitFeedback(messageId, rating, null);
            });
        });
        
        // Comment button listeners
        document.querySelectorAll('.comment-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const messageId = btn.getAttribute('data-message-id');
                const panel = document.getElementById(`comment-panel-${messageId}`);
                console.log(`[attachFeedbackListeners] Comment button clicked: messageId=${messageId}`);
                
                // Toggle visibility
                if (panel.style.display === 'none') {
                    panel.style.display = 'block';
                    // Focus on textarea
                    const textarea = panel.querySelector('.comment-input');
                    setTimeout(() => textarea.focus(), 0);
                } else {
                    panel.style.display = 'none';
                }
            });
        });
        
        // Comment submit button listeners
        document.querySelectorAll('.comment-submit-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const messageId = btn.getAttribute('data-message-id');
                const panel = document.getElementById(`comment-panel-${messageId}`);
                const textarea = panel.querySelector('.comment-input');
                const comment = textarea.value.trim();
                
                console.log(`[attachFeedbackListeners] Comment submit: messageId=${messageId}, comment=${comment}`);
                
                if (comment) {
                    // Send to backend
                    await this.submitFeedback(messageId, null, comment);
                    
                    // Close panel after successful submission
                    panel.style.display = 'none';
                }
            });
        });
        
        // Comment cancel button listeners
        document.querySelectorAll('.comment-cancel-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const messageId = btn.getAttribute('data-message-id');
                const panel = document.getElementById(`comment-panel-${messageId}`);
                console.log(`[attachFeedbackListeners] Comment cancel: messageId=${messageId}`);
                
                // Close panel
                panel.style.display = 'none';
            });
        });
    }
    
    async submitFeedback(messageId, rating = null, comment = null) {
        try {
            const payload = {
                action: 'update-feedback',
                message_id: messageId,
                chat_session_id: this.chatSessionId  // Add chat_session_id
            };
            
            if (rating !== null) {
                payload.rating = rating;
            }
            
            if (comment !== null) {
                payload.comment = comment;
            }
            
            console.log('[submitFeedback] Sending feedback:', payload);
            
            const response = await this.apiRequest(`${this.apiEndpoint}/history`, {
                method: 'POST',
                body: JSON.stringify(payload)
            });
            
            if (!response.ok) {
                throw new Error('フィードバック送信に失敗しました');
            }
            
            const result = await response.json();
            console.log('[submitFeedback] Success:', result);
            
            // Update the message object in chatMessages array
            const messageObj = this.chatMessages.find(m => m.messageId === messageId);
            if (messageObj) {
                if (rating !== null) {
                    messageObj.rating = rating;
                }
                if (comment !== null) {
                    messageObj.comment = comment;
                }
                console.log('[submitFeedback] Updated message object:', messageObj);
            }
            
        } catch (error) {
            console.error('[submitFeedback] Error:', error);
            this.showMessage('フィードバック送信に失敗しました: ' + error.message, 'error');
        }
    }
    
    updatePdfList(sources) {
        console.log('[updatePdfList] Updating file list with', sources.length, 'sources');
        
        this.currentPdfUris = [];
        const uniquePdfs = new Map();  // Use map to avoid duplicates
        
        sources.forEach(source => {
            // Use presignedUrl if available (CORS-safe), fallback to sourceUri
            const fileUrl = source.presignedUrl || source.sourceUri;
            const key = fileUrl;
            if (!uniquePdfs.has(key)) {
                uniquePdfs.set(key, source);
                this.currentPdfUris.push(fileUrl);
                console.log('[updatePdfList] Added file:', source.fileName || source.pdfFileName, 'URL:', fileUrl);
            }
        });
        
        if (this.currentPdfUris.length > 0) {
            this.currentPdfIndex = 0;
            this.elements.pdfSelectorContainer.style.display = this.currentPdfUris.length > 1 ? 'block' : 'none';
            this.displayPdfInIframe(this.currentPdfUris[0]);
            this.updatePdfIndicators();
        }
    }
    
    displayPdfInIframe(pdfUrl) {
        console.log('[displayPdfInIframe] Displaying PDF:', pdfUrl);
        
        this.showMessage('PDFを読み込み中...', 'info');
        
        // Use iframe instead of fetch + PDF.js (no CORS required)
        const pdfContainer = this.elements.pdfViewerContainer;
        const iframe = document.createElement('iframe');
        iframe.src = pdfUrl;
        iframe.style.width = '100%';
        iframe.style.height = '100%';
        iframe.style.border = 'none';
        iframe.style.overflow = 'auto';
        iframe.scrolling = 'yes';
        
        pdfContainer.innerHTML = '';
        pdfContainer.appendChild(iframe);
        
        this.showMessage('', '');
        console.log('[displayPdfInIframe] PDF loaded in iframe');
    }
    
    async renderPdfPage(pageNum) {
        console.log('[renderPdfPage] Rendering page', pageNum);
        
        if (!this.currentPdfUris.length) return;
        
        const currentPdfUri = this.currentPdfUris[this.currentPdfIndex];
        const pdf = this.pdfDocuments[currentPdfUri];
        
        if (!pdf) {
            console.error('[renderPdfPage] PDF not loaded');
            return;
        }
        
        try {
            const page = await pdf.getPage(pageNum);
            const viewport = page.getViewport({ scale: this.pdfScale });
            
            const canvas = document.createElement('canvas');
            canvas.width = viewport.width;
            canvas.height = viewport.height;
            
            const context = canvas.getContext('2d');
            const renderContext = {
                canvasContext: context,
                viewport: viewport
            };
            
            await page.render(renderContext).promise;
            
            // Replace canvas content
            this.elements.pdfViewerContainer.innerHTML = '';
            this.elements.pdfViewerContainer.appendChild(canvas);
            
            this.updatePageIndicators();
            
        } catch (error) {
            console.error('[renderPdfPage] Error:', error);
            this.showMessage('ページの表示に失敗しました', 'error');
        }
    }
    
    previousPdf() {
        if (this.currentPdfIndex > 0) {
            this.currentPdfIndex--;
            this.displayPdfInIframe(this.currentPdfUris[this.currentPdfIndex]);
            this.updatePdfIndicators();
        }
    }
    
    nextPdf() {
        if (this.currentPdfIndex < this.currentPdfUris.length - 1) {
            this.currentPdfIndex++;
            this.displayPdfInIframe(this.currentPdfUris[this.currentPdfIndex]);
            this.updatePdfIndicators();
        }
    }
    
    updatePdfIndicators() {
        const indicator = `${this.currentPdfIndex + 1} / ${this.currentPdfUris.length}`;
        this.elements.pdfIndicator.textContent = indicator;
        
        this.elements.prevPdfBtn.disabled = this.currentPdfIndex === 0;
        this.elements.nextPdfBtn.disabled = this.currentPdfIndex === this.currentPdfUris.length - 1;
    }
    
    showMessage(message, type) {
        if (!message) {
            this.elements.queryStatus.style.display = 'none';
            this.elements.queryStatus.textContent = '';
            return;
        }
        
        this.elements.queryStatus.textContent = message;
        this.elements.queryStatus.className = `status-message ${type}`;
        this.elements.queryStatus.style.display = 'block';
    }
    
    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }
}

/**
 * History Sidebar Manager
 * Manages the chat history sidebar functionality
 */
class HistorySidebarManager {
    constructor(knowledgeQueryApp) {
        this.app = knowledgeQueryApp;
        this.histories = [];
        this.selectedHistoryMessageId = null;
        this.isCollapsed = true;  // Changed: Start in collapsed state
        
        try {
            this.initializeElements();
            this.initializeCollapsedState();  // New: Initialize collapsed UI
            this.attachEventListeners();
            this.loadHistories();
            console.log('[HistorySidebarManager] Initialization complete');
        } catch (error) {
            console.error('[HistorySidebarManager] Initialization error:', error);
            console.error('[HistorySidebarManager] Error stack:', error.stack);
        }
    }
    
    initializeCollapsedState() {
        // Initialize sidebar in collapsed state
        console.log('[initializeCollapsedState] Initializing sidebar in collapsed state');
        if (this.elements.sidebar) {
            this.elements.sidebar.classList.add('collapsed');
        }
        if (this.elements.toggleBtn) {
            this.elements.toggleBtn.textContent = '＞';  // Menu icon
            this.elements.toggleBtn.title = 'サイドバーを展開';
            this.elements.toggleBtn.style.display = 'flex';  // NEW: Ensure button is visible
        }
    }
    
    initializeElements() {
        this.elements = {
            sidebar: document.getElementById('historySidebar'),
            toggleBtn: document.getElementById('sidebarToggleBtn'),
            refreshBtn: document.getElementById('refreshHistoryBtn'),
            searchInput: document.getElementById('historySearchInput'),
            searchBtn: document.getElementById('historySearchBtn'),
            historyList: document.getElementById('historyList')
        };
        
        // Verify critical elements exist
        const criticalElements = ['sidebar', 'historyList'];
        for (const elemId of criticalElements) {
            if (!this.elements[elemId]) {
                console.error(`[HistorySidebarManager] Critical element missing: ${elemId}`);
            }
        }
        
        console.log('[HistorySidebarManager] Elements initialized:', this.elements);
    }
    
    attachEventListeners() {
        console.log('[HistorySidebarManager] Attaching event listeners...');
        
        // Toggle sidebar
        this.elements.toggleBtn.addEventListener('click', () => this.toggleSidebar());
        
        // Refresh histories
        this.elements.refreshBtn.addEventListener('click', () => this.loadHistories());
        
        // Search
        this.elements.searchBtn.addEventListener('click', () => this.searchHistories());
        this.elements.searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.searchHistories();
            }
        });
    }
    
    toggleSidebar() {
        this.isCollapsed = !this.isCollapsed;
        if (this.isCollapsed) {
            this.elements.sidebar.classList.add('collapsed');
            this.elements.toggleBtn.textContent = '＞';
            this.elements.toggleBtn.title = 'サイドバーを展開';
        } else {
            this.elements.sidebar.classList.remove('collapsed');
            this.elements.toggleBtn.textContent = '＜';
            this.elements.toggleBtn.title = 'サイドバーを最小化';
        }
        // Ensure button is always visible
        this.elements.toggleBtn.style.display = 'flex';  // NEW
        console.log('[toggleSidebar] Sidebar collapsed:', this.isCollapsed);
    }
    
    async loadHistories() {
        console.log('[loadHistories] Loading history summaries...');
        console.log('[loadHistories] apiEndpoint:', this.app.apiEndpoint);
        console.log('[loadHistories] chatSessionId:', this.app.chatSessionId);
        console.log('[loadHistories] selectedJobId:', this.app.selectedJobId);
        
        try {
            const requestBody = {
                chat_session_id: this.app.chatSessionId,
                action: 'get-history',
                mode: 'verification'
            };
            
            if (this.app.selectedJobId) {
                requestBody.jobId = this.app.selectedJobId;
            }
            
            console.log('[loadHistories] Request body:', JSON.stringify(requestBody));
            
            const response = await this.app.apiRequest(`${this.app.apiEndpoint}/history`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody)
            });
            
            console.log('[loadHistories] Response status:', response.status);
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('[loadHistories] Error response text:', errorText);
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }
            
            const data = await response.json();
            console.log('[loadHistories] Response data:', JSON.stringify(data));
            
            this.histories = data.histories || [];
            
            console.log('[loadHistories] Loaded', this.histories.length, 'history summaries');
            this.renderHistoryList();
            
        } catch (error) {
            console.error('[loadHistories] Error:', error);
            console.error('[loadHistories] Full error stack:', error.stack);
            const errorMsg = '履歴の読み込みに失敗しました: ' + (error.message || 'Unknown error');
            console.error('[loadHistories] Displaying error message:', errorMsg);
            if (this.elements && this.elements.historyList) {
                this.showEmptyMessage(errorMsg);
            } else {
                console.error('[loadHistories] historyList element not found');
            }
        }
    }
    
    renderHistoryList() {
        console.log('[renderHistoryList] Rendering', this.histories.length, 'histories');
        
        if (this.histories.length === 0) {
            this.showEmptyMessage('履歴がありません');
            return;
        }
        
        const html = this.histories.map(history => {
            const timestamp = new Date(history.timestamp);
            const timeStr = timestamp.toLocaleString('ja-JP', {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
            
            const questionPreview = history.first_question.substring(0, 50);
            const isActive = history.message_id === this.selectedHistoryMessageId;
            
            return `
                <div class="history-item ${isActive ? 'active' : ''}" data-message-id="${history.message_id}">
                    <div class="history-item-header">
                        <span class="history-item-time">${timeStr}</span>
                        <span class="history-item-count">${history.message_count}</span>
                    </div>
                    <div class="history-item-question">${this.app.escapeHtml(questionPreview)}</div>
                    <div class="history-item-preview">
                        <div class="history-preview-content" data-message-id="${history.message_id}">
                            <div class="loading">読み込み中...</div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
        
        this.elements.historyList.innerHTML = html;
        
        // Attach click listeners to history items
        document.querySelectorAll('.history-item').forEach(item => {
            item.addEventListener('click', () => {
                const messageId = item.getAttribute('data-message-id');
                this.loadHistoryDetail(messageId);
            });
            
            // Load preview content on hover
            item.addEventListener('mouseenter', () => {
                const messageId = item.getAttribute('data-message-id');
                this.loadHistoryPreview(messageId);
                // Show preview
                const preview = item.querySelector('.history-item-preview');
                if (preview) {
                    preview.style.display = 'block';
                }
            });
            
            // Hide preview when mouse leaves
            item.addEventListener('mouseleave', () => {
                const preview = item.querySelector('.history-item-preview');
                if (preview) {
                    preview.style.display = 'none';
                }
            });
        });
    }
    
    async loadHistoryPreview(messageId) {
        // Load the full conversation for preview
        const previewContainer = document.querySelector(`.history-preview-content[data-message-id="${messageId}"]`);
        if (!previewContainer) return;
        
        // Check if already loaded
        if (previewContainer.dataset.loaded === 'true') return;
        
        try {
            const response = await this.app.apiRequest(`${this.app.apiEndpoint}/history`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    chat_session_id: this.app.chatSessionId,
                    action: 'get-history-detail',
                    message_id: messageId
                })
            });
            
            if (!response.ok) {
                previewContainer.innerHTML = '<div class="error">プレビューを読み込めませんでした</div>';
                return;
            }
            
            const data = await response.json();
            const history = data.history;
            
            if (!history || !history.messages) {
                previewContainer.innerHTML = '<div class="error">メッセージが見つかりません</div>';
                return;
            }
            
            // Build preview HTML with all messages
            let previewHtml = '';
            for (const msg of history.messages) {
                const roleLabel = msg.role === 'user' ? 'ユーザー' : 'AI会話';
                const roleClass = msg.role === 'user' ? 'user' : 'assistant';
                previewHtml += `
                    <div class="history-preview-message">
                        <div class="history-preview-role ${roleClass}">${roleLabel}</div>
                        <div class="history-preview-text">${this.app.escapeHtml(msg.content)}</div>
                `;
                
                // Add rating if exists and is assistant message
                if (msg.role === 'assistant' && msg.rating) {
                    const ratingNumbers = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩'];
                    const ratingSymbol = ratingNumbers[msg.rating - 1];
                    previewHtml += `<div class="history-preview-rating">評価: ${ratingSymbol}</div>`;
                }
                
                // Add comment if exists and is assistant message
                if (msg.role === 'assistant' && msg.comment) {
                    previewHtml += `<div class="history-preview-comment">コメント: ${this.app.escapeHtml(msg.comment)}</div>`;
                }
                
                previewHtml += `</div>`;
            }
            
            previewContainer.innerHTML = previewHtml;
            previewContainer.dataset.loaded = 'true';
            
        } catch (error) {
            console.error('[loadHistoryPreview] Error:', error);
            previewContainer.innerHTML = '<div class="error">エラーが発生しました</div>';
        }
    }
    
    async loadHistoryDetail(messageId) {
        console.log('[loadHistoryDetail] Loading detail for message:', messageId);
        
        try {
            // 現在のアクティブなチャットセッションがあるかチェック
            const hasActiveSession = this.app.chatMessages && this.app.chatMessages.length > 0;
            
            // アクティブなセッションがある場合は確認ダイアログを表示
            if (hasActiveSession) {
                const confirmed = confirm(
                    '現在のチャットをリセットして履歴を読み込んでもよろしいでしょうか?\n' +
                    'リセットした場合でもチャット履歴は左サイドバーから確認できます。'
                );
                
                if (!confirmed) {
                    console.log('[loadHistoryDetail] User cancelled loading history');
                    return;
                }
            }
            
            // Mark as active
            this.selectedHistoryMessageId = messageId;
            document.querySelectorAll('.history-item').forEach(item => {
                if (item.getAttribute('data-message-id') === messageId) {
                    item.classList.add('active');
                } else {
                    item.classList.remove('active');
                }
            });
            
            // Fetch full conversation history from backend
            console.log('[loadHistoryDetail] Fetching history detail');
            
            const response = await this.app.apiRequest(`${this.app.apiEndpoint}/history`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    chat_session_id: this.app.chatSessionId,
                    message_id: messageId,
                    action: 'get-history-detail'
                })
            });
            
            if (!response.ok) {
                console.error('[loadHistoryDetail] Response not ok:', response.status);
                this.app.showMessage('履歴の読み込みに失敗しました', 'error');
                return;
            }
            
            const data = await response.json();
            
            if (!data.history) {
                console.error('[loadHistoryDetail] No history data in response');
                this.app.showMessage('履歴データが見つかりません', 'error');
                return;
            }
            
            const history = data.history;
            
            // フォルダ選択情報を復元
            if (history.selected_folder_paths && Array.isArray(history.selected_folder_paths)) {
                console.log('[loadHistoryDetail] Restoring selected_folder_paths:', history.selected_folder_paths);
                this.app.selectedFolderPaths = history.selected_folder_paths;
                
                // localStorageにも保存
                localStorage.setItem('selectedFolderPaths', JSON.stringify(history.selected_folder_paths));
                
                // デフォルトJOB_IDを再取得
                await this.app.loadDefaultJobIdsForFolders();
                
                // 表示を更新
                this.app.updateCurrentFolderDisplay();
            }
            
            // ユーザーが選択したJOB_IDを復元（オプション）
            if (history.selected_job_id) {
                console.log('[loadHistoryDetail] Restoring selected_job_id:', history.selected_job_id);
                this.app.selectedJobId = history.selected_job_id;
                localStorage.setItem('selectedJobId', history.selected_job_id);
            } else {
                this.app.selectedJobId = null;
                localStorage.removeItem('selectedJobId');
            }
            
            // チャットセッションIDを履歴のものに切り替え
            if (history.chat_session_id) {
                console.log('[loadHistoryDetail] Switching to chat_session_id:', history.chat_session_id);
                this.app.chatSessionId = history.chat_session_id;
                sessionStorage.setItem('chatSessionId', history.chat_session_id);
            }
            
            // Clear current chat and load the conversation
            this.app.chatMessages = [];
            
            // Load ALL messages from the chat session
            if (history.messages && history.messages.length > 0) {
                for (const msg of history.messages) {
                    const role = msg.role || 'user';
                    const content = msg.content || '';
                    this.app.addChatMessage(role, content);
                }
                
                // Display sources if available
                if (history.sources && history.sources.length > 0) {
                    this.displaySources(history.sources);
                }
            } else {
                // Fallback to old format (backward compatibility)
                if (history.user_message) {
                    this.app.addChatMessage('user', history.user_message);
                }
                if (history.assistant_message) {
                    this.app.addChatMessage('assistant', history.assistant_message);
                }
            }
            
            // textareaを有効化（フォルダが復元されたので）
            if (this.app.selectedFolderPaths && this.app.selectedFolderPaths.length > 0) {
                this.app.elements.queryInput.disabled = false;
            }
            
            this.app.showMessage('履歴を読み込みました', 'success');
            
        } catch (error) {
            console.error('[loadHistoryDetail] Error:', error);
            this.app.showMessage('履歴の読み込みに失敗しました: ' + error.message, 'error');
        }
    }
    
    displaySources(sources) {
        /**
         * Display sources/references in the chat message area (same as AI query response)
         */
        if (!sources || sources.length === 0) {
            return;
        }
        
        // Build sources HTML (same format as AI query response)
        let sourcesHtml = '<div class="sources-section"><h4>📚 参考資料:</h4><ul class="sources-list">';
        
        sources.forEach((source) => {
            if (typeof source === 'object' && source !== null) {
                const fileName = source.fileName || source.pdfFileName || 'Document';
                const presignedUrl = source.presignedUrl || '';
                
                if (presignedUrl) {
                    sourcesHtml += `<li>
                        <a href="${this.app.escapeHtml(presignedUrl)}" target="_blank" rel="noopener noreferrer" class="source-link">
                            📄 ${this.app.escapeHtml(fileName)}
                        </a>
                    </li>`;
                } else {
                    sourcesHtml += `<li>📄 ${this.app.escapeHtml(fileName)}</li>`;
                }
            }
        });
        
        sourcesHtml += '</ul></div>';
        
        // Append sources to chat messages container
        const chatMessages = document.querySelector('.chat-history');
        if (chatMessages) {
            const sourcesDiv = document.createElement('div');
            sourcesDiv.innerHTML = sourcesHtml;
            sourcesDiv.className = 'source-display-container';
            chatMessages.appendChild(sourcesDiv);
        }
        
        // Display first PDF in the PDF viewer
        const firstSourceWithPdf = sources.find(s => 
            (typeof s === 'object') && s.presignedUrl);
        
        if (firstSourceWithPdf) {
            const pdfUrl = firstSourceWithPdf.presignedUrl;
            this.app.displayPdfInIframe(pdfUrl);
            
            // Store all PDF URLs for navigation
            this.app.currentPdfUris = sources
                .filter(s => (typeof s === 'object') && s.presignedUrl)
                .map(s => s.presignedUrl);
            this.app.currentPdfIndex = 0;
            
            // Show PDF selector if multiple PDFs
            if (this.app.currentPdfUris.length > 1) {
                this.app.updatePdfIndicators();
                this.app.elements.pdfSelectorContainer.style.display = 'block';
            }
        }
    }
    
    async searchHistories() {
        const query = this.elements.searchInput.value.trim();
        if (!query) {
            console.log('[searchHistories] Empty search query');
            this.app.showMessage('検索キーワードを入力してください', 'info');
            this.loadHistories();
            return;
        }
        
        console.log('[searchHistories] Searching for:', query);
        this.app.showMessage('検索中...', 'info');
        
        try {
            const requestBody = {
                chat_session_id: this.app.chatSessionId,
                action: 'search',
                search_query: query,
                mode: 'verification'
            };
            
            if (this.app.selectedJobId) {
                requestBody.jobId = this.app.selectedJobId;
            }
            
            console.log('[searchHistories] Request body:', JSON.stringify(requestBody));
            
            const response = await this.app.apiRequest(`${this.app.apiEndpoint}/history`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody)
            });
            
            console.log('[searchHistories] Response status:', response.status);
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('[searchHistories] Error response:', errorText);
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }
            
            const data = await response.json();
            console.log('[searchHistories] Response data:', JSON.stringify(data));
            
            this.app.showMessage('', '');
            this.histories = data.results || [];
            this.renderHistoryList();
        } catch (error) {
            console.error('[searchHistories] Error:', error);
            this.app.showMessage('検索エラー: ' + error.message, 'error');
        }
    }
    
    showEmptyMessage(message) {
        this.elements.historyList.innerHTML = `<div class="empty-message">${this.app.escapeHtml(message)}</div>`;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Helper functions for loading UI
function showLoadingUI(message) {
    // Remove existing loading UI if present
    hideLoadingUI();
    
    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'loading-spinner-overlay';
    loadingDiv.innerHTML = `
        <div class="loading-spinner-container">
            <div class="loading-spinner"></div>
            <p class="loading-message">${message}</p>
        </div>
    `;
    document.body.appendChild(loadingDiv);
}

function hideLoadingUI() {
    const loadingDiv = document.getElementById('loading-spinner-overlay');
    if (loadingDiv) {
        loadingDiv.remove();
    }
}

// Add loading UI methods to KnowledgeQueryApp prototype
KnowledgeQueryApp.prototype.showLoadingUI = showLoadingUI;
KnowledgeQueryApp.prototype.hideLoadingUI = hideLoadingUI;

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    console.log('[DOMContentLoaded] Initializing KnowledgeQueryApp...');
    console.log('[DOMContentLoaded] window.API_CONFIG:', window.API_CONFIG);
    
    // Get API endpoint from AppConfig
    const apiEndpoint = AppConfig.getApiEndpoint();
    console.log('[DOMContentLoaded] Resolved API endpoint:', apiEndpoint);
    
    const config = {
        apiEndpoint: apiEndpoint,
        ...window.API_CONFIG
    };
    
    console.log('[DOMContentLoaded] Passing config to KnowledgeQueryApp:', config);
    window.knowledgeQueryApp = new KnowledgeQueryApp(config);
    
    // Initialize history sidebar manager
    console.log('[DOMContentLoaded] Initializing HistorySidebarManager...');
    window.historySidebarManager = new HistorySidebarManager(window.knowledgeQueryApp);
});

