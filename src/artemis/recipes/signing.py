"""HMAC signing for recipes using deterministic canonical bytes."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Protocol

from artemis.recipes.model import Recipe


class KeyProvider(Protocol):
    """Narrow signing-key seam for recipe integrity."""

    def signing_key(self) -> bytes:
        """Return the owner-held HMAC key."""
        ...


class RecipeSignatureError(Exception):
    """Raised when a recipe is unsigned or fails signature verification."""


class RecipeSigner:
    """Sign and verify recipes with HMAC-SHA256."""

    def __init__(self, key_provider: KeyProvider) -> None:
        self._key_provider = key_provider

    def canonical_bytes(self, recipe: Recipe) -> bytes:
        """Return deterministic bytes excluding the signature field."""
        payload = recipe.model_dump(exclude={"signature"})
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")

    def sign(self, recipe: Recipe) -> str:
        """Return a hex HMAC signature for a recipe."""
        return hmac.new(
            self._key_provider.signing_key(),
            self.canonical_bytes(recipe),
            hashlib.sha256,
        ).hexdigest()

    def verify(self, recipe: Recipe) -> bool:
        """Verify a recipe signature in constant time."""
        if recipe.signature is None:
            return False
        expected = self.sign(recipe)
        return hmac.compare_digest(expected, recipe.signature)
