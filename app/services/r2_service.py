# app/services/r2_service.py

import os
import boto3
import logging

logger = logging.getLogger(__name__)


class CloudflareR2Handler:
    def __init__(self):
        """Initialize R2 client with existing configuration."""
        self.s3_client = boto3.client(
            service_name='s3',
            endpoint_url=os.getenv('R2_ENDPOINT_URL'),
            aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
            region_name='weur'  # Western Europe region
        )
        self.bucket_name = 'multivio'

    async def delete_asset(self, key: str) -> bool:
        """
        Delete an asset from R2 storage.
        
        Args:
            key: The storage key of the asset to delete
            
        Returns:
            bool: True if deletion was successful, False otherwise
            
        Raises:
            Exception: If deletion fails
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=key
            )
            logger.info(f"Successfully deleted object with key: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete object with key {key}: {str(e)}")
            raise Exception(f"Failed to delete from R2: {str(e)}")

    async def delete_multiple_assets(self, keys: list[str]) -> dict:
        """
        Delete multiple assets from R2 storage.
        
        Args:
            keys: List of storage keys to delete
            
        Returns:
            dict: Results of deletion operations
        """
        results = {
            'successful': [],
            'failed': []
        }

        for key in keys:
            try:
                await self.delete_asset(key)
                results['successful'].append(key)
            except Exception as e:
                results['failed'].append({
                    'key': key,
                    'error': str(e)
                })

        return results
