"""Recognize the bounded pip console wrappers supported by package preparation."""

import ast

_NORMALIZATIONS = (
    "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n",
    '    if sys.argv[0].endswith("-script.pyw"):\n'
    "        sys.argv[0] = sys.argv[0][:-11]\n"
    '    elif sys.argv[0].endswith(".exe"):\n'
    "        sys.argv[0] = sys.argv[0][:-4]\n",
)


def console_wrapper_matches(script: bytes, entry_point: str) -> bool:
    """Match imports, guarded dispatch, and the known argv normalization exactly."""
    try:
        module, attribute = entry_point.split(":", 1)
        if (
            not all(part.isidentifier() for part in module.split("."))
            or not attribute.isidentifier()
        ):
            return False
        observed = ast.dump(ast.parse(script), include_attributes=False)
        for index, normalization in enumerate(_NORMALIZATIONS):
            expected = (
                ("import re\n" if index == 0 else "")
                + "import sys\n"
                + f"from {module} import {attribute}\n"
                + "if __name__ == '__main__':\n"
                + normalization
                + f"    sys.exit({attribute}())\n"
            )
            if observed == ast.dump(ast.parse(expected), include_attributes=False):
                return True
        return False
    except (SyntaxError, ValueError, UnicodeError):
        return False
