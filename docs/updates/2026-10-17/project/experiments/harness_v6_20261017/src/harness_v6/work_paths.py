"""Keep generated verification artifacts outside the checkout and source inputs."""
from pathlib import Path


def checked_output(output, work_root, *, inputs=()):
    root = Path(work_root).resolve()
    destination = Path(output).resolve()
    checkout = next((p for p in Path(__file__).resolve().parents if (p / '.git').exists()),
                    Path(__file__).resolve().parents[2])
    if root.is_relative_to(checkout) or checkout.is_relative_to(root):
        raise ValueError('work root must be separate from the repository')
    if destination == root or not destination.is_relative_to(root):
        raise ValueError('output must be a child of the explicit work root')
    for source in inputs:
        source = Path(source).resolve()
        if destination.is_relative_to(source) or source.is_relative_to(destination):
            raise ValueError('output must not overlap source inputs')
    return destination
