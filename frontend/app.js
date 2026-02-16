/**
 * Document to Knowledge System - Frontend Application
 * 
 * Features:
 * - Job submission with custom prompts
 * - Real-time polling for results
 * - Display transcription and knowledge base results side-by-side
 * - Navigation through multiple PDFs in a job
 * - Load and review past job results
 */

class DoctoKnowApp {
    constructor(config = {}) {
        this.apiEndpoint = config.apiEndpoint || '';
        this.currentJobId = null;
        this.currentPdfIndex = 0;
        this.pdfList = [];
        this.selectedPdfs = [];  // 選択されたPDFファイルのリスト
        this.selectedFolderPath = null;  // 選択されたフォルダパス
        this.createdJobId = null;  // 作成されたジョブID
        this.results = {
            transcripts: {},
            knowledge: {},
            pdfs: {},
            statuses: {}
        };
        this.pollingInterval = null;
        
        // Cognito認証マネージャーへの参照
        this.authManager = null;
        
        this.initializeElements();
        this.attachEventListeners();
        this.setupPageNavigation();
        this.initializeStep0();  // Initialize Step 0 functionality
        this.initializeAuthManager();  // 認証マネージャーの初期化
        this.updatePromptVisibility();  // 初期表示時のプロンプト制御
    }
    
    /**
     * Cognito認証マネージャーを初期化
     */
    initializeAuthManager() {
        // window.authUIControllerが利用可能になるまで待機
        const checkAuthManager = () => {
            if (window.authUIController?.authManager) {
                this.authManager = window.authUIController.authManager;
                console.log('[DoctoKnowApp] Auth manager initialized');
            } else {
                setTimeout(checkAuthManager, 100);
            }
        };
        checkAuthManager();
    }
    
    setupPageNavigation() {
        // Get all nav tabs
        const navTabs = document.querySelectorAll('.nav-tab');
        
        navTabs.forEach(tab => {
            tab.addEventListener('click', (e) => {
                e.preventDefault();
                const pageName = tab.getAttribute('data-page');
                this.switchPage(pageName);
            });
        });
    }
    
    switchPage(pageName) {
        // If switching to knowledge query, navigate to that page
        if (pageName === 'knowledge-query') {
            window.location.href = 'knowledge-query.html';
            return;
        }
        
        // If switching to verification plan, navigate to that page
        if (pageName === 'verification-plan') {
            window.location.href = 'verification-plan.html';
            return;
        }
        
        // If switching to specification, navigate to that page
        if (pageName === 'specification') {
            window.location.href = 'specification.html';
            return;
        }
        
        // If switching to prompt management, navigate to that page
        if (pageName === 'prompt-management') {
            window.location.href = 'prompt-management.html';
            return;
        }
        
        // For other pages, update nav tabs and page content
        const navTabs = document.querySelectorAll('.nav-tab');
        navTabs.forEach(tab => {
            tab.classList.remove('active');
            if (tab.getAttribute('data-page') === pageName) {
                tab.classList.add('active');
            }
        });
        
        const pageContents = document.querySelectorAll('.page-content');
        pageContents.forEach(page => page.classList.remove('active'));
        
        const activePage = document.getElementById(pageName + '-page');
        if (activePage) {
            activePage.classList.add('active');
        }
    }
    
    initializeElements() {
        this.elements = {
            // Folder Selection
            fetchFolderTreeBtn: document.getElementById('fetchFolderTreeBtn'),
            folderLoadingMsg: document.getElementById('folderLoadingMsg'),
            folderTreeContainer: document.getElementById('folderTreeContainer'),
            selectedFolderInfo: document.getElementById('selectedFolderInfo'),
            selectedFolderPath: document.getElementById('selectedFolderPath'),
            pdfSelectionSection: document.getElementById('pdfSelectionSection'),
            // PDF Selection
            fetchPdfListBtn: document.getElementById('fetchPdfListBtn'),
            pdfLoadingMsg: document.getElementById('pdfLoadingMsg'),
            pdfListContainer: document.getElementById('pdfListContainer'),
            pdfList: document.getElementById('pdfList'),
            selectAllBtn: document.getElementById('selectAllBtn'),
            deselectAllBtn: document.getElementById('deselectAllBtn'),
            selectedPdfsInfo: document.getElementById('selectedPdfsInfo'),
            selectedPdfCount: document.getElementById('selectedPdfCount'),
            selectedPdfNames: document.getElementById('selectedPdfNames'),
            // Default Job ID
            defaultJobIdSection: document.getElementById('defaultJobIdSection'),
            createdJobId: document.getElementById('createdJobId'),
            setAsDefaultJobIdBtn: document.getElementById('setAsDefaultJobIdBtn'),
            defaultJobIdStatus: document.getElementById('defaultJobIdStatus'),
            // Job Configuration
            processingMode: document.getElementById('processingMode'),
            transcriptPrompt: document.getElementById('transcriptPrompt'),
            knowledgePrompt: document.getElementById('knowledgePrompt'),
            transcriptPromptGroup: document.getElementById('transcriptPromptGroup'),
            knowledgePromptGroup: document.getElementById('knowledgePromptGroup'),
            jobId: document.getElementById('jobId'),
            jobIdSelect: document.getElementById('jobIdSelect'),
            refreshJobListBtn: document.getElementById('refreshJobListBtn'),
            submitBtn: document.getElementById('submitBtn'),
            loadJobBtn: document.getElementById('loadJobBtn'),
            reknowledgeBtn: document.getElementById('reknowledgeBtn'),
            // Status and Results
            statusSection: document.getElementById('statusSection'),
            statusMessage: document.getElementById('statusMessage'),
            progressFill: document.getElementById('progressFill'),
            prevBtn: document.getElementById('prevBtn'),
            nextBtn: document.getElementById('nextBtn'),
            currentPdfInfo: document.getElementById('currentPdfInfo'),
            transcriptResult: document.getElementById('transcriptResult'),
            knowledgeResult: document.getElementById('knowledgeResult')
        };
        
        // Check for missing elements
        const missingElements = Object.entries(this.elements)
            .filter(([key, el]) => !el)
            .map(([key]) => key);
        
        if (missingElements.length > 0) {
            console.error('❌ Missing DOM elements:', missingElements);
        }
    }
    
    attachEventListeners() {
        // Folder Selection listeners
        if (this.elements.fetchFolderTreeBtn) {
            this.elements.fetchFolderTreeBtn.addEventListener('click', () => {
                this.fetchFolderTree();
            });
        }
        
        // Default Job ID listeners
        if (this.elements.setAsDefaultJobIdBtn) {
            this.elements.setAsDefaultJobIdBtn.addEventListener('click', () => {
                this.setDefaultJobId();
            });
        }
        
        // PDF Selection listeners
        this.elements.fetchPdfListBtn.addEventListener('click', () => {
            this.fetchPdfList();
        });
        this.elements.selectAllBtn.addEventListener('click', () => this.selectAllPdfs());
        this.elements.deselectAllBtn.addEventListener('click', () => this.deselectAllPdfs());
        
        // Processing mode listener
        if (this.elements.processingMode) {
            this.elements.processingMode.addEventListener('change', () => {
                this.updatePromptVisibility();
            });
        }
        
        // Job submission listeners
        this.elements.submitBtn.addEventListener('click', () => {
            this.submitJob();
        });
        this.elements.loadJobBtn.addEventListener('click', () => {
            this.loadJobResults();
        });
        this.elements.reknowledgeBtn.addEventListener('click', () => {
            this.submitReknowledgeJob();
        });
        this.elements.refreshJobListBtn.addEventListener('click', () => {
            this.loadJobIdList();
        });
        this.elements.jobIdSelect.addEventListener('change', (e) => {
            const selectedJobId = e.target.value;
            if (selectedJobId) {
                this.elements.jobId.value = selectedJobId;
            }
        });
        this.elements.prevBtn.addEventListener('click', () => this.previousPdf());
        this.elements.nextBtn.addEventListener('click', () => this.nextPdf());
        
        // Load job list on initialization
        this.loadJobIdList();
    }
    
    /**
     * APIリクエスト時にアクセストークンを自動的に含める（有効期限チェック付き）
     */
    async apiRequest(url, options = {}) {
        const headers = options.headers || {};
        
        // authManagerがまだ初期化されていない場合は待機
        if (!this.authManager) {
            console.log('[apiRequest] Waiting for authManager to initialize...');
            await this.waitForAuthManager();
        }
        
        // Cognito IDトークンを取得（API Gateway Cognito Authorizer用）
        // 期限切れの場合は自動リフレッシュ
        let idToken = null;
        if (this.authManager) {
            console.log('[apiRequest] Using authManager to get ID token');
            idToken = await this.authManager.getIdToken();
            if (!idToken) {
                // トークン取得失敗（期限切れでリフレッシュも失敗）
                // リフレッシュトークンも期限切れの場合のみエラー
                console.error('[apiRequest] Failed to get valid ID token - refresh token may be expired');
                
                // トークンをクリアしてログイン画面を表示
                localStorage.removeItem('cognito_access_token');
                localStorage.removeItem('cognito_id_token');
                localStorage.removeItem('cognito_refresh_token');
                localStorage.removeItem('cognito_token_expires_at');
                
                if (window.authUIController) {
                    window.authUIController.showAuthenticationUI();
                }
                throw new Error('認証セッションが完全に切れました。再度ログインしてください。');
            }
        } else {
            // フォールバック: 直接LocalStorageから取得（非推奨）
            console.warn('[apiRequest] authManager not available, using localStorage fallback');
            idToken = localStorage.getItem('cognito_id_token');
        }
        
        if (idToken) {
            headers['Authorization'] = `Bearer ${idToken}`;
            console.log('[apiRequest] Initial ID token prefix:', idToken.substring(0, 50) + '...');
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
                    console.log('[apiRequest] Calling refreshAccessToken...');
                    const refreshResult = await this.authManager.refreshAccessToken();
                    console.log('[apiRequest] Refresh result:', refreshResult);
                    
                    if (refreshResult.success && refreshResult.idToken) {
                        console.log('[apiRequest] Token refreshed successfully, retrying request...');
                        // リフレッシュ結果から直接新しいIDトークンを使用
                        const newIdToken = refreshResult.idToken;
                        headers['Authorization'] = `Bearer ${newIdToken}`;
                        console.log('[apiRequest] Using new ID token from refresh result, token prefix:', newIdToken.substring(0, 50) + '...');
                        
                        const retryResponse = await fetch(url, {
                            ...options,
                            headers: headers
                        });
                        
                        console.log('[apiRequest] Retry response status:', retryResponse.status);
                        
                        if (retryResponse.ok) {
                            console.log('[apiRequest] Retry successful after token refresh');
                            return retryResponse;
                        } else {
                            console.error('[apiRequest] Retry still failed with status:', retryResponse.status);
                            // レスポンスボディも確認
                            try {
                                const errorBody = await retryResponse.text();
                                console.error('[apiRequest] Error response body:', errorBody);
                            } catch (e) {
                                // ignore
                            }
                        }
                    }
                } else {
                    console.error('[apiRequest] authManager is null, cannot refresh token');
                }
                
                // リフレッシュ失敗または再試行も失敗
                console.error('[apiRequest] Token refresh failed or retry failed');
                
                // トークンをクリアしてログイン画面を表示
                localStorage.removeItem('cognito_access_token');
                localStorage.removeItem('cognito_id_token');
                localStorage.removeItem('cognito_refresh_token');
                localStorage.removeItem('cognito_token_expires_at');
                
                if (window.authUIController) {
                    window.authUIController.showAuthenticationUI();
                }
                throw new Error('認証エラー: セッションが切れました');
            }
            
            return response;
        } catch (error) {
            console.error('[apiRequest] Request failed:', error);
            throw error;
        }
    }
    
    /**
     * authManagerの初期化を待機
     */
    waitForAuthManager() {
        return new Promise((resolve) => {
            if (this.authManager) {
                resolve();
                return;
            }
            
            const checkInterval = setInterval(() => {
                if (this.authManager) {
                    clearInterval(checkInterval);
                    resolve();
                }
            }, 50);
            
            // 最大3秒待機
            setTimeout(() => {
                clearInterval(checkInterval);
                console.warn('[waitForAuthManager] Timeout waiting for authManager');
                resolve();
            }, 3000);
        });
    }
    
    // ===== Folder Selection Methods =====
    
    /**
     * フォルダツリーを取得してレンダリング
     */
    async fetchFolderTree() {
        console.log('[fetchFolderTree] Starting folder tree fetch...');
        
        // コンテナを表示
        this.elements.folderTreeContainer.style.display = 'block';
        this.elements.folderTreeContainer.innerHTML = '<p>フォルダツリーを読み込み中...</p>';
        
        try {
            const response = await this.apiRequest(`${this.apiEndpoint}/folders`, {
                method: 'GET'
            });
            
            console.log('[fetchFolderTree] Response status:', response.status);
            
            if (!response.ok) {
                throw new Error('フォルダツリーの取得に失敗しました');
            }
            
            const folders = await response.json();
            console.log('[fetchFolderTree] Folders received:', folders);
            
            this.renderFolderTree(folders, 0);
            
        } catch (error) {
            console.error('[fetchFolderTree] Error:', error);
            this.elements.folderTreeContainer.innerHTML = `<p class="error">フォルダツリーの取得に失敗しました: ${error.message}</p>`;
        }
    }
    
    /**
     * フォルダツリーをDOMに描画
     * @param {Array} folders - フォルダ配列
     * @param {number} level - 階層レベル
     */
    renderFolderTree(folders, level) {
        if (!folders || folders.length === 0) {
            this.elements.folderTreeContainer.innerHTML = '<p>フォルダが見つかりません</p>';
            return;
        }
        
        // 初回レンダリング時はコンテナをクリア
        if (level === 0) {
            this.elements.folderTreeContainer.innerHTML = '';
        }
        
        folders.forEach(folder => {
            const folderItem = document.createElement('div');
            folderItem.className = `folder-item level-${level}`;
            folderItem.dataset.folderPath = folder.path;
            
            // フォルダアイコンと名前
            const icon = folder.is_leaf ? '📄' : '📁';
            folderItem.innerHTML = `${icon} ${folder.name}`;
            
            // リーフフォルダ（選択可能）の場合
            if (folder.is_leaf) {
                folderItem.classList.add('leaf');
                folderItem.addEventListener('click', () => {
                    this.selectFolder(folder.path);
                });
            } else {
                folderItem.classList.add('parent');
            }
            
            this.elements.folderTreeContainer.appendChild(folderItem);
            
            // 子フォルダを再帰的にレンダリング
            if (folder.children && folder.children.length > 0) {
                this.renderFolderTree(folder.children, level + 1);
            }
        });
    }
    
    /**
     * フォルダを選択してPDF選択セクションを有効化
     * @param {string} folderPath - 選択されたフォルダパス
     */
    selectFolder(folderPath) {
        // 以前の選択状態をクリア
        document.querySelectorAll('.folder-item.selected').forEach(item => {
            item.classList.remove('selected');
        });
        
        // 新しいフォルダを選択
        const selectedItem = document.querySelector(`.folder-item[data-folder-path="${folderPath}"]`);
        if (selectedItem) {
            selectedItem.classList.add('selected');
        }
        
        // 状態を更新
        this.selectedFolderPath = folderPath;
        this.elements.selectedFolderPath.textContent = folderPath;
        
        // PDF選択セクションを有効化
        this.elements.pdfSelectionSection.classList.remove('disabled');
        
        // ジョブIDリストを自動更新（過去の結果確認用）
        this.loadJobIdList();
    }
    
    /**
     * デフォルトJOB_IDをDynamoDBに設定
     */
    async setDefaultJobId() {
        if (!this.createdJobId || !this.selectedFolderPath) {
            console.error('[setDefaultJobId] Missing createdJobId or selectedFolderPath');
            return;
        }
        
        // 確認ダイアログを表示
        const confirmMessage = `警告: このJOB_IDをデフォルトに設定すると、\n「${this.selectedFolderPath}」フォルダでの\nAIへの質問で常にこのJOB_IDが使用されます。\n\nよろしいですか？`;
        
        if (!confirm(confirmMessage)) {
            console.log('[setDefaultJobId] User cancelled the operation');
            return;
        }
        
        try {
            this.elements.setAsDefaultJobIdBtn.disabled = true;
            
            const response = await this.apiRequest(`${this.apiEndpoint}/default-job`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    folder_path: this.selectedFolderPath,
                    job_id: this.createdJobId
                })
            });
            
            if (!response.ok) {
                throw new Error('Failed to set default job_id');
            }
            
            console.log('[setDefaultJobId] Default Job ID saved:', this.createdJobId, 'for folder:', this.selectedFolderPath);
            
            // ステータスメッセージを表示
            if (this.elements.defaultJobIdStatus) {
                this.elements.defaultJobIdStatus.textContent = `✓ デフォルトJOB_IDとして設定しました`;
                this.elements.defaultJobIdStatus.style.display = 'block';
                this.elements.defaultJobIdStatus.style.color = '#4caf50';
                
                // 3秒後に非表示
                setTimeout(() => {
                    if (this.elements.defaultJobIdStatus) {
                        this.elements.defaultJobIdStatus.style.display = 'none';
                    }
                }, 3000);
            }
        } catch (error) {
            console.error('[setDefaultJobId] Error:', error);
            if (this.elements.defaultJobIdStatus) {
                this.elements.defaultJobIdStatus.textContent = `✗ 設定に失敗しました: ${error.message}`;
                this.elements.defaultJobIdStatus.style.display = 'block';
                this.elements.defaultJobIdStatus.style.color = '#d32f2f';
            }
        } finally {
            this.elements.setAsDefaultJobIdBtn.disabled = false;
        }
    }
    
    // ===== PDF Selection Methods =====
    
    async fetchPdfList() {
        // フォルダが選択されているか確認
        if (!this.selectedFolderPath) {
            this.showError('フォルダを選択してください');
            return;
        }
        
        this.elements.fetchPdfListBtn.disabled = true;
        this.elements.pdfLoadingMsg.style.display = 'block';
        
        try {
            // フォルダパスをクエリパラメータとして送信
            const url = `${this.apiEndpoint}/list-pdfs?folder_path=${encodeURIComponent(this.selectedFolderPath)}`;
            const response = await this.apiRequest(url, {
                method: 'GET'
            });
            
            if (!response.ok) {
                throw new Error(`Failed to fetch PDF list: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            this.displayPdfList(data.files || []);
            this.showSuccess(`${data.files.length}件のPDFファイルを取得しました（フォルダ: ${this.selectedFolderPath}）`);
        } catch (error) {
            console.error('[fetchPdfList] Error:', error);
            this.showError('PDFリストの取得に失敗しました: ' + error.message);
        } finally {
            this.elements.fetchPdfListBtn.disabled = false;
            this.elements.pdfLoadingMsg.style.display = 'none';
        }
    }
    
    displayPdfList(pdfFiles) {
        this.elements.pdfList.innerHTML = '';
        this.elements.pdfListContainer.style.display = 'block';
        
        if (pdfFiles.length === 0) {
            this.elements.pdfList.innerHTML = '<li style="color: #999;">PDFファイルが見つかりませんでした</li>';
            return;
        }
        
        pdfFiles.forEach(pdfFile => {
            const li = document.createElement('li');
            li.style.padding = '6px 0';
            li.style.borderBottom = '1px solid #eee';
            li.style.display = 'flex';
            li.style.alignItems = 'center';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `pdf_${pdfFile}`;
            checkbox.value = pdfFile;
            checkbox.style.marginRight = '8px';
            checkbox.style.flexShrink = '0';
            checkbox.addEventListener('change', () => this.updateSelectedPdfs());
            
            const label = document.createElement('label');
            label.htmlFor = `pdf_${pdfFile}`;
            label.textContent = pdfFile;
            label.style.cursor = 'pointer';
            label.style.flex = '1';
            
            li.appendChild(checkbox);
            li.appendChild(label);
            this.elements.pdfList.appendChild(li);
        });
        
        this.updateSelectedPdfs();
    }
    
    updateSelectedPdfs() {
        const checkboxes = this.elements.pdfList.querySelectorAll('input[type="checkbox"]');
        this.selectedPdfs = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.value);
        
        // 要素が存在する場合のみ更新
        if (this.elements.selectedPdfCount) {
            this.elements.selectedPdfCount.textContent = this.selectedPdfs.length;
        }
        
        if (this.elements.selectedPdfNames) {
            this.elements.selectedPdfNames.textContent = this.selectedPdfs.length > 0
                ? this.selectedPdfs.join(', ')
                : '選択されていません';
        }
        
        if (this.elements.selectedPdfsInfo) {
            this.elements.selectedPdfsInfo.style.display = this.selectedPdfs.length > 0 ? 'block' : 'none';
        }
    }
    
    selectAllPdfs() {
        const checkboxes = this.elements.pdfList.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = true);
        this.updateSelectedPdfs();
    }
    
    deselectAllPdfs() {
        const checkboxes = this.elements.pdfList.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = false);
        this.updateSelectedPdfs();
    }
    
    getSelectedPdfs() {
        return this.selectedPdfs;
    }
    
    // ===== Job Submission Methods =====
    
    /**
     * Update prompt visibility based on processing mode
     */
    updatePromptVisibility() {
        const mode = this.elements.processingMode?.value || 'full';
        const isDirectPdf = mode === 'direct_pdf';
        
        if (this.elements.transcriptPromptGroup) {
            this.elements.transcriptPromptGroup.style.display = isDirectPdf ? 'none' : 'block';
        }
        if (this.elements.knowledgePromptGroup) {
            this.elements.knowledgePromptGroup.style.display = isDirectPdf ? 'none' : 'block';
        }
    }
    
    async submitJob() {
        const transcriptPrompt = this.elements.transcriptPrompt.value.trim();
        const knowledgePrompt = this.elements.knowledgePrompt.value.trim();
        const selectedPdfs = this.getSelectedPdfs();
        const processingMode = this.elements.processingMode?.value || 'full';
        
        // フォルダパスの確認
        if (!this.selectedFolderPath) {
            console.warn('[submitJob] No folder selected');
            alert('フォルダを選択してください');
            return;
        }
        
        // Direct PDFモード以外はプロンプト必須
        if (processingMode !== 'direct_pdf' && (!transcriptPrompt || !knowledgePrompt)) {
            console.warn('[submitJob] Missing prompts');
            alert('プロンプトを両方入力してください');
            return;
        }
        
        this.elements.submitBtn.disabled = true;
        this.showStatus('ジョブを送信中...');
        
        try {
            const requestBody = {
                folder_path: this.selectedFolderPath,
                processing_mode: processingMode
            };
            
            // Direct PDFモード以外はプロンプトを含める
            if (processingMode !== 'direct_pdf') {
                requestBody.transcript_prompt = transcriptPrompt;
                requestBody.knowledge_prompt = knowledgePrompt;
            }
            
            // 選択されたPDFがあれば、それを含める
            if (selectedPdfs.length > 0) {
                requestBody.pdfFiles = selectedPdfs;
                console.log('[submitJob] Including specific PDFs:', selectedPdfs);
            } else {
                console.log('[submitJob] No specific PDFs selected - processing all PDFs in folder:', this.selectedFolderPath);
            }
            
            const response = await this.apiRequest(`${this.apiEndpoint}/job`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody)
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            this.currentJobId = data.job_id;
            this.createdJobId = data.job_id;  // デフォルトJOB_ID用に保存
            
            // sessionStorage に保存
            sessionStorage.setItem('selectedJobId', this.currentJobId);
            
            // デフォルトJOB_IDセクションを表示
            this.elements.createdJobId.textContent = this.createdJobId;
            this.elements.defaultJobIdSection.style.display = 'block';
            
            this.showStatus(`ジョブ ${this.currentJobId} が送信されました。処理中...`);
            this.startPolling();
        } catch (error) {
            console.error('[submitJob] Error:', error);
            this.showError(`ジョブ送信エラー: ${error.message}`);
            this.elements.submitBtn.disabled = false;
        }
    }
    
    async submitReknowledgeJob() {
        const sourceJobId = this.elements.jobId.value.trim() || this.elements.jobIdSelect.value.trim();
        const knowledgePrompt = this.elements.knowledgePrompt.value.trim();
        
        if (!sourceJobId) {
            alert('元となるジョブIDを入力または選択してください');
            return;
        }
        
        if (!this.selectedFolderPath) {
            alert('ステップ1でフォルダを選択してください');
            return;
        }
        
        if (!knowledgePrompt) {
            alert('ナレッジ生成プロンプトを入力してください');
            return;
        }
        
        // 確認ダイアログ
        const confirmMsg = `ジョブID: ${sourceJobId} の文字起こし結果を使用して、\n新しいナレッジを生成します。\n\nよろしいですか?`;
        if (!confirm(confirmMsg)) {
            return;
        }
        
        this.elements.reknowledgeBtn.disabled = true;
        this.showStatus('再ナレッジ生成ジョブを送信中...');
        
        try {
            const requestBody = {
                job_id: sourceJobId,  // Use existing job_id for reknowledge
                folder_path: this.selectedFolderPath,
                knowledge_prompt: knowledgePrompt
            };
            
            const response = await this.apiRequest(`${this.apiEndpoint}/reknowledge`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody)
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            this.currentJobId = data.job_id;
            
            // sessionStorage に保存
            sessionStorage.setItem('selectedJobId', this.currentJobId);
            sessionStorage.setItem('selectedFolderPath', this.selectedFolderPath);
            
            this.showStatus(`再ナレッジ生成ジョブ ${this.currentJobId} が送信されました。\n元ジョブ: ${sourceJobId}\n処理中...`);
            this.startPolling();
        } catch (error) {
            console.error('[submitReknowledgeJob] Error:', error);
            this.showError(`再ナレッジ生成ジョブ送信エラー: ${error.message}`);
            this.elements.reknowledgeBtn.disabled = false;
        }
    }
    
    startPolling() {
        this.pollingInterval = setInterval(() => this.checkJobProgress(), 10000); // 10秒ごと
        this.checkJobProgress(); // 即座にチェック
    }
    
    async checkJobProgress() {
        if (!this.currentJobId) return;
        
        console.log('[checkJobProgress] Checking job:', this.currentJobId, 'folder:', this.selectedFolderPath);
        
        try {
            // API経由で結果を取得 (folder_path required)
            let url = `${this.apiEndpoint}/results/${this.currentJobId}`;
            if (this.selectedFolderPath) {
                url += `?folder_path=${encodeURIComponent(this.selectedFolderPath)}`;
            }
            
            console.log('[checkJobProgress] Fetching:', url);
            
            const response = await this.apiRequest(url);
            
            if (!response.ok) {
                console.warn(`[checkJobProgress] API returned status ${response.status}`);
                return;
            }
            
            const data = await response.json();
            console.log('[checkJobProgress] Received data:', data);
            
            // プロンプトをフォームに表示
            if (data.transcript_prompt) {
                this.elements.transcriptPrompt.value = data.transcript_prompt;
            }
            if (data.knowledge_prompt) {
                this.elements.knowledgePrompt.value = data.knowledge_prompt;
            }
            
            // 結果を処理
            if (data.results && Array.isArray(data.results)) {
                this.pdfList = [];
                this.results = {
                    transcripts: {},
                    knowledge: {},
                    pdfs: {},
                    statuses: {}  // ステータスを保存
                };
                
                // content_loadedフラグを保存（6ファイル以上の場合はfalse）
                this.contentLoaded = data.content_loaded !== false;
                
                for (const item of data.results) {
                    const pdfName = item.file_name || item.pdf_name;  // file_name with backward compatibility
                    
                    // PDFリストに追加
                    if (!this.pdfList.includes(pdfName)) {
                        this.pdfList.push(pdfName);
                    }
                    
                    // ステータスを保存
                    if (item.status) {
                        this.results.statuses[pdfName] = item.status;
                    }
                    
                    // PDF URLを保存
                    if (item.file_url) {
                        this.results.pdfs[pdfName] = item.file_url;
                        console.log(`[checkJobProgress] Saved PDF URL for ${pdfName}`);
                    }
                    
                    // 文字起こし結果を保存
                    if (item.transcript) {
                        this.results.transcripts[pdfName] = item.transcript;
                    }
                    
                    // ナレッジベース結果を保存
                    if (item.knowledge) {
                        this.results.knowledge[pdfName] = item.knowledge;
                    }
                }
                
                console.log(`[checkJobProgress] Loaded ${this.pdfList.length} PDFs`);
                
                // ステータスの集計とエラーメッセージをログ出力
                const statusCounts = {};
                const errorMessages = [];
                data.results.forEach(item => {
                    const status = item.status;
                    statusCounts[status] = (statusCounts[status] || 0) + 1;
                    if (status === 'failed' && item.message) {
                        errorMessages.push(`${item.file_name}: ${item.message}`);
                    }
                });
                console.log(`[checkJobProgress] Status breakdown:`, statusCounts);
                if (errorMessages.length > 0) {
                    console.error(`[checkJobProgress] Failed files:`, errorMessages);
                }
                
                this.updateProgress();
            }
        } catch (error) {
            console.log('[checkJobProgress] Error:', error.message);
        }
    }
    
    async fetchResults(transcriptPrefix, knowledgePrefix) {
        // 削除済み - checkJobProgress で直接API呼び出しに変更
        console.log('Deprecated: Use checkJobProgress instead');
    }
    
    async loadFileContent(fileName) {
        // 単一ファイルのコンテンツを取得（遅延ロード用）
        if (!this.currentJobId || !this.selectedFolderPath || !fileName) {
            console.warn('[loadFileContent] Missing required parameters');
            return;
        }
        
        try {
            const url = `${this.apiEndpoint}/results?job_id=${encodeURIComponent(this.currentJobId)}&folder_path=${encodeURIComponent(this.selectedFolderPath)}&file_name=${encodeURIComponent(fileName)}`;
            
            console.log(`[loadFileContent] Fetching content for ${fileName}`);
            
            const response = await this.apiRequest(url);
            
            if (!response.ok) {
                console.warn(`[loadFileContent] Failed to fetch content for ${fileName}`);
                return;
            }
            
            const data = await response.json();
            
            // 結果を保存
            if (data.transcript) {
                this.results.transcripts[fileName] = data.transcript;
            }
            if (data.knowledge) {
                this.results.knowledge[fileName] = data.knowledge;
            }
            
            console.log(`[loadFileContent] Successfully loaded content for ${fileName}`);
            
        } catch (error) {
            console.error(`[loadFileContent] Error loading ${fileName}:`, error);
        }
    }
    
    async updateProgress() {
        const total = this.pdfList.length;
        
        console.log('[updateProgress] Total files:', total);
        console.log('[updateProgress] Statuses:', this.results.statuses);
        console.log('[updateProgress] Transcripts:', Object.keys(this.results.transcripts).length);
        
        // ステータスが'done'のファイル数をカウント
        // ステータス情報がある場合はそれを使用、ない場合はtranscriptの存在で判断
        let completed = 0;
        if (this.results.statuses && Object.keys(this.results.statuses).length > 0) {
            completed = Object.values(this.results.statuses).filter(status => status === 'done').length;
            console.log(`[updateProgress] Using status info: ${completed}/${total} completed`);
        } else {
            completed = Object.keys(this.results.transcripts).length;
            console.log(`[updateProgress] Using transcript count: ${completed}/${total} completed`);
        }
        
        if (total > 0) {
            const percentage = (completed / total) * 100;
            this.elements.progressFill.style.width = percentage + '%';
            
            this.showStatus(`処理進捗: ${completed}/${total} (${Math.round(percentage)}%)`);
            
            if (completed === total) {
                this.stopPolling();
                this.showSuccess('すべてのPDFの処理が完了しました！');
                await this.displayResults();
            }
        }
    }
    
    async loadJobIdList() {
        try {
            // ステップ1で選択されたフォルダパスを使用
            if (!this.selectedFolderPath) {
                console.warn('[loadJobIdList] No folder selected');
                this.elements.jobIdSelect.innerHTML = '<option value="">-- まずステップ1でフォルダを選択してください --</option>';
                return;
            }
            
            const url = `${this.apiEndpoint}/results?folder_path=${encodeURIComponent(this.selectedFolderPath)}`;
            
            const response = await this.apiRequest(url);
            
            if (!response.ok) {
                console.warn('[loadJobIdList] Failed to fetch job list');
                return;
            }
            
            const data = await response.json();
            const jobIds = data.job_ids || [];
            
            // Clear and populate dropdown
            this.elements.jobIdSelect.innerHTML = '<option value="">-- ジョブIDを選択 --</option>';
            
            jobIds.forEach(jobId => {
                const option = document.createElement('option');
                option.value = jobId;
                option.textContent = jobId;
                this.elements.jobIdSelect.appendChild(option);
            });
            
            if (jobIds.length === 0) {
                const option = document.createElement('option');
                option.value = '';
                option.textContent = '（このフォルダにジョブが見つかりません）';
                this.elements.jobIdSelect.appendChild(option);
            }
        } catch (error) {
            console.error('[loadJobIdList] Error:', error);
        }
    }
    
    async loadJobResults() {
        const jobId = this.elements.jobId.value.trim();
        if (!jobId) {
            alert('ジョブIDを入力または選択してください');
            return;
        }
        
        if (!this.selectedFolderPath) {
            alert('ステップ1でフォルダを選択してください');
            return;
        }
        
        this.currentJobId = jobId;
        // sessionStorage に保存して、ページ遷移時にも参照可能にする
        sessionStorage.setItem('selectedJobId', jobId);
        sessionStorage.setItem('selectedFolderPath', this.selectedFolderPath);
        
        this.currentPdfIndex = 0;
        this.pdfList = [];
        this.results = {
            transcripts: {},
            knowledge: {},
            pdfs: {},
            statuses: {}
        };
        
        this.showStatus('ジョブ結果を読み込み中...');
        
        try {
            // API経由で結果を取得
            await this.checkJobProgress();
            
            if (this.pdfList.length > 0) {
                this.showSuccess(`${this.pdfList.length}件のPDF結果を読み込みました`);
                await this.displayResults();
            } else {
                this.showError('ジョブが見つからないか、まだ処理中です');
            }
        } catch (error) {
            this.showError(`ジョブ結果の読み込みエラー: ${error.message}`);
        }
    }
    
    async displayResults() {
        if (this.pdfList.length === 0) {
            this.elements.currentPdfInfo.textContent = 'PDF: なし';
            document.getElementById('pdfContainer').innerHTML = '<p class="loading">- 結果がまだありません -</p>';
            this.elements.transcriptResult.innerHTML = '<p class="loading">- 結果がまだありません -</p>';
            this.elements.knowledgeResult.innerHTML = '<p class="loading">- 結果がまだありません -</p>';
            return;
        }
        
        const pdfName = this.pdfList[this.currentPdfIndex];
        this.elements.currentPdfInfo.textContent = `PDF: ${pdfName} (${this.currentPdfIndex + 1}/${this.pdfList.length})`;
        
        // コンテンツが未読込み（6ファイル以上）で、このファイルのコンテンツがない場合、取得
        if (!this.contentLoaded && !this.results.transcripts[pdfName] && !this.results.knowledge[pdfName]) {
            this.elements.transcriptResult.innerHTML = '<p class="loading">読み込み中...</p>';
            this.elements.knowledgeResult.innerHTML = '<p class="loading">読み込み中...</p>';
            
            // 非同期でコンテンツを取得
            await this.loadFileContent(pdfName);
        }
        
        const transcript = this.results.transcripts[pdfName] || '処理中...';
        const knowledge = this.results.knowledge[pdfName] || '処理中...';
        
        // PDFを表示
        const pdfUrl = this.results.pdfs && this.results.pdfs[pdfName] ? this.results.pdfs[pdfName] : null;
        if (pdfUrl) {
            const pdfContainer = document.getElementById('pdfContainer');
            pdfContainer.innerHTML = `<iframe src="${pdfUrl}" style="width: 100%; height: 100%; border: none;"></iframe>`;
        } else {
            document.getElementById('pdfContainer').innerHTML = '<p class="loading">- PDFが見つかりません -</p>';
        }
        
        this.elements.transcriptResult.textContent = transcript;
        this.elements.knowledgeResult.textContent = knowledge;
        
        // ボタンの有効/無効を更新
        this.elements.prevBtn.disabled = this.currentPdfIndex === 0;
        this.elements.nextBtn.disabled = this.currentPdfIndex === this.pdfList.length - 1;
    }
    
    async previousPdf() {
        if (this.currentPdfIndex > 0) {
            this.currentPdfIndex--;
            await this.displayResults();
        }
    }
    
    async nextPdf() {
        if (this.currentPdfIndex < this.pdfList.length - 1) {
            this.currentPdfIndex++;
            await this.displayResults();
        }
    }
    
    showStatus(message) {
        this.elements.statusSection.style.display = 'block';
        this.elements.statusMessage.textContent = message;
        this.elements.statusMessage.className = '';
    }
    
    showError(message) {
        this.elements.statusSection.style.display = 'block';
        this.elements.statusMessage.textContent = message;
        this.elements.statusMessage.className = 'error';
    }
    
    showSuccess(message) {
        this.elements.statusSection.style.display = 'block';
        this.elements.statusMessage.textContent = message;
        this.elements.statusMessage.className = 'success';
    }
    
    // ===== Step 0: Folder & File Management Methods =====
    
    /**
     * Initialize Step 0 elements and event listeners
     */
    initializeStep0() {
        this.step0Elements = {
            fetchFolderTreeForMgmtBtn: document.getElementById('fetchFolderTreeForMgmtBtn'),
            folderMgmtLoadingMsg: document.getElementById('folderMgmtLoadingMsg'),
            folderMgmtContainer: document.getElementById('folderMgmtContainer'),
            fileInput: document.getElementById('fileInput'),
            uploadFilesBtn: document.getElementById('uploadFilesBtn'),
            uploadTargetPath: document.getElementById('uploadTargetPath'),
            fileInputContainer: document.getElementById('fileInputContainer'),
            uploadProgress: document.getElementById('uploadProgress'),
            uploadStatus: document.getElementById('uploadStatus'),
            uploadProgressFill: document.getElementById('uploadProgressFill'),
            registeredFolderOptions: document.getElementById('registeredFolderOptions'),
            uploadProcessingMode: document.getElementById('uploadProcessingMode')
        };
        
        // Event listeners
        if (this.step0Elements.fetchFolderTreeForMgmtBtn) {
            this.step0Elements.fetchFolderTreeForMgmtBtn.addEventListener('click', () => {
                this.fetchFolderTreeForManagement();
            });
        }
        
        if (this.step0Elements.uploadFilesBtn) {
            this.step0Elements.uploadFilesBtn.addEventListener('click', () => {
                this.uploadFiles();
            });
        }
        
        // Initialize state
        this.cachedFolderTree = [];
        this.selectedUploadFolder = null;
    }
    
    /**
     * Fetch folder tree with registration status for Step 0
     */
    async fetchFolderTreeForManagement() {
        console.log('[Step0] Fetching folder tree for management...');
        
        this.step0Elements.folderMgmtContainer.style.display = 'block';
        this.step0Elements.folderMgmtContainer.innerHTML = '<p>フォルダツリーを読み込み中...</p>';
        this.step0Elements.folderMgmtLoadingMsg.style.display = 'block';
        
        try {
            const response = await this.apiRequest(`${this.apiEndpoint}/folders`, {
                method: 'GET'
            });
            
            if (!response.ok) {
                throw new Error('フォルダツリーの取得に失敗しました');
            }
            
            const folders = await response.json();
            console.log('[Step0] Folders received:', folders);
            
            // Cache folder tree
            this.cachedFolderTree = folders;
            
            // PDF直下にフォルダを作成するボタンを表示
            const rootCreateBtn = document.createElement('div');
            rootCreateBtn.style.marginBottom = '16px';
            rootCreateBtn.innerHTML = '<button class="btn btn-primary-blue" id="createRootFolderBtn">📁 新規フォルダ</button>';
            this.step0Elements.folderMgmtContainer.innerHTML = '';
            this.step0Elements.folderMgmtContainer.appendChild(rootCreateBtn);
            
            // イベントリスナー設定
            document.getElementById('createRootFolderBtn').addEventListener('click', () => {
                this.createFolder(null);  // parentPath = null でルート作成
            });
            
            this.renderFolderTreeForManagement(folders, 0);
            this.step0Elements.folderMgmtLoadingMsg.style.display = 'none';
            
        } catch (error) {
            console.error('[Step0] Error:', error);
            this.step0Elements.folderMgmtContainer.innerHTML = `<p class="error">フォルダツリーの取得に失敗しました: ${error.message}</p>`;
            this.step0Elements.folderMgmtLoadingMsg.style.display = 'none';
        }
    }
    
    /**
     * Render folder tree for Step 0 with management buttons
     */
    renderFolderTreeForManagement(folders, level) {
        if (!folders || folders.length === 0) {
            this.step0Elements.folderMgmtContainer.innerHTML = '<p>フォルダが見つかりません</p>';
            return;
        }
        
        if (level === 0) {
            // level=0はrootCreateBtnの後に追加するため、innerHTML は置き換えない
        }
        
        folders.forEach(folder => {
            const folderItem = document.createElement('div');
            folderItem.className = `folder-item-mgmt level-${level}`;
            folderItem.dataset.folderPath = folder.path;
            
            // Folder icon and name
            const icon = '📁';
            const registeredBadge = folder.is_registered ? '<span class="registered-badge">✓ 登録済み</span>' : '';
            
            // ボタンの有効/無効を判定
            // is_leaf=false（ファイルなし）のみ新規フォルダ作成可能
            const canCreateFolder = folder.is_leaf === false;
            // 子フォルダがない場合のみアップロード可能（リーフフォルダ）
            const hasChildren = folder.children && folder.children.length > 0;
            const canUpload = !hasChildren;
            
            folderItem.innerHTML = `
                <span class="folder-name">${icon} ${folder.name} ${registeredBadge}</span>
                <div class="folder-actions">
                    ${canCreateFolder ? `<button class="btn-small btn-create-folder" data-path="${folder.path}">新規フォルダ</button>` : ''}
                    ${canUpload ? `<button class="btn-small btn-upload-here" data-path="${folder.path}">ここにアップロード</button>` : ''}
                    ${folder.can_delete ? `<button class="btn-small btn-delete-folder" data-path="${folder.path}">削除</button>` : ''}
                </div>
            `;
            
            this.step0Elements.folderMgmtContainer.appendChild(folderItem);
            
            // Attach event listeners
            const createBtn = folderItem.querySelector('.btn-create-folder');
            if (createBtn && !createBtn.disabled) {
                createBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.createFolder(folder.path);
                });
            }
            
            const uploadBtn = folderItem.querySelector('.btn-upload-here');
            if (uploadBtn) {
                uploadBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.selectFolderForUpload(folder);
                });
            }
            
            const deleteBtn = folderItem.querySelector('.btn-delete-folder');
            if (deleteBtn) {
                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.deleteFolder(folder.path);
                });
            }
            
            // Recursively render children
            if (folder.children && folder.children.length > 0) {
                this.renderFolderTreeForManagement(folder.children, level + 1);
            }
        });
    }
    
    /**
     * Create a new folder
     */
    async createFolder(parentPath) {
        const folderName = prompt('新しいフォルダ名を入力してください:');
        if (!folderName) return;
        
        // parentPath が null の場合（ルート作成）、パスを直接使用
        const folderPath = parentPath === null ? folderName : `${parentPath}/${folderName}`;
        
        try {
            const response = await this.apiRequest(`${this.apiEndpoint}/folder-management`, {
                method: 'POST',
                body: JSON.stringify({
                    action: 'create',
                    folder_path: folderPath
                })
            });
            
            const result = await response.json();
            
            if (response.ok) {
                alert(result.message);
                this.fetchFolderTreeForManagement(); // Refresh
            } else {
                alert(`エラー: ${result.message}`);
            }
            
        } catch (error) {
            console.error('[Step0] Error creating folder:', error);
            alert(`フォルダの作成に失敗しました: ${error.message}`);
        }
    }
    
    /**
     * Delete a folder
     */
    async deleteFolder(folderPath) {
        if (!confirm(`フォルダ「${folderPath}」を削除してもよろしいですか？\n（中身が空の場合のみ削除できます）`)) {
            return;
        }
        
        try {
            const response = await this.apiRequest(`${this.apiEndpoint}/folder-management`, {
                method: 'POST',
                body: JSON.stringify({
                    action: 'delete',
                    folder_path: folderPath
                })
            });
            
            const result = await response.json();
            
            if (response.ok) {
                alert(result.message);
                this.fetchFolderTreeForManagement(); // Refresh
            } else {
                alert(result.message);
            }
            
        } catch (error) {
            console.error('[Step0] Error deleting folder:', error);
            alert(`フォルダの削除に失敗しました: ${error.message}`);
        }
    }
    
    /**
     * Select folder for file upload
     */
    selectFolderForUpload(folder) {
        this.selectedUploadFolder = folder;
        this.step0Elements.uploadTargetPath.textContent = folder.path;
        this.step0Elements.fileInputContainer.style.display = 'block';
        
        // Show processing mode options if folder is registered
        if (this.step0Elements.registeredFolderOptions) {
            if (folder.is_registered && folder.default_job_id) {
                this.step0Elements.registeredFolderOptions.style.display = 'block';
            } else {
                this.step0Elements.registeredFolderOptions.style.display = 'none';
            }
        }
        
        console.log('[Step0] Selected folder for upload:', folder);
    }
    
    /**
     * Upload files to S3
     */
    async uploadFiles() {
        if (!this.selectedUploadFolder) {
            alert('アップロード先のフォルダを選択してください');
            return;
        }
        
        const files = this.step0Elements.fileInput.files;
        if (files.length === 0) {
            alert('アップロードするファイルを選択してください');
            return;
        }
        
        console.log(`[Step0] Uploading ${files.length} files to ${this.selectedUploadFolder.path}`);
        
        try {
            // Show progress
            this.step0Elements.uploadProgress.style.display = 'block';
            this.step0Elements.uploadStatus.textContent = '署名付きURLを取得中...';
            this.step0Elements.uploadProgressFill.style.width = '10%';
            
            // Get presigned URLs
            const filenames = Array.from(files).map(f => f.name).join(',');
            const response = await this.apiRequest(
                `${this.apiEndpoint}/s3-presigned-urls?folder_path=${encodeURIComponent(this.selectedUploadFolder.path)}&filenames=${encodeURIComponent(filenames)}`,
                { method: 'GET' }
            );
            
            if (!response.ok) {
                throw new Error('署名付きURLの取得に失敗しました');
            }
            
            const { is_registered, default_job_id, urls } = await response.json();
            console.log('[Step0] Presigned URLs received:', { is_registered, default_job_id });
            
            // Upload files to S3
            this.step0Elements.uploadStatus.textContent = 'ファイルをアップロード中...';
            const totalFiles = files.length;
            let completedFiles = 0;
            
            for (const file of files) {
                const url = urls[file.name];
                
                await fetch(url, {
                    method: 'PUT',
                    body: file,
                    headers: {
                        'Content-Type': 'application/pdf'
                    }
                });
                
                completedFiles++;
                const progress = 10 + (completedFiles / totalFiles * 70);
                this.step0Elements.uploadProgressFill.style.width = `${progress}%`;
                this.step0Elements.uploadStatus.textContent = `ファイルをアップロード中... (${completedFiles}/${totalFiles})`;
            }
            
            console.log('[Step0] All files uploaded to S3');
            
            // Check if folder is registered
            if (is_registered && default_job_id) {
                // Trigger automatic processing
                this.step0Elements.uploadStatus.textContent = '自動処理を開始中...';
                this.step0Elements.uploadProgressFill.style.width = '90%';
                
                const uploadedFiles = Array.from(files).map(f => f.name);
                const uploadProcessingMode = this.step0Elements.uploadProcessingMode?.value || 'full';
                
                const triggerResponse = await this.apiRequest(`${this.apiEndpoint}/trigger-processing`, {
                    method: 'POST',
                    body: JSON.stringify({
                        folder_path: this.selectedUploadFolder.path,
                        job_id: default_job_id,
                        uploaded_files: uploadedFiles,
                        processing_mode: uploadProcessingMode
                    })
                });
                
                const triggerResult = await triggerResponse.json();
                
                this.step0Elements.uploadProgressFill.style.width = '100%';
                this.step0Elements.uploadStatus.textContent = triggerResult.message;
                
                alert(`✅ ${triggerResult.message}\n\nジョブID: ${default_job_id}\n\n進捗はステップ1以降で確認できます。`);
                
            } else {
                // Unregistered folder - notify user
                this.step0Elements.uploadProgressFill.style.width = '100%';
                this.step0Elements.uploadStatus.textContent = 'アップロード完了';
                
                alert(`✅ ${totalFiles}個のファイルをアップロードしました。\n\nナレッジ化するためにステップ1以降で処理を実行してください。`);
            }
            
            // Reset
            this.step0Elements.fileInput.value = '';
            setTimeout(() => {
                this.step0Elements.uploadProgress.style.display = 'none';
                this.step0Elements.uploadProgressFill.style.width = '0%';
            }, 3000);
            
        } catch (error) {
            console.error('[Step0] Error uploading files:', error);
            alert(`ファイルのアップロードに失敗しました: ${error.message}`);
            this.step0Elements.uploadProgress.style.display = 'none';
        }
    }
    
    stopPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
        this.elements.submitBtn.disabled = false;
    }
}

// Initialize app on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    // AppConfig から APIエンドポイントを取得
    const apiEndpoint = AppConfig.getApiEndpoint();
    
    if (!apiEndpoint) {
        const errorMsg = '❌ APIエンドポイントが設定されていません。\n\n以下のいずれかの方法で設定してください:\n1. 開発環境: frontend/.env.local に VITE_API_ENDPOINT を設定\n2. ローカルデバッグ: ブラウザコンソールで AppConfig.setApiEndpoint("https://...")を実行\n3. 本番環境: CloudFormation デプロイスクリプトが自動で設定します';
        console.error(errorMsg);
        throw new Error('API_ENDPOINT is not configured');
    }
    
    try {
        const app = new DoctoKnowApp({
            apiEndpoint: apiEndpoint
        });
        
        window.DoctoKnowApp = app;
        window.appInstance = app;
    } catch (error) {
        console.error('[DOMContentLoaded] Initialization error:', error);
        throw error;
    }
});
