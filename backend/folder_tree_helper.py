"""
Folder Tree Helper
S3バケットからフォルダ構造を抽出
"""
import boto3
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
S3_BUCKET = os.environ['S3_BUCKET']


def get_folder_tree():
    """
    S3バケットのフォルダ構造を階層的に取得
    
    フォルダ検出方法:
    1. PDFファイルから検出されるフォルダ
    2. .folder_marker から検出されるフォルダ（新規作成時、ファイルがまだない場合）
    
    Returns:
        [
            {
                "name": "生技資料",
                "path": "生技資料",
                "is_leaf": False,
                "children": [
                    {
                        "name": "生技25",
                        "path": "生技資料/生技25",
                        "is_leaf": False,
                        "children": [...]
                    }
                ]
            }
        ]
    """
    try:
        logger.info("Starting folder tree extraction from S3")
        all_folders = set()
        folders_with_files = set()  # ファイルを含むフォルダを追跡
        continuation_token = None
        
        # S3のPDF/配下のすべてのオブジェクトを取得
        while True:
            list_params = {
                'Bucket': S3_BUCKET,
                'Prefix': 'PDF/',
                'Delimiter': ''
            }
            
            if continuation_token:
                list_params['ContinuationToken'] = continuation_token
            
            response = s3_client.list_objects_v2(**list_params)
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    key = obj['Key']
                    
                    # 方法1: PDFファイルから検出
                    if key.startswith('PDF/') and key.endswith('.pdf'):
                        parts = key[4:].split('/')  # PDF/ を除去
                        
                        # job_id を識別（14桁の数字）してフォルダパスを抽出
                        folder_parts = []
                        for part in parts[:-1]:  # 最後はファイル名
                            if len(part) == 14 and part.isdigit():
                                break
                            folder_parts.append(part)
                        
                        if folder_parts:
                            folder_path = '/'.join(folder_parts)
                            all_folders.add(folder_path)
                            folders_with_files.add(folder_path)  # ファイル有りとマーク
                            
                            # 中間フォルダも追加
                            for i in range(1, len(folder_parts)):
                                parent_path = '/'.join(folder_parts[:i])
                                all_folders.add(parent_path)
                    
                    # 方法2: .folder_marker から検出（新規作成時、ファイルがまだない場合）
                    elif key.startswith('PDF/') and key.endswith('/.folder_marker'):
                        # PDF/folder_path/.folder_marker の形式
                        folder_path = key[4:-len('/.folder_marker')]  # PDF/ と /.folder_marker を除去
                        
                        if folder_path:  # 空ではないことを確認
                            all_folders.add(folder_path)
                            
                            # 親フォルダも追加
                            parts = folder_path.split('/')
                            for i in range(1, len(parts)):
                                parent_path = '/'.join(parts[:i])
                                all_folders.add(parent_path)
            
            if not response.get('IsTruncated'):
                break
            
            continuation_token = response.get('NextContinuationToken')
        
        logger.info(f"Found {len(all_folders)} unique folders, {len(folders_with_files)} with files")
        
        # フォルダ情報を構築
        folder_dict = {}
        for folder_path in sorted(all_folders):
            parts = folder_path.split('/')
            folder_dict[folder_path] = {
                'name': parts[-1],
                'path': folder_path,
                'is_leaf': folder_path in folders_with_files,  # ファイルがあれば is_leaf=True
                'children': []
            }
        
        # 親子関係を判定してis_leafを更新
        # is_leaf=false にする条件: 子フォルダがある場合
        for folder_path in all_folders:
            prefix = folder_path + '/'
            for other_path in all_folders:
                if other_path.startswith(prefix) and other_path != folder_path:
                    remaining = other_path[len(prefix):]
                    if '/' not in remaining:
                        # 直下に子フォルダがある → is_leaf=False
                        folder_dict[folder_path]['is_leaf'] = False
                        break
        
        # can_delete フラグを判定
        # 削除可能条件: ファイルなし AND 子孫フォルダなし
        for folder_path in all_folders:
            prefix = folder_path + '/'
            has_descendants = False
            has_files = folder_path in folders_with_files
            
            # 子孫フォルダの有無をチェック
            for other_path in all_folders:
                if other_path.startswith(prefix) and other_path != folder_path:
                    has_descendants = True
                    break
            
            # 削除可能 = ファイルなし AND 子孫フォルダなし
            folder_dict[folder_path]['can_delete'] = not has_files and not has_descendants
        
        # 階層構造を構築
        def build_tree(parent_path):
            children = []
            prefix = parent_path + '/' if parent_path else ''
            
            for folder_path in sorted(all_folders):
                if folder_path == parent_path:
                    continue
                
                if folder_path.startswith(prefix):
                    remaining = folder_path[len(prefix):]
                    if '/' not in remaining:
                        folder_info = folder_dict[folder_path].copy()
                        folder_info['children'] = build_tree(folder_path)
                        children.append(folder_info)
            
            return children
        
        # ルートフォルダから構築
        root_folders = [fp for fp in sorted(all_folders) if '/' not in fp]
        tree = []
        for root_path in root_folders:
            folder_info = folder_dict[root_path].copy()
            folder_info['children'] = build_tree(root_path)
            tree.append(folder_info)
        
        logger.info(f"Built folder tree with {len(tree)} root folders")
        return tree
        
    except Exception as e:
        logger.error(f"Error building folder tree: {e}", exc_info=True)
        raise
