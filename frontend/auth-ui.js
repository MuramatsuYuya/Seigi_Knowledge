/**
 * Authentication UI Controller
 * 
 * ログイン、登録、メール確認のUIを制御
 * 認証前はモーダル表示、認証後はメインコンテンツを表示
 */

class AuthUIController {
    constructor() {
        this.authManager = null;
        this.userPoolId = window.API_CONFIG?.cognitoUserPoolId || '';
        this.clientId = window.API_CONFIG?.cognitoClientId || '';
        this.region = window.API_CONFIG?.region || 'ap-northeast-1';
        this.isNewLogin = false; // ログイン成功時のみtrueに設定
        
        this.elements = {
            authModal: document.getElementById('authModal'),
            mainContent: document.getElementById('mainContent'),
            appHeader: document.getElementById('appHeader'),
            
            // Tabs
            authTabBtns: document.querySelectorAll('.auth-tab-btn'),
            authTabContents: document.querySelectorAll('.auth-tab-content'),
            
            // Login
            loginForm: document.getElementById('loginForm'),
            loginEmail: document.getElementById('loginEmail'),
            loginPassword: document.getElementById('loginPassword'),
            loginError: document.getElementById('loginError'),
            
            // SignUp
            signupForm: document.getElementById('signupForm'),
            signupEmail: document.getElementById('signupEmail'),
            signupPassword: document.getElementById('signupPassword'),
            signupPasswordConfirm: document.getElementById('signupPasswordConfirm'),
            signupError: document.getElementById('signupError'),
            signupSuccess: document.getElementById('signupSuccess'),
            
            // Confirm
            confirmForm: document.getElementById('confirmForm'),
            confirmEmail: document.getElementById('confirmEmail'),
            confirmCode: document.getElementById('confirmCode'),
            confirmError: document.getElementById('confirmError'),
            confirmSuccess: document.getElementById('confirmSuccess'),
            
            // Header
            userEmailDisplay: document.getElementById('userEmailDisplay'),
            logoutBtn: document.getElementById('logoutBtn'),
            appContent: document.querySelector('.container')
        };
        
        this.initialize();
    }
    
    initialize() {
        console.log('[AuthUIController] Initializing...');
        
        // Cognitoを初期化
        if (!this.userPoolId || !this.clientId) {
            console.error('[AuthUIController] Missing Cognito config. Waiting for API_CONFIG to be injected.');
            // デプロイスクリプトがAPI_CONFIGを注入するまで待機
            setTimeout(() => this.initialize(), 1000);
            return;
        }
        
        this.authManager = initializeAuthManager(this.userPoolId, this.clientId, this.region);
        
        // イベントリスナー設定
        this.attachEventListeners();
        
        // 既存のセッションをチェック
        this.checkExistingSession();
        
        // トークン有効期限の定期チェックを開始（5分ごと）
        this.startTokenExpiryCheck();
    }
    
    /**
     * トークン有効期限の定期チェック（サイレント）
     */
    startTokenExpiryCheck() {
        // 3分ごとにチェック（より頻繁に）
        setInterval(() => {
            if (!this.authManager.isAuthenticated()) {
                console.warn('[AuthUIController] Token expired during session - attempting silent refresh...');
                
                // サイレントにトークンのリフレッシュを試みる（ユーザーに通知しない）
                this.authManager.refreshAccessToken().then(result => {
                    if (result.success) {
                        console.log('[AuthUIController] Token refreshed silently');
                    } else {
                        // リフレッシュトークンも期限切れの場合のみログアウト
                        console.error('[AuthUIController] Silent token refresh failed - refresh token may be expired');
                        // ユーザーには次のAPI呼び出し時に認証画面が表示される
                    }
                });
            } else if (this.authManager.isTokenExpiringSoon()) {
                // 期限切れが近い場合、事前にリフレッシュ（サイレント）
                console.log('[AuthUIController] Token expiring soon, refreshing silently...');
                this.authManager.refreshAccessToken().then(result => {
                    if (result.success) {
                        console.log('[AuthUIController] Token refreshed proactively');
                    }
                });
            }
        }, 3 * 60 * 1000); // 3分ごと
        
        // 初回も即座にチェック（30秒後）
        setTimeout(() => {
            if (this.authManager.isTokenExpiringSoon()) {
                console.log('[AuthUIController] Initial token check - refreshing if needed...');
                this.authManager.refreshAccessToken();
            }
        }, 30 * 1000); // 30秒後
    }
    
    attachEventListeners() {
        // タブ切り替え
        this.elements.authTabBtns.forEach(btn => {
            btn.addEventListener('click', (e) => this.switchAuthTab(e.target.dataset.tab));
        });
        
        // フォーム送信
        this.elements.loginForm.addEventListener('submit', (e) => this.handleLogin(e));
        this.elements.signupForm.addEventListener('submit', (e) => this.handleSignUp(e));
        this.elements.confirmForm.addEventListener('submit', (e) => this.handleConfirm(e));
        
        // ログアウト
        this.elements.logoutBtn.addEventListener('click', () => this.handleLogout());
    }
    
    switchAuthTab(tabName) {
        // タブボタンのアクティブ状態を更新
        this.elements.authTabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });
        
        // タブコンテンツを表示/非表示
        this.elements.authTabContents.forEach(content => {
            content.classList.toggle('active', content.id === tabName + 'Tab');
        });
    }
    
    async handleLogin(e) {
        e.preventDefault();
        
        const email = this.elements.loginEmail.value.trim();
        const password = this.elements.loginPassword.value;
        
        this.clearErrorMessage('loginError');
        
        if (!email || !password) {
            this.showError('loginError', 'メールアドレスとパスワードを入力してください');
            return;
        }
        
        const result = await this.authManager.signIn(email, password);
        
        if (result.success) {
            console.log('[AuthUIController] Login successful');
            this.isNewLogin = true; // ログイン成功フラグを設定
            this.showAuthenticatedUI();
        } else {
            this.showError('loginError', result.message);
        }
    }
    
    async handleSignUp(e) {
        e.preventDefault();
        
        const email = this.elements.signupEmail.value.trim();
        const password = this.elements.signupPassword.value;
        const passwordConfirm = this.elements.signupPasswordConfirm.value;
        
        this.clearErrorMessage('signupError');
        this.clearSuccessMessage('signupSuccess');
        
        if (!email || !password || !passwordConfirm) {
            this.showError('signupError', '全ての項目を入力してください');
            return;
        }
        
        if (password !== passwordConfirm) {
            this.showError('signupError', 'パスワードが一致しません');
            return;
        }
        
        const result = await this.authManager.signUp(email, password);
        
        if (result.success) {
            this.showSuccess('signupSuccess', result.message);
            // フォームをクリア
            this.elements.signupForm.reset();
            
            // 確認タブに自動切り替え
            setTimeout(() => {
                this.switchAuthTab('confirm');
                this.elements.confirmEmail.value = email;
            }, 2000);
        } else {
            this.showError('signupError', result.message);
        }
    }
    
    async handleConfirm(e) {
        e.preventDefault();
        
        const email = this.elements.confirmEmail.value.trim();
        const confirmationCode = this.elements.confirmCode.value.trim();
        
        this.clearErrorMessage('confirmError');
        this.clearSuccessMessage('confirmSuccess');
        
        if (!email || !confirmationCode) {
            this.showError('confirmError', 'メールアドレスと確認コードを入力してください');
            return;
        }
        
        const result = await this.authManager.confirmSignUp(email, confirmationCode);
        
        if (result.success) {
            this.showSuccess('confirmSuccess', result.message);
            // フォームをクリア
            this.elements.confirmForm.reset();
            
            // ログインタブに自動切り替え
            setTimeout(() => {
                this.switchAuthTab('login');
                this.elements.loginEmail.value = email;
            }, 2000);
        } else {
            this.showError('confirmError', result.message);
        }
    }
    
    async handleLogout() {
        const confirmed = confirm('ログアウトしますか？');
        if (!confirmed) return;
        
        const result = await this.authManager.signOut();
        if (result.success) {
            this.showAuthenticationUI();
        } else {
            console.error('[AuthUIController] Logout failed:', result.message);
            this.showAuthenticationUI(); // エラーでも認証画面を表示
        }
    }
    
    checkExistingSession() {
        if (this.authManager.isAuthenticated()) {
            console.log('[AuthUIController] Existing session found');
            this.showAuthenticatedUI();
        } else {
            console.log('[AuthUIController] No existing session');
            this.showAuthenticationUI();
        }
    }
    
    showAuthenticationUI() {
        this.elements.authModal.style.display = 'flex';
        this.elements.appHeader.style.display = 'none';
        this.elements.mainContent.style.display = 'none';
    }
    
    showAuthenticatedUI() {
        // 新規ログインの場合のみknowledge-query.htmlにリダイレクト
        if (this.isNewLogin) {
            window.location.href = 'knowledge-query.html';
        } else {
            // 既存セッションの場合はindex.htmlのUIを表示
            this.elements.authModal.style.display = 'none';
            this.elements.appHeader.style.display = 'block';
            this.elements.mainContent.style.display = 'block';
            
            // ユーザーメールを表示（要素が存在する場合のみ）
            const userEmail = this.authManager.getUserEmail();
            if (this.elements.userEmailDisplay) {
                this.elements.userEmailDisplay.textContent = `ログイン中: ${userEmail}`;
            }
            
            // 既にDOMに追加されているコンテンツを表示
            if (!this.contentLoaded) {
                this.loadMainContent();
                this.contentLoaded = true;
            }
        }
    }
    
    loadMainContent() {
        // mainContentにHTMLコンテンツを追加
        // （このコンテンツはindex.htmlから移されているはず）
        // app.jsが実行されるため、追加の処理は不要
    }
    
    showError(elementId, message) {
        const element = document.getElementById(elementId);
        if (element) {
            element.textContent = '❌ ' + message;
            element.style.display = 'block';
        }
    }
    
    clearErrorMessage(elementId) {
        const element = document.getElementById(elementId);
        if (element) {
            element.textContent = '';
            element.style.display = 'none';
        }
    }
    
    showSuccess(elementId, message) {
        const element = document.getElementById(elementId);
        if (element) {
            element.textContent = '✅ ' + message;
            element.style.display = 'block';
        }
    }
    
    clearSuccessMessage(elementId) {
        const element = document.getElementById(elementId);
        if (element) {
            element.textContent = '';
            element.style.display = 'none';
        }
    }
}

// ページロード時に初期化
document.addEventListener('DOMContentLoaded', () => {
    console.log('[auth-ui.js] Initializing AuthUIController');
    window.authUIController = new AuthUIController();
});
