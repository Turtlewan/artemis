"""Speaker-ID adapter, encrypted voiceprint store, and test fake.

Voice-ID is identity routing, not authentication: a matched owner voice can
select owner scope, but it never unlocks the owner DEK. Stored voiceprints are
embeddings only, encrypted at rest under the Tier-0/general key so matching can
run while the owner-private scope remains locked.
"""

from __future__ import annotations

import json
import math
import os
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import artemis.paths as paths
from artemis.config import Settings
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import GENERAL, OWNER_PERSON_ID, OWNER_PRIVATE
from artemis.ports.types import PersonId, Vector
from artemis.ports.voice import SpeakerID

_DEFAULT_THRESHOLD = 0.25
_NONCE_BYTES = 12


class SpeakerIDError(Exception):
    """Raised when speaker-ID enrolment or matching fails."""


class _TensorLike(Protocol):
    def detach(self) -> _TensorLike:
        """Return a detached tensor-like object."""

    def cpu(self) -> _TensorLike:
        """Return a CPU tensor-like object."""

    def reshape(self, *shape: int) -> _TensorLike:
        """Return a reshaped tensor-like object."""

    def tolist(self) -> list[float]:
        """Return a flat list of floats."""


class _EcapaModel(Protocol):
    def encode_batch(self, waveform: object) -> object:
        """Encode a waveform tensor into an embedding tensor."""


class VoiceprintStore:
    """Encrypted per-person embedding store for speaker voiceprints."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider
        self._dir = paths.scope_dir(settings, OWNER_PRIVATE) / "voiceprints"

    def enrol(self, person_id: PersonId, embedding: Vector) -> None:
        """Encrypt and store one person's speaker embedding."""
        payload = json.dumps(
            {"person_id": str(person_id), "embedding": [float(v) for v in embedding]},
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = self._encrypt(payload)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._voiceprint_path(person_id).write_bytes(ciphertext)

    def all_voiceprints(self) -> Mapping[PersonId, Vector]:
        """Return all decrypted voiceprints keyed by person id."""
        if not self._dir.exists():
            return {}
        voiceprints: dict[PersonId, Vector] = {}
        for path in sorted(self._dir.glob("*.vp")):
            payload = self._decrypt(path.read_bytes())
            raw = json.loads(payload.decode("utf-8"))
            if not isinstance(raw, dict):
                raise SpeakerIDError("Invalid voiceprint payload")
            person_id = raw.get("person_id")
            embedding = raw.get("embedding")
            if not isinstance(person_id, str) or not isinstance(embedding, list):
                raise SpeakerIDError("Invalid voiceprint payload")
            voiceprints[PersonId(person_id)] = tuple(float(value) for value in embedding)
        return voiceprints

    def has_any(self) -> bool:
        """Return true when at least one encrypted voiceprint exists."""
        return self._dir.exists() and any(self._dir.glob("*.vp"))

    def _voiceprint_path(self, person_id: PersonId) -> Path:
        safe_id = str(person_id).replace("/", "_").replace("\\", "_")
        if not safe_id:
            raise ValueError("person_id must not be empty")
        return self._dir / f"{safe_id}.vp"

    def _encrypt(self, payload: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + AESGCM(self._tier0_key()).encrypt(nonce, payload, None)

    def _decrypt(self, payload: bytes) -> bytes:
        if len(payload) <= _NONCE_BYTES:
            raise SpeakerIDError("Invalid encrypted voiceprint")
        nonce = payload[:_NONCE_BYTES]
        ciphertext = payload[_NONCE_BYTES:]
        return AESGCM(self._tier0_key()).decrypt(nonce, ciphertext, None)

    def _tier0_key(self) -> bytes:
        """Return the Tier-0/general key used for pre-unlock identity routing."""
        return bytes.fromhex(self._key_provider.dek_for_scope(GENERAL).as_hex())


class EcapaSpeakerID:
    """SpeechBrain ECAPA-TDNN speaker-ID adapter."""

    def __init__(
        self,
        store: VoiceprintStore,
        *,
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> None:
        self._store = store
        self._threshold = threshold
        self._model: _EcapaModel | None = None

    def enrol(self, person_id: PersonId, audio: bytes) -> None:
        """Compute and store a speaker embedding from 16 kHz mono int16 PCM."""
        try:
            self._store.enrol(person_id, self._embed_audio(audio))
        except Exception as exc:
            raise SpeakerIDError("Speaker enrolment failed") from exc

    def identify(self, audio: bytes) -> PersonId | None:
        """Return the best matching person id, or None below the threshold."""
        try:
            candidates = self._store.all_voiceprints()
            if not candidates:
                return None
            query = self._embed_audio(audio)
            best_person: PersonId | None = None
            best_score = -1.0
            for person_id, embedding in candidates.items():
                score = _cosine(query, embedding)
                if score > best_score:
                    best_score = score
                    best_person = person_id
            if best_person is not None and best_score >= self._threshold:
                return best_person
            return None
        except Exception as exc:
            raise SpeakerIDError("Speaker identification failed") from exc

    def warmup(self) -> None:
        """Load the ECAPA model without processing audio."""
        self._load_ecapa()

    def _embed_audio(self, audio: bytes) -> Vector:
        if len(audio) < 2 or len(audio) % 2 != 0:
            raise SpeakerIDError("Audio must be 16-bit PCM bytes")
        model = self._load_ecapa()
        import torch  # type: ignore[import-not-found]

        sample_count = len(audio) // 2
        samples = struct.unpack(f"<{sample_count}h", audio)
        waveform = torch.tensor(
            [[sample / 32768.0 for sample in samples]],
            dtype=torch.float32,
        )
        encoded = model.encode_batch(waveform)
        return _flatten_embedding(encoded)

    def _load_ecapa(self) -> _EcapaModel:
        if self._model is None:
            try:
                import speechbrain.inference.speaker as speechbrain_speaker  # type: ignore[import-not-found]

                self._model = cast(
                    _EcapaModel,
                    speechbrain_speaker.EncoderClassifier.from_hparams(
                        source="speechbrain/spkrec-ecapa-voxceleb",
                        savedir="pretrained_models/spkrec-ecapa-voxceleb",
                    ),
                )
            except Exception as exc:
                raise SpeakerIDError("Unable to load SpeechBrain ECAPA model") from exc
        return self._model


class FakeSpeakerID:
    """Deterministic SpeakerID fake for tests and off-hardware flows."""

    def __init__(
        self,
        script: Mapping[bytes, PersonId | None] | Sequence[PersonId | None] | None = None,
    ) -> None:
        self._script_map: dict[bytes, PersonId | None] = {}
        self._script_list: list[PersonId | None] = []
        if isinstance(script, Mapping):
            self._script_map = dict(script)
        elif script is not None:
            self._script_list = list(script)
        self.enrolments: list[tuple[PersonId, bytes]] = []

    def enrol(self, person_id: PersonId, audio: bytes) -> None:
        """Record an enrolment call without model work."""
        self.enrolments.append((person_id, audio))

    def identify(self, audio: bytes) -> PersonId | None:
        """Return a scripted match for the supplied utterance."""
        if self._script_list:
            return self._script_list.pop(0)
        return self._script_map.get(audio)


def enrol_owner(audio_clips: Sequence[bytes], speaker_id: SpeakerID) -> None:
    """Enrol the owner from one or more clips through the SpeakerID seam."""
    for clip in audio_clips:
        speaker_id.enrol(OWNER_PERSON_ID, clip)  # type: ignore[attr-defined]


def _flatten_embedding(value: object) -> Vector:
    tensor = cast(_TensorLike, value)
    flattened = tensor.detach().cpu().reshape(-1).tolist()
    return tuple(float(item) for item in flattened)


def _cosine(left: Vector, right: Vector) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return -1.0
    return dot / (left_norm * right_norm)


_speaker_id_conformance: SpeakerID
