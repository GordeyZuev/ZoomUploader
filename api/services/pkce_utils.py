"""PKCE (Proof Key for Code Exchange) utilities for OAuth 2.0.

RFC 7636: https://datatracker.ietf.org/doc/html/rfc7636
"""

import base64
import hashlib
import secrets
import string


def generate_code_verifier(length: int = 128) -> str:
    """Generate a cryptographically random code_verifier.

    Args:
        length: Length of the code_verifier (43-128 characters)

    Returns:
        Random string consisting of [A-Z, a-z, 0-9, -, _, ~]

    Raises:
        ValueError: If length is not between 43 and 128
    """
    if not 43 <= length <= 128:
        raise ValueError("code_verifier length must be between 43 and 128")

    # Characters allowed in code_verifier
    alphabet = string.ascii_letters + string.digits + "-._~"

    # Generate random string
    code_verifier = "".join(secrets.choice(alphabet) for _ in range(length))

    return code_verifier


def generate_code_challenge(code_verifier: str, method: str = "S256") -> str:
    """Generate code_challenge from code_verifier.

    Args:
        code_verifier: The code verifier string
        method: Challenge method - 'S256' (SHA256) or 'plain'

    Returns:
        Base64 URL-encoded code_challenge

    Raises:
        ValueError: If method is not supported
    """
    if method == "plain":
        # Plain method - code_challenge = code_verifier
        return code_verifier
    elif method == "S256":
        # SHA256 method - code_challenge = BASE64URL(SHA256(ASCII(code_verifier)))
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()

        # Base64 URL encoding (without padding)
        code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

        return code_challenge
    else:
        raise ValueError(f"Unsupported code_challenge_method: {method}")


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge pair.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier, method="S256")

    return code_verifier, code_challenge

