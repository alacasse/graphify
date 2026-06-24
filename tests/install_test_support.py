"""Small helpers shared by product install tests."""
import os
from pathlib import Path
from unittest.mock import patch


def install_in_tmp(tmp_path, platform):
    from graphify.__main__ import install

    old_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with patch("graphify.__main__.Path.home", return_value=tmp_path):
            install(platform=platform)
    finally:
        os.chdir(old_cwd)


def agents_install(tmp_path, platform):
    from graphify.__main__ import _agents_install as _install_fn

    _install_fn(tmp_path, platform)


def agents_uninstall(tmp_path, platform=""):
    from graphify.__main__ import _agents_uninstall as _uninstall_fn

    _uninstall_fn(tmp_path, platform=platform)
