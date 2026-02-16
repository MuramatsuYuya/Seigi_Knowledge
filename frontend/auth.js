/**
 * Cognito Authentication Module
 * 
 * メールアドレスとパスワードによる認証
 * - メール確認必須
 * - メールドメイン制限: @ad.melco.co.jp のみ
 * - パスワード要件: 英字のみ6文字以上（Cognito最小要件）
 */

class CognitoAuthManager {
    constructor(config = {}) {
        this.userPoolId = config.userPoolId || '';
        this.clientId = config.clientId || '';
        this.region = config.region || 'ap-northeast-1';
        this.cognitoIdentityServiceProvider = null;
        this.currentUser = null;
        this.sessionToken = null;
        
        // パスワード検証ルール
        this.PASSWORD_REGEX = /^[a-zA-Z]{6,}$/; // 英字のみ6文字以上
        this.ALLOWED_EMAIL_DOMAIN = '@ad.melco.co.jp';
        
        this.initializeAWS();
    }
    
    initializeAWS() {
        // AWS SDK v3は動的にロード
        if (typeof AWS !== 'undefined' && AWS.CognitoIdentityServiceProvider) {
            this.cognitoIdentityServiceProvider = new AWS.CognitoIdentityServiceProvider({
                region: this.region
            });
            console.log('[CognitoAuthManager] AWS SDK initialized');
        } else {
            console.warn('[CognitoAuthManager] AWS SDK not loaded. Please include AWS SDK script.');
        }
    }
    
    /**
     * パスワード検証: 英字のみ6文字以上（Cognito最小要件）
     */
    validatePassword(password) {
        if (!password || typeof password !== 'string') {
            return { valid: false, message: 'パスワードは必須です' };
        }
        
        if (password.length < 6) {
            return { valid: false, message: 'パスワードは6文字以上である必要があります' };
        }
        
        if (!this.PASSWORD_REGEX.test(password)) {
            return { valid: false, message: 'パスワードは英字のみで構成される必要があります（大文字小文字は区別しません）' };
        }
        
        return { valid: true, message: 'パスワードは有効です' };
    }
    
    /**
     * メールアドレス検証: @ad.melco.co.jp のみ許可
     */
    validateEmail(email) {
        if (!email || typeof email !== 'string') {
            return { valid: false, message: 'メールアドレスは必須です' };
        }
        
        // メール形式の基本チェック
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            return { valid: false, message: '有効なメールアドレス形式ではありません' };
        }
        
        // ドメイン制限チェック
        if (!email.endsWith(this.ALLOWED_EMAIL_DOMAIN)) {
            return { valid: false, message: `メールアドレスは ${this.ALLOWED_EMAIL_DOMAIN} で終わる必要があります` };
        }
        
        return { valid: true, message: 'メールアドレスは有効です' };
    }
    
    /**
     * ユーザー登録
     */
    async signUp(email, password) {
        // バリデーション
        const emailValidation = this.validateEmail(email);
        if (!emailValidation.valid) {
            return { success: false, message: emailValidation.message };
        }
        
        const passwordValidation = this.validatePassword(password);
        if (!passwordValidation.valid) {
            return { success: false, message: passwordValidation.message };
        }
        
        if (!this.cognitoIdentityServiceProvider) {
            return { success: false, message: 'AWS SDKが初期化されていません' };
        }
        
        try {
            const params = {
                ClientId: this.clientId,
                Username: email,
                Password: password,
                UserAttributes: [
                    {
                        Name: 'email',
                        Value: email
                    }
                ]
            };
            
            const response = await this.cognitoIdentityServiceProvider.signUp(params).promise();
            console.log('[CognitoAuthManager] SignUp successful:', response);
            
            return {
                success: true,
                message: 'ユーザー登録が完了しました。確認メールを確認してください。',
                userSub: response.UserSub
            };
        } catch (error) {
            console.error('[CognitoAuthManager] SignUp error:', error);
            return {
                success: false,
                message: this.parseError(error)
            };
        }
    }
    
    /**
     * メール確認コードの検証
     */
    async confirmSignUp(email, confirmationCode) {
        if (!this.cognitoIdentityServiceProvider) {
            return { success: false, message: 'AWS SDKが初期化されていません' };
        }
        
        try {
            const params = {
                ClientId: this.clientId,
                Username: email,
                ConfirmationCode: confirmationCode
            };
            
            await this.cognitoIdentityServiceProvider.confirmSignUp(params).promise();
            console.log('[CognitoAuthManager] ConfirmSignUp successful');
            
            return {
                success: true,
                message: 'メール確認が完了しました。ログインできます。'
            };
        } catch (error) {
            console.error('[CognitoAuthManager] ConfirmSignUp error:', error);
            return {
                success: false,
                message: this.parseError(error)
            };
        }
    }
    
    /**
     * ログイン
     */
    async signIn(email, password) {
        const emailValidation = this.validateEmail(email);
        if (!emailValidation.valid) {
            return { success: false, message: emailValidation.message };
        }
        
        if (!this.cognitoIdentityServiceProvider) {
            return { success: false, message: 'AWS SDKが初期化されていません' };
        }
        
        try {
            const params = {
                AuthFlow: 'USER_PASSWORD_AUTH',
                ClientId: this.clientId,
                AuthParameters: {
                    USERNAME: email,
                    PASSWORD: password
                }
            };
            
            const response = await this.cognitoIdentityServiceProvider.initiateAuth(params).promise();
            console.log('[CognitoAuthManager] SignIn response:', response);
            
            // チャレンジレスポンスの確認
            if (response.ChallengeName) {
                console.error('[CognitoAuthManager] Challenge required:', response.ChallengeName);
                return {
                    success: false,
                    message: `認証チャレンジが必要です: ${response.ChallengeName}`
                };
            }
            
            // AuthenticationResult の存在確認
            if (!response.AuthenticationResult) {
                console.error('[CognitoAuthManager] No AuthenticationResult in response:', response);
                return {
                    success: false,
                    message: '認証レスポンスが不正です。管理者に連絡してください。'
                };
            }
            
            // トークン保存
            this.sessionToken = response.AuthenticationResult.AccessToken;
            localStorage.setItem('cognito_access_token', this.sessionToken);
            localStorage.setItem('cognito_id_token', response.AuthenticationResult.IdToken);
            localStorage.setItem('cognito_refresh_token', response.AuthenticationResult.RefreshToken);
            localStorage.setItem('cognito_user_email', email);
            
            // トークン有効期限を記録 (AccessTokenは通常1時間有効)
            const expiresIn = response.AuthenticationResult.ExpiresIn || 3600; // デフォルト1時間
            const expiresAt = Date.now() + (expiresIn * 1000);
            localStorage.setItem('cognito_token_expires_at', expiresAt.toString());
            
            console.log('[CognitoAuthManager] SignIn successful, tokens saved');
            console.log('[CognitoAuthManager] Token expires at:', new Date(expiresAt).toLocaleString());
            
            return {
                success: true,
                message: 'ログインに成功しました',
                accessToken: this.sessionToken
            };
        } catch (error) {
            console.error('[CognitoAuthManager] SignIn error:', error);
            return {
                success: false,
                message: this.parseError(error)
            };
        }
    }
    
    /**
     * ログアウト
     */
    async signOut() {
        try {
            localStorage.removeItem('cognito_access_token');
            localStorage.removeItem('cognito_id_token');
            localStorage.removeItem('cognito_refresh_token');
            localStorage.removeItem('cognito_token_expires_at');
            localStorage.removeItem('cognito_user_email');
            this.sessionToken = null;
            console.log('[CognitoAuthManager] SignOut successful');
            return { success: true, message: 'ログアウトしました' };
        } catch (error) {
            console.error('[CognitoAuthManager] SignOut error:', error);
            return { success: false, message: 'ログアウトに失敗しました' };
        }
    }
    
    /**
     * 現在のセッション確認（有効期限も確認）
     */
    isAuthenticated() {
        const token = localStorage.getItem('cognito_access_token');
        if (!token) {
            return false;
        }
        
        // トークンの有効期限を確認
        const expiresAt = localStorage.getItem('cognito_token_expires_at');
        if (expiresAt) {
            const now = Date.now();
            const expiryTime = parseInt(expiresAt, 10);
            
            if (now >= expiryTime) {
                console.warn('[CognitoAuthManager] Token has expired');
                return false;
            }
        }
        
        return true;
    }
    
    /**
     * トークンが期限切れかチェック（5分前にも警告）
     */
    isTokenExpiringSoon() {
        const expiresAt = localStorage.getItem('cognito_token_expires_at');
        if (!expiresAt) {
            return false;
        }
        
        const now = Date.now();
        const expiryTime = parseInt(expiresAt, 10);
        const fiveMinutes = 5 * 60 * 1000;
        
        return (expiryTime - now) < fiveMinutes;
    }
    
    /**
     * リフレッシュトークンを使用してアクセストークンを更新
     */
    async refreshAccessToken() {
        const refreshToken = localStorage.getItem('cognito_refresh_token');
        if (!refreshToken) {
            console.error('[CognitoAuthManager] No refresh token available');
            return { success: false, message: 'リフレッシュトークンがありません' };
        }
        
        if (!this.cognitoIdentityServiceProvider) {
            return { success: false, message: 'AWS SDKが初期化されていません' };
        }
        
        try {
            const params = {
                AuthFlow: 'REFRESH_TOKEN_AUTH',
                ClientId: this.clientId,
                AuthParameters: {
                    REFRESH_TOKEN: refreshToken
                }
            };
            
            const response = await this.cognitoIdentityServiceProvider.initiateAuth(params).promise();
            console.log('[CognitoAuthManager] Token refresh successful');
            
            if (!response.AuthenticationResult) {
                return { success: false, message: 'トークンのリフレッシュに失敗しました' };
            }
            
            // 新しいトークンを保存
            this.sessionToken = response.AuthenticationResult.AccessToken;
            const newIdToken = response.AuthenticationResult.IdToken;
            localStorage.setItem('cognito_access_token', this.sessionToken);
            localStorage.setItem('cognito_id_token', newIdToken);
            
            // 有効期限を更新
            const expiresIn = response.AuthenticationResult.ExpiresIn || 3600;
            const expiresAt = Date.now() + (expiresIn * 1000);
            localStorage.setItem('cognito_token_expires_at', expiresAt.toString());
            
            console.log('[CognitoAuthManager] New token expires at:', new Date(expiresAt).toLocaleString());
            
            return {
                success: true,
                message: 'トークンを更新しました',
                accessToken: this.sessionToken,
                idToken: newIdToken
            };
        } catch (error) {
            console.error('[CognitoAuthManager] Token refresh error:', error);
            
            // リフレッシュトークンも期限切れの場合、全てクリア
            if (error.code === 'NotAuthorizedException') {
                await this.signOut();
            }
            
            return {
                success: false,
                message: this.parseError(error)
            };
        }
    }
    
    /**
     * ユーザーメール取得
     */
    getUserEmail() {
        return localStorage.getItem('cognito_user_email');
    }
    
    /**
     * アクセストークン取得（有効期限チェック付き）
     */
    async getAccessToken() {
        // トークンが期限切れの場合、自動的にリフレッシュ
        if (!this.isAuthenticated()) {
            console.log('[CognitoAuthManager] Token expired, attempting refresh...');
            const refreshResult = await this.refreshAccessToken();
            if (!refreshResult.success) {
                console.error('[CognitoAuthManager] Failed to refresh token');
                return null;
            }
        }
        
        return localStorage.getItem('cognito_access_token');
    }
    
    /**
     * IDトークン取得（有効期限チェック付き）
     * API Gateway Cognito Authorizerに必要
     */
    async getIdToken() {
        // トークンが期限切れの場合、自動的にリフレッシュ
        if (!this.isAuthenticated()) {
            console.log('[CognitoAuthManager] Token expired, attempting refresh...');
            const refreshResult = await this.refreshAccessToken();
            if (!refreshResult.success) {
                console.error('[CognitoAuthManager] Failed to refresh token');
                return null;
            }
        }
        
        return localStorage.getItem('cognito_id_token');
    }
    
    /**
     * Cognito エラーメッセージをパース
     */
    parseError(error) {
        const errorCode = error.code || error.name;
        
        const errorMessages = {
            'UsernameExistsException': 'このメールアドレスは既に登録されています',
            'InvalidPasswordException': 'パスワードが要件を満たしていません',
            'UserNotFoundException': 'このユーザーは登録されていません',
            'NotAuthorizedException': 'メールアドレスまたはパスワードが正しくありません',
            'UserNotConfirmedException': 'メール確認がまだ完了していません',
            'CodeMismatchException': '確認コードが正しくありません',
            'ExpiredCodeException': '確認コードの有効期限が切れています',
            'TooManyRequestsException': 'リクエストが多すぎます。しばらく待ってから再度お試しください'
        };
        
        return errorMessages[errorCode] || error.message || 'エラーが発生しました';
    }
}

/**
 * ローカルストレージからCognito設定を取得
 */
function initializeAuthManager(userPoolId, clientId, region = 'ap-northeast-1') {
    return new CognitoAuthManager({
        userPoolId: userPoolId,
        clientId: clientId,
        region: region
    });
}

// グローバルに公開
window.CognitoAuthManager = CognitoAuthManager;
window.initializeAuthManager = initializeAuthManager;
