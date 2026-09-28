"""STEP -> GLB conversion for the 3D viewer.

`convert()` and `info()` are the whole surface; everything else in
`step.py` is an implementation detail. See `step.py`'s module docstring for
why the OpenCASCADE import is deferred and why conversions are cached by
content hash.
"""

from xforge.viewer.step import ModelInfo, convert, info

__all__ = ["ModelInfo", "convert", "info"]
