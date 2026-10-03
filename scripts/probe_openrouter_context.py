"""Opt-in OpenRouter smoke test using a local .env and synthetic JPEG only.

This is not the recorded-video pipeline. Never print keys or raw model output.
"""
import argparse
import io
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image
from aba_demo.openrouter_context import OpenRouterContextAdapter, OpenRouterContextError

SMOKE_MODEL = 'dots-studio/dots-3-note-preview:free'


def read_local_key(path):
    """Read one explicit local credential; do not alter process environment."""
    try:
        with path.open('rb') as handle:
            contents = handle.read(8193)
    except FileNotFoundError:
        return None
    except OSError:
        raise ValueError('invalid_config') from None
    if len(contents) > 8192:
        raise ValueError('invalid_config')
    try:
        lines = contents.decode('utf-8-sig').splitlines()
    except UnicodeError:
        raise ValueError('invalid_config') from None
    values = [line.partition('=')[2] for line in lines
              if line.startswith('OPENROUTER_API_KEY=')]
    if len(values) > 1:
        raise ValueError('invalid_config')
    return values[0] if values and values[0] else None


def run_probe(*, key_path=None, model=SMOKE_MODEL, max_tokens=4096, transport=None):
    """Return only a stable status. Never serialize the credential or response."""
    try:
        key = read_local_key(key_path or ROOT / '.env')
    except ValueError:
        return 'invalid_config'
    if key is None:
        return 'provider_not_configured'
    buffer = io.BytesIO()
    Image.new('RGB', (64, 64), 'white').save(buffer, format='JPEG')
    jpeg = buffer.getvalue()
    frame = {'time': 0.0, 'identity': 'confirmed', 'scene_jpeg': jpeg,
             'target_crop_jpeg': jpeg, 'target_box': [0.1, 0.1, 0.9, 0.9]}
    try:
        OpenRouterContextAdapter(
            api_key=key, model=model, max_tokens=max_tokens,
            transport=transport,
        ).analyze([frame], source_sha256=sha256(jpeg).hexdigest())
    except OpenRouterContextError as error:
        return error.code
    finally:
        key = None
    return 'success'


def main():
    parser = argparse.ArgumentParser(description='Synthetic-image OpenRouter smoke test')
    parser.add_argument('--model', default=SMOKE_MODEL,
                        help='Replaceable model ID; not a credential')
    parser.add_argument('--max-tokens', type=int, default=4096)
    arguments = parser.parse_args()
    print('RESULT:', run_probe(model=arguments.model, max_tokens=arguments.max_tokens))


if __name__ == '__main__':
    main()
