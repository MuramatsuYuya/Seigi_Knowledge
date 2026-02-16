/**
 * Application Configuration
 * 
 * Security Note:
 * - APIエンドポイントはCloudFront経由でアクセスされます
 * - 相対パス /api/* を使用することで、実際のAPI Gateway URLを隠します
 * - 開発環境では環境変数から読み込みます
 */

console.log('[config.js] Loading...');

class AppConfig {
    static DEFAULT_API_ENDPOINT = null; // Will be set by deployment script or runtime config
    static USE_CLOUDFRONT_PROXY = true; // CloudFront プロキシ経由でAPI呼び出し
    
    /**
     * APIエンドポイントを取得します
     * CloudFront 経由でプロキシされている場合は相対パスを返します
     * 
     * 優先度:
     * 1. CloudFront プロキシ モード（本番環境推奨）
     * 2. localStorage.apiEndpoint (ユーザーが明示的に設定)
     * 3. window.API_CONFIG?.endpoint (ランタイムインジェクション)
     * 4. 本番環境では import.meta は使用不可（static deployの場合）
     */
    static getApiEndpoint() {
        // 1. CloudFront プロキシ モード（本番環境）
        if (this.USE_CLOUDFRONT_PROXY) {
            console.log('[AppConfig] Using CloudFront proxy mode: /api');
            return '/api';
        }
        
        // 2. localStorage (ユーザーが明示的に設定した場合)
        const storedEndpoint = localStorage.getItem('apiEndpoint');
        if (storedEndpoint) {
            console.log('[AppConfig] Using API endpoint from localStorage');
            return storedEndpoint;
        }
        
        // 3. Runtime injection (S3デプロイされたHTMLから注入)
        if (window.API_CONFIG?.endpoint) {
            console.log('[AppConfig] Using API endpoint from runtime config');
            return window.API_CONFIG.endpoint;
        }
        
        // 4. デフォルト値
        return this.DEFAULT_API_ENDPOINT;
    }
    
    /**
     * CloudFront プロキシ モードを切り替える
     * デバッグ用途
     */
    static setUseCloudFrontProxy(enabled) {
        this.USE_CLOUDFRONT_PROXY = enabled;
        if (enabled) {
            console.log('[AppConfig] CloudFront proxy mode enabled');
        } else {
            console.log('[AppConfig] CloudFront proxy mode disabled');
        }
    }
    
    /**
     * APIエンドポイントをユーザーが手動で設定する
     * (デバッグ用途、または自動設定が失敗した場合の回復方法)
     */
    static setApiEndpoint(endpoint) {
        if (!endpoint || typeof endpoint !== 'string') {
            throw new Error('Invalid API endpoint');
        }
        
        if (!endpoint.startsWith('https://') && !endpoint.startsWith('/')) {
            throw new Error('API endpoint must use HTTPS or be a relative path');
        }
        
        localStorage.setItem('apiEndpoint', endpoint);
        this.setUseCloudFrontProxy(false); // CloudFront プロキシを無効化
        console.log('[AppConfig] API endpoint set in localStorage (for development/debugging only)');
    }
    
    /**
     * APIエンドポイント設定をクリア
     */
    static clearApiEndpoint() {
        localStorage.removeItem('apiEndpoint');
        console.log('[AppConfig] API endpoint cleared from localStorage');
    }
    
    /**
     * 設定情報をコンソールに出力（デバッグ用）
     */
    static debugPrintConfig() {
        console.group('[AppConfig] Configuration Debug Info');
        console.log('USE_CLOUDFRONT_PROXY:', this.USE_CLOUDFRONT_PROXY);
        console.log('localStorage.apiEndpoint:', localStorage.getItem('apiEndpoint') || '(not set)');
        console.log('window.API_CONFIG.endpoint:', window.API_CONFIG?.endpoint || '(not set)');
        console.log('Final API endpoint:', this.getApiEndpoint());
        console.groupEnd();
    }
}

// 本番環境でも利用可能にする（グローバル公開）
// 開発環境でも本番環境でも always グローバルに公開
window.AppConfig = AppConfig;
console.log('[config.js] Loaded successfully. AppConfig available as window.AppConfig');
