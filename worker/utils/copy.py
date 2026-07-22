import os
import shutil


def fetch_copy_source(src: str, dest: str) -> None:
    """
    Copy a local file or directory to the destination directory.

    If *src* is a file, the file is copied into *dest* (preserving the
    filename).  If *src* is a directory, the entire tree is copied into
    *dest*.

    *src* must be an absolute path.

    Raises ValueError when *src* is not absolute.
    Raises FileNotFoundError when *src* does not exist.
    """
    # Accept POSIX-style absolute paths on Windows as well. Hydra job
    # definitions are commonly shared between Linux and Windows workers.
    if not (os.path.isabs(src) or src.startswith(("/", "\\"))):
        raise ValueError(f"Copy source path must be absolute, got: {src!r}")
    if not os.path.exists(src):
        raise FileNotFoundError(f"Copy source path not found: {src}")

    if os.path.isfile(src):
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
    elif os.path.isdir(src):
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        raise ValueError(f"Copy source is not a regular file or directory: {src}")
