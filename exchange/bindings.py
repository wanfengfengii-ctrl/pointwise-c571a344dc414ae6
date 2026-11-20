from hashlib import sha256


def item_identity(item: bytes) -> str:
    return sha256(item).hexdigest()


def build_directory(batch_id: str, revision_id: str, payload: bytes) -> dict[str, str]:
    return {
        'batch_id': batch_id,
        'revision_id': revision_id,
        'payload_sha256': sha256(payload).hexdigest(),
    }


def verify_directory(directory: object, batch_id: str, revision_id: str, payload: bytes) -> None:
    if not isinstance(directory, dict) or directory != build_directory(batch_id, revision_id, payload):
        raise ValueError('directory does not bind the declared batch, revision and payload')
