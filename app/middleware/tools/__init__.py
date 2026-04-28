"""Auto-discovered tools for the middleware demo.

Drop a file into `patient/` or `clinician/`, decorate the function with
`@tool`, add one import line to the subpackage `__init__.py`. That's it.
"""

from . import clinician, patient  # noqa: F401 — import side effects register @tool

