"""
Encryption utilities for secure storage of OAuth tokens and other sensitive data.
"""

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


class TokenEncryption:
    """Handles encryption/decryption of OAuth tokens using Fernet symmetric encryption."""

    _fernet = None

    @classmethod
    def _get_fernet(cls) -> Fernet:
        """Get or create Fernet instance with configured key."""
        if cls._fernet is None:
            key = current_app.config.get("QB_ENCRYPTION_KEY")
            if not key:
                raise ValueError(
                    "QB_ENCRYPTION_KEY not configured. Generate one with: "
                    "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
            # Ensure key is bytes
            if isinstance(key, str):
                key = key.encode()
            cls._fernet = Fernet(key)
        return cls._fernet

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """
        Encrypt a string, return base64-encoded ciphertext.

        Args:
            plaintext: The string to encrypt

        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return ""
        f = cls._get_fernet()
        return f.encrypt(plaintext.encode()).decode()

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """
        Decrypt base64-encoded ciphertext, return plaintext.

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If decryption fails (key may have changed)
        """
        if not ciphertext:
            return ""
        f = cls._get_fernet()
        try:
            return f.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            raise ValueError("Failed to decrypt token - encryption key may have changed")

    @classmethod
    def reset(cls):
        """Reset the cached Fernet instance (useful for testing)."""
        cls._fernet = None
