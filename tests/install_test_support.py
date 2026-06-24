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
