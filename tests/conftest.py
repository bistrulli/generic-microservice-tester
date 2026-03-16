"""Shared fixtures for GMT tests."""

import ctypes
import pathlib

import pytest


@pytest.fixture(scope="session")
def busy_wait_lib():
    """Load the compiled busy_wait shared library.

    Looks for busy_wait.so in the src/ directory (local dev build).
    """
    src_dir = pathlib.Path(__file__).parent.parent / "src"
    so_path = src_dir / "busy_wait.so"

    if not so_path.exists():
        pytest.skip(
            f"busy_wait.so not found at {so_path}. "
            "Compile with: gcc -shared -fPIC -O2 -o src/busy_wait.so src/busy_wait.c"
        )

    lib = ctypes.CDLL(str(so_path))
    lib.busy_wait_cpu.argtypes = [ctypes.c_double]
    lib.busy_wait_cpu.restype = None
    return lib


@pytest.fixture()
def groundtruth_dir():
    """Path to the LQN ground truth test models."""
    return pathlib.Path(__file__).parent.parent / "test" / "lqn-groundtruth"
