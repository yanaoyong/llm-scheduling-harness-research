"""Freeze one official Codex model row; never discover credentials or user caches."""
import argparse
import hashlib
import json
from pathlib import Path

EDITS = dict(tool_mode='direct', use_responses_lite=False,
             experimental_supported_tools=[], apply_patch_tool_type=None,
             supports_search_tool=False, multi_agent_version=None)


def freeze(source, output, slug):
    output = Path(output).resolve()
    parents = Path(__file__).resolve().parents
    repository = next((p for p in parents if (p/'.git').exists()), parents[1])
    if output.is_relative_to(repository):
        raise ValueError('frozen catalog must be written outside the repository')
    catalog = json.loads(Path(source).read_bytes())
    rows = [row for row in catalog['models'] if row.get('slug') == slug]
    if len(rows) != 1:
        raise ValueError('requested slug must have exactly one source row')
    blob = (json.dumps({'models': [dict(rows[0], **EDITS)]}, ensure_ascii=False,
                       sort_keys=True, indent=2)+'\n').encode()
    output.write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--slug', required=True)
    args = parser.parse_args()
    print(freeze(args.source, args.output, args.slug))


if __name__ == '__main__': main()
