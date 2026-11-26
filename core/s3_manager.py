import boto3
import os
import mimetypes
import threading
import concurrent.futures
from botocore.config import Config
from boto3.s3.transfer import TransferConfig

# Standard optimal S3 transfer configuration: 8 MB chunks, concurrent parts
DEFAULT_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=8 * 1024 * 1024,
    max_concurrency=10,
    multipart_chunksize=8 * 1024 * 1024,
    use_threads=True
)

class S3Manager:
    def __init__(self, ak, sk, rg):
        # Configure connection pool with up to 50 reusable HTTP connections
        # to avoid pool exhaustion warnings during parallel transfers.
        boto_config = Config(max_pool_connections=50)
        self.client = boto3.client(
            's3', aws_access_key_id=ak, aws_secret_access_key=sk, region_name=rg, config=boto_config)
        self.resource = boto3.resource(
            's3', aws_access_key_id=ak, aws_secret_access_key=sk, region_name=rg, config=boto_config)

    def list_buckets(self):
        response = self.client.list_buckets()
        return response.get('Buckets', [])

    def list_objects(self, bucket, prefix):
        return self.client.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter='/')

    def download_file(self, bucket, key, local_path, progress_cb=None, known_size=None):
        total_size = known_size
        if total_size is None and progress_cb is not None:
            obj = self.client.head_object(Bucket=bucket, Key=key)
            total_size = obj.get('ContentLength', 0)
        
        class Progress:
            def __init__(self, _total, _cb):
                self.size = _total or 0
                self.seen = 0
                self.cb = _cb
            def __call__(self, bytes_amount):
                self.seen += bytes_amount
                if self.cb and self.size > 0:
                    self.cb(self.seen / self.size)

        self.client.download_file(
            Bucket=bucket, 
            Key=key, 
            Filename=local_path,
            Config=DEFAULT_TRANSFER_CONFIG,
            Callback=Progress(total_size, progress_cb) if progress_cb else None
        )

    def generate_presigned_url(self, bucket, key):
        return self.client.generate_presigned_url(
             'get_object',
             Params={'Bucket': bucket, 'Key': key},
             ExpiresIn=604800
        )

    def upload_file(self, bucket, prefix, file_path, storage_class="STANDARD", progress_cb=None):
        filename = os.path.basename(file_path)
        s3_key = f"{prefix}{filename}" if prefix else filename
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = "application/octet-stream"
        
        total_size = os.path.getsize(file_path)
        
        class Progress:
            def __init__(self, _total, _cb):
                self.size = _total
                self.seen = 0
                self.cb = _cb
            def __call__(self, bytes_amount):
                self.seen += bytes_amount
                if self.cb and self.size > 0:
                    self.cb(self.seen / self.size)
                    
        self.client.upload_file(
            file_path, bucket, s3_key,
            ExtraArgs={'ContentType': mime_type, 'StorageClass': storage_class},
            Config=DEFAULT_TRANSFER_CONFIG,
            Callback=Progress(total_size, progress_cb) if progress_cb else None
        )

    def rename_file(self, bucket, old_key, new_key):
        self.client.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': old_key}, Key=new_key)
        self.client.delete_object(Bucket=bucket, Key=old_key)

    def rename_folder(self, bucket, old_prefix, new_prefix):
        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=old_prefix):
            if 'Contents' in page:
                for obj in page['Contents']:
                    old_obj_key = obj['Key']
                    new_obj_key = old_obj_key.replace(old_prefix, new_prefix, 1)
                    self.client.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': old_obj_key}, Key=new_obj_key)
                    self.client.delete_object(Bucket=bucket, Key=old_obj_key)

    def delete_file(self, bucket, key):
        self.client.delete_object(Bucket=bucket, Key=key)

    def delete_files_batch(self, bucket, keys):
        """Delete multiple objects using S3's batch delete API (up to 1,000 per request)."""
        if not keys:
            return 0
        deleted_count = 0
        for i in range(0, len(keys), 1000):
            batch = [{'Key': k} for k in keys[i:i + 1000]]
            resp = self.client.delete_objects(Bucket=bucket, Delete={'Objects': batch, 'Quiet': True})
            errors = resp.get('Errors', [])
            deleted_count += len(batch) - len(errors)
        return deleted_count

    def delete_folder(self, bucket, prefix):
        paginator = self.client.get_paginator('list_objects_v2')
        keys = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if 'Contents' in page:
                for obj in page['Contents']:
                    keys.append(obj['Key'])
                    if len(keys) >= 1000:
                        self.client.delete_objects(Bucket=bucket, Delete={'Objects': [{'Key': k} for k in keys], 'Quiet': True})
                        keys.clear()
        if keys:
            self.client.delete_objects(Bucket=bucket, Delete={'Objects': [{'Key': k} for k in keys], 'Quiet': True})

    def create_folder(self, bucket, folder_key):
        self.client.put_object(Bucket=bucket, Key=folder_key)

    def move_object(self, src_bucket, src_key, tgt_bucket, tgt_key):
        self.client.copy_object(Bucket=tgt_bucket, CopySource={'Bucket': src_bucket, 'Key': src_key}, Key=tgt_key)
        self.client.delete_object(Bucket=src_bucket, Key=src_key)

    def move_folder(self, src_bucket, src_prefix, tgt_bucket, tgt_prefix):
        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=src_bucket, Prefix=src_prefix):
            if 'Contents' in page:
                for obj in page['Contents']:
                    old_obj_key = obj['Key']
                    new_obj_key = old_obj_key.replace(src_prefix, tgt_prefix, 1)
                    self.client.copy_object(Bucket=tgt_bucket, CopySource={'Bucket': src_bucket, 'Key': old_obj_key}, Key=new_obj_key)
                    self.client.delete_object(Bucket=src_bucket, Key=old_obj_key)

    def rename_folder_parallel(self, bucket, old_prefix, new_prefix,
                               max_workers=10, progress_cb=None):
        """Rename a folder using parallel copies + batch deletes.

        Phase 1: Copy all objects in parallel to the new prefix.
        Phase 2: Batch delete originals (skipped on copy error to avoid data loss).
        """
        paginator = self.client.get_paginator('list_objects_v2')
        keys = []
        for page in paginator.paginate(Bucket=bucket, Prefix=old_prefix):
            for obj in page.get('Contents', []):
                keys.append(obj['Key'])

        if not keys:
            return 0

        total = len(keys)
        completed = [0]
        lock = threading.Lock()

        def copy_one(old_key):
            new_key = old_key.replace(old_prefix, new_prefix, 1)
            self.client.copy_object(
                Bucket=bucket,
                CopySource={'Bucket': bucket, 'Key': old_key},
                Key=new_key)
            with lock:
                completed[0] += 1
                if progress_cb:
                    progress_cb(completed[0], total)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(copy_one, k) for k in keys]
            for f in concurrent.futures.as_completed(futs):
                f.result()  # raises on first error → skips delete phase

        # Phase 2: batch delete originals
        for i in range(0, len(keys), 1000):
            batch = [{'Key': k} for k in keys[i:i + 1000]]
            self.client.delete_objects(
                Bucket=bucket, Delete={'Objects': batch, 'Quiet': True})

        return total

    def move_folder_parallel(self, src_bucket, src_prefix, tgt_bucket, tgt_prefix,
                             max_workers=10, progress_cb=None):
        """Move a folder across buckets/prefixes using parallel copies + batch deletes."""
        paginator = self.client.get_paginator('list_objects_v2')
        keys = []
        for page in paginator.paginate(Bucket=src_bucket, Prefix=src_prefix):
            for obj in page.get('Contents', []):
                keys.append(obj['Key'])

        if not keys:
            return 0

        total = len(keys)
        completed = [0]
        lock = threading.Lock()

        def copy_one(old_key):
            new_key = old_key.replace(src_prefix, tgt_prefix, 1)
            self.client.copy_object(
                Bucket=tgt_bucket,
                CopySource={'Bucket': src_bucket, 'Key': old_key},
                Key=new_key)
            with lock:
                completed[0] += 1
                if progress_cb:
                    progress_cb(completed[0], total)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(copy_one, k) for k in keys]
            for f in concurrent.futures.as_completed(futs):
                f.result()

        # Batch delete from source
        for i in range(0, len(keys), 1000):
            batch = [{'Key': k} for k in keys[i:i + 1000]]
            self.client.delete_objects(
                Bucket=src_bucket, Delete={'Objects': batch, 'Quiet': True})

        return total
