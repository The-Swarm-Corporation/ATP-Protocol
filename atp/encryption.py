"""
Encryption utilities for ATP Protocol.

This module provides encryption/decryption functionality to protect agent
responses until payment is verified.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet
from loguru import logger


class ResponseEncryptor:
    """
    Encrypts and decrypts agent responses using Fernet symmetric encryption.
    
    The encryption key is derived from a secret that should be kept secure.
    In production, this should be set via environment variable.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize the encryptor.
        
        Args:
            encryption_key: Base64-encoded Fernet key. If not provided, generates
                a new key or uses ATP_ENCRYPTION_KEY from environment.
        """
        if encryption_key:
            self.key = encryption_key.encode()
        else:
            # Try to get from environment, or generate a new one
            env_key = os.getenv("ATP_ENCRYPTION_KEY")
            if env_key:
                self.key = env_key.encode()
            else:
                # Generate a new key (for development/testing)
                # In production, this should be set via environment variable
                logger.warning(
                    "No ATP_ENCRYPTION_KEY found in environment. "
                    "Generating a new key. This key will not persist across restarts."
                )
                self.key = Fernet.generate_key()
        
        try:
            self.fernet = Fernet(self.key)
        except Exception as e:
            raise ValueError(
                f"Invalid encryption key format: {e}. "
                "Key must be a valid base64-encoded Fernet key."
            )

    def encrypt(self, data: str) -> str:
        """
        Encrypt a string.
        
        Args:
            data: String to encrypt.
            
        Returns:
            Base64-encoded encrypted string.
        """
        encrypted = self.fernet.encrypt(data.encode())
        return base64.b64encode(encrypted).decode()

    def decrypt(self, encrypted_data: str) -> str:
        """
        Decrypt a string.
        
        Args:
            encrypted_data: Base64-encoded encrypted string.
            
        Returns:
            Decrypted string.
        """
        try:
            encrypted_bytes = base64.b64decode(encrypted_data.encode())
            decrypted = self.fernet.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise ValueError(f"Failed to decrypt data: {e}")

    def encrypt_response_data(
        self, response_data: Dict[str, Any], fields_to_encrypt: list[str] = None
    ) -> Dict[str, Any]:
        """
        Encrypt specific fields in a response dictionary.
        
        Args:
            response_data: Response dictionary containing agent output.
            fields_to_encrypt: List of field names to encrypt. Defaults to
                common output fields: ["output", "response", "result", "message"].
                
        Returns:
            Response dictionary with specified fields encrypted.
        """
        if fields_to_encrypt is None:
            fields_to_encrypt = ["output", "response", "result", "message"]
        
        encrypted_data = response_data.copy()
        
        for field in fields_to_encrypt:
            if field in encrypted_data and isinstance(
                encrypted_data[field], str
            ):
                encrypted_data[field] = self.encrypt(encrypted_data[field])
                # Mark as encrypted
                encrypted_data[f"{field}_encrypted"] = True
        
        return encrypted_data

    def decrypt_response_data(
        self, response_data: Dict[str, Any], fields_to_decrypt: list[str] = None
    ) -> Dict[str, Any]:
        """
        Decrypt specific fields in a response dictionary.
        
        Args:
            response_data: Response dictionary with encrypted fields.
            fields_to_decrypt: List of field names to decrypt. Defaults to
                common output fields: ["output", "response", "result", "message"].
                
        Returns:
            Response dictionary with specified fields decrypted.
        """
        if fields_to_decrypt is None:
            fields_to_decrypt = ["output", "response", "result", "message"]
        
        decrypted_data = response_data.copy()
        
        for field in fields_to_decrypt:
            if (
                field in decrypted_data
                and isinstance(decrypted_data[field], str)
                and decrypted_data.get(f"{field}_encrypted", False)
            ):
                try:
                    decrypted_data[field] = self.decrypt(decrypted_data[field])
                    # Remove encryption marker
                    decrypted_data.pop(f"{field}_encrypted", None)
                except Exception as e:
                    logger.error(
                        f"Failed to decrypt field '{field}': {e}"
                    )
                    # Keep encrypted if decryption fails
                    pass
        
        return decrypted_data

