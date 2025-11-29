import subprocess
import os

def fetch_git_source(url: str, ref: str, dest: str):
    """
    Clones a git repository to the destination directory and checks out the reference.
    """
    # Ensure destination does not exist or we might fail, 
    # but usually the temp dir created by executor is empty or we are passed a fresh path.
    
    # Clone
    cmd_clone = ["git", "clone", "-q", url, dest]
    subprocess.run(cmd_clone, check=True)
    
    # Checkout
    if ref:
        cmd_checkout = ["git", "checkout", ref]
        subprocess.run(cmd_checkout, cwd=dest, check=True)
