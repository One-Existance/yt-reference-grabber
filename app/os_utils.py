"""Windows shell helpers."""

import ctypes
import os

_ole32 = ctypes.windll.ole32
_shell32 = ctypes.windll.shell32

_shell32.ILCreateFromPathW.restype = ctypes.c_void_p
_shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
_shell32.ILFree.argtypes = [ctypes.c_void_p]
_shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long
_shell32.SHOpenFolderAndSelectItems.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_ulong,
]


def reveal_in_explorer(filepath):
    """Open File Explorer with filepath selected/highlighted in its folder.

    Uses the shell API directly rather than shelling out to explorer.exe
    with "/select,<path>" - that approach is unreliable for paths with
    spaces because of how Windows re-quotes the argument, and silently
    falls back to opening a default folder instead of failing loudly.
    """
    filepath = os.path.abspath(filepath)
    folder = os.path.dirname(filepath)

    _ole32.CoInitialize(None)
    try:
        pidl = _shell32.ILCreateFromPathW(filepath)
        if not pidl:
            os.startfile(folder)
            return
        try:
            _shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        finally:
            _shell32.ILFree(pidl)
    except Exception:
        os.startfile(folder)
    finally:
        _ole32.CoUninitialize()
