import boto3
import os
import mimetypes
from boto3.s3.transfer import TransferConfig

class S3Manager:
    def __init__(self, ak, sk, rg):
        self.client = boto3.client('s3', aws_access_key_id=ak, aws_secret_access_key=sk, region_name=rg)
        self.resource = boto3.resource('s3', aws_access_key_id=ak, aws_secret_access_key=sk, region_name=rg)

    def list_buckets(self):
        response = self.client.list_buckets()
        return response.get('Buckets', [])

    def list_objects(self, bucket, prefix):
        return self.client.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter='/')

    def download_file(self, bucket, key, local_path, progress_cb=None):
        config = TransferConfig(multipart_threshold=1024*25, max_concurrency=10, multipart_chunksize=1024*25, use_threads=True)
        class Progress:
            def __init__(self, _total, _cb):
                self.size = _total
                self.seen = 0
                self.cb = _cb
            def __call__(self, bytes_amount):
                self.seen += bytes_amount
                if self.cb and self.size > 0:
                    self.cb(self.seen / self.size)
                    
        obj = self.client.head_object(Bucket=bucket, Key=key)
        total_size = obj['ContentLength']
        
        self.client.download_file(
            Bucket=bucket, 
            Key=key, 
            Filename=local_path,
            Config=config,
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
        config = TransferConfig(multipart_threshold=1024*25, max_concurrency=10, multipart_chunksize=1024*25, use_threads=True)
        
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
            Config=config,
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

    def delete_folder(self, bucket, prefix):
        self.resource.Bucket(bucket).objects.filter(Prefix=prefix).delete()

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
