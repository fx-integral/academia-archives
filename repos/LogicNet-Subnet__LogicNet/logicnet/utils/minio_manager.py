from minio import Minio
from minio.error import S3Error
import os
import time
import glob

class MinioManager:
    def __init__(self, minio_endpoint, access_key, secret_key):
        self.minio_endpoint = minio_endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        
        self.minio_client = self.initialize_minio_client()

    def initialize_minio_client(self) -> Minio:
        """Initialize and return MinIO client."""
        return Minio(
            self.minio_endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=False  # Set to True if using HTTPS
        )
    
    def ensure_bucket_exists(self, bucket_name):
        """Check if bucket exists, create if it doesn't."""
        try:
            if not self.minio_client.bucket_exists(bucket_name):
                self.minio_client.make_bucket(bucket_name)
                print(f"Bucket '{bucket_name}' created")
            else:
                print(f"Bucket '{bucket_name}' already exists")
        except S3Error as e:
            print(f"Error checking/creating bucket: {e}")
            raise

    def upload_file(self, file_path, bucket_name, minio_folder_path):
        """Upload a single file to MinIO."""
        self.ensure_bucket_exists(bucket_name)
        try:
            object_name = os.path.basename(file_path)
            if not os.path.exists(file_path):
                print(f"File '{file_path}' not found, skipping")
                return False
            self.minio_client.fput_object(bucket_name, f"{minio_folder_path}/{object_name}", file_path)
            print(f"Uploaded '{file_path}' to bucket '{bucket_name}' as '{object_name}'")
            return True
        except S3Error as e:
            print(f"Error uploading '{file_path}': {e}")
            return False
        except Exception as e:
            print(f"Unexpected error uploading '{file_path}': {e}")
            return False
        
    def get_uploaded_files(self, bucket_name):
        """Get list of files already uploaded to MinIO."""
        try:
            objects = self.minio_client.list_objects(bucket_name, recursive=True)
            return {obj.object_name for obj in objects}
        except S3Error as e:
            print(f"Error listing objects in bucket: {e}")
            return set()