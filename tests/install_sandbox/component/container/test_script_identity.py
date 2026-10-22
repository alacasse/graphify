"""Executable identity follows parsed dispatch rather than matching text."""

import pytest

from tools.install_sandbox.contracts.script_identity import console_wrapper_matches

_WRAPPER = (
    "import re\nimport sys\nfrom candidate import main\n"
    "if __name__ == '__main__':\n"
    "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
    "    sys.exit(main())\n"
)


def test_known_wrapper_dispatches_declared_entry() -> None:
    assert console_wrapper_matches(_WRAPPER.encode(), "candidate:main")


@pytest.mark.parametrize(
    "malformed",
    [
        _WRAPPER.replace("from candidate import main", "# from candidate import main"),
        _WRAPPER.replace("sys.exit(main())", "sys.exit(other())"),
    ],
)
def test_textual_import_or_wrong_dispatch_is_rejected(malformed: str) -> None:
    assert not console_wrapper_matches(malformed.encode(), "candidate:main")


def test_known_slice_normalization_wrapper() -> None:
    script = (
        "import sys\nfrom candidate import main\nif __name__ == '__main__':\n"
        "    if sys.argv[0].endswith('-script.pyw'):\n"
        "        sys.argv[0] = sys.argv[0][:-11]\n"
        "    elif sys.argv[0].endswith('.exe'):\n"
        "        sys.argv[0] = sys.argv[0][:-4]\n"
        "    sys.exit(main())\n"
    )
    assert console_wrapper_matches(script.encode(), "candidate:main")
