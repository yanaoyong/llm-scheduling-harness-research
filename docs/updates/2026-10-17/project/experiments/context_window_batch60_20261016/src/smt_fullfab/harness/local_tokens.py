"""Offline, pinned text-token measurement; server alias mapping is unverified."""
from functools import lru_cache
from pathlib import Path
import hashlib
import sys

from .offline_isolation import ROOT


@lru_cache(maxsize=1)
def tokenizer():
    folder = ROOT / 'dependencies/python'
    sys.path.insert(0, str(folder))
    import tiktoken
    import tiktoken.load
    if not Path(tiktoken.__file__).resolve().is_relative_to(folder):
        raise RuntimeError('Only the pinned local tokenizer is permitted')
    def read_local(url, expected_hash=None):
        if not url.endswith('/o200k_base.tiktoken'):
            raise RuntimeError('Unregistered tokenizer vocabulary')
        raw = (ROOT / 'dependencies/encodings/o200k_base.tiktoken').read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d':
            raise RuntimeError('Tokenizer vocabulary changed')
        if expected_hash and actual != expected_hash:
            raise RuntimeError('Vocabulary hash does not match package')
        return raw
    tiktoken.load.read_file_cached = read_local
    return tiktoken.get_encoding('o200k_base')


def count(text):
    return len(tokenizer().encode_ordinary(text))

