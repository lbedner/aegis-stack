"""Form fields with one look, so a form reads as a form.

A package rather than one module, one file per kind of input.

Every name the rest of the app imported from ``controls.form_fields``
is re-exported here, including the three private ones other modules
had already reached for - ``_build_label`` (controls.pickers builds
its trigger label with it), ``_CLEAR_HIT_SIZE`` (a test asserts the
hit box), and the ``FormVariant`` alias. Splitting the module is not
the moment to renegotiate who may import what.
"""

from app.components.frontend.controls.form_fields.actions import FormActionButtons
from app.components.frontend.controls.form_fields.date import FormDateField
from app.components.frontend.controls.form_fields.dropdown import FormDropdown
from app.components.frontend.controls.form_fields.shared import (
    FormVariant,
    _build_label as _build_label,
    input_field_kwargs,
)
from app.components.frontend.controls.form_fields.secret import FormSecretField
from app.components.frontend.controls.form_fields.text import (
    FormTextField,
    _CLEAR_HIT_SIZE as _CLEAR_HIT_SIZE,
)

__all__ = [
    "FormActionButtons",
    "FormDateField",
    "FormDropdown",
    "FormSecretField",
    "FormTextField",
    "FormVariant",
    "input_field_kwargs",
]
