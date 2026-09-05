import os
import shutil
import uuid
import sqlite3
import urllib.parse
from typing import Optional
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from google import genai  # Official Google GenAI SDK

app = FastAPI(title="Abdur AI Universal Assistant")

# Uploads directory setup
UPLOAD_DIR = "/tmp/uploads"
import os; UPLOAD_DIR = "/tmp/uploads" if os.environ.get("VERCEL") else "uploads"; 
try: import os; os.makedirs(UPLOAD_DIR, exist_ok=True) if not os.path.exists(UPLOAD_DIR) else None 
except Exception: pass
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Static directory setup (Added to fix logo/images)
STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Configure GEMINI_API_KEY through the environment in local and hosted deployments.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    client = None

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            message TEXT,
            file_path TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions (id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

@app.get("/")
def read_index():
    if os.path.exists("templates/index.html"):
        return FileResponse("templates/index.html")
    return HTMLResponse("<h3>Error: index.html file missing in templates folder! Please make sure it is inside the 'templates' directory.</h3>")

@app.get("/sessions")
def get_sessions():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM sessions ORDER BY rowid DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1]} for r in rows]

@app.post("/sessions")
def create_session():
    session_id = str(uuid.uuid4())
    title = "New Chat"
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, title) VALUES (?, ?)", (session_id, title))
    conn.commit()
    conn.close()
    return {"session_id": session_id}

@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT role, message, file_path FROM messages WHERE session_id = ?", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r[0], "message": r[1], "file_path": r[2]} for r in rows]

@app.post("/chat-stream")
async def chat_stream(
    session_id: str = Form(...),
    message: str = Form(...),
    web_search: bool = Form(False),
    file: Optional[UploadFile] = File(None)
):
    file_url = None
    if file:
        file_ext = os.path.splitext(file.filename)[1]
        file_name = f"{uuid.uuid4()}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_url = f"/uploads/{file_name}"

    # Save User Message to Database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (session_id, role, message, file_path) VALUES (?, ?, ?, ?)",
        (session_id, "user", message, file_url)
    )
    
    # Auto-update session title based on the first prompt
    cursor.execute("SELECT title FROM sessions WHERE id = ?", (session_id,))
    res = cursor.fetchone()
    if res and res[0] == "New Chat":
        new_title = message[:30] + ("..." if len(message) > 30 else "")
        cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (new_title, session_id))
    
    conn.commit()
    conn.close()

    lower_msg = message.lower()
    
    # 1. Image Generation Check
    image_keywords = ["generate image", "draw", "image banao", "picture", "photo", "tasveer", "create an image", "generate a picture", "paint"]
    is_image_request = any(kw in lower_msg for kw in image_keywords)

    if is_image_request:
        image_prompt = message
        for kw in image_keywords:
            image_prompt = image_prompt.replace(kw, "").strip()
        
        encoded_prompt = urllib.parse.quote(image_prompt if image_prompt else message)
        generated_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=768&nologo=true"
        final_response = f"???? **Here is your generated image based on your prompt:**\n\n![Generated Art]({generated_image_url})\n\n*(Prompt: {message})*"
    
    # 2. Universal Text & Task Handling via Gemini API
    else:
        try:
            if client:
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=message,
                )
                final_response = response.text
            else:
                final_response = "?????? **Client Error:** GenAI client is not initialized properly."
        except Exception as e:
            final_response = f"?????? Error processing query with AI model: {str(e)}"

    # Generator to stream response smoothly
    async def generate():
        chunk_size = 20
        for i in range(0, len(final_response), chunk_size):
            chunk = final_response[i:i+chunk_size]
            yield chunk

        # Save Assistant Final Response to Database
        conn_inner = sqlite3.connect(DB_FILE)
        cursor_inner = conn_inner.cursor()
        cursor_inner.execute(
            "INSERT INTO messages (session_id, role, message, file_path) VALUES (?, ?, ?, ?)",
            (session_id, "assistant", final_response, None)
        )
        conn_inner.commit()
        conn_inner.close()

    return StreamingResponse(generate(), media_type="text/plain")

@app.post("/clear-history")
def clear_history():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages")
    cursor.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()
    return {"status": "success"}

class Doc:
    """Define the documentation of a type annotation using `Annotated`, to be
        used in class attributes, function and method parameters, return values,
        and variables.

    The value should be a positional-only string literal to allow static tools
    like editors and documentation generators to use it.

    This complements docstrings.

    The string value passed is available in the attribute `documentation`.

    Example:

    ```Python
    from typing import Annotated
    from annotated_doc import Doc

    def hi(name: Annotated[str, Doc("Who to say hi to")]) -> None:
        print(f"Hi, {name}!")
    ```
    """

    def __init__(self, documentation: str, /) -> None:
        self.documentation = documentation

    def __repr__(self) -> str:
        return f"Doc({self.documentation!r})"

    def __hash__(self) -> int:
        return hash(self.documentation)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Doc):
            return NotImplemented
        return self.documentation == other.documentation


from typing import List, Optional


def main(args: Optional[List[str]] = None) -> int:
    """This is preserved for old console scripts that may still be referencing
    it.

    For additional details, see https://github.com/pypa/pip/issues/7498.
    """
    from pip._internal.utils.entrypoints import _wrapper

    return _wrapper(args)


"""Primary application entrypoint."""

import locale
import logging
import os
import sys
import warnings
from typing import List, Optional

from pip._internal.cli.autocompletion import autocomplete
from pip._internal.cli.main_parser import parse_command
from pip._internal.commands import create_command
from pip._internal.exceptions import PipError
from pip._internal.utils import deprecation

logger = logging.getLogger(__name__)


# Do not import and use main() directly! Using it directly is actively
# discouraged by pip's maintainers. The name, location and behavior of
# this function is subject to change, so calling it directly is not
# portable across different pip versions.

# In addition, running pip in-process is unsupported and unsafe. This is
# elaborated in detail at
# https://pip.pypa.io/en/stable/user_guide/#using-pip-from-your-program.
# That document also provides suggestions that should work for nearly
# all users that are considering importing and using main() directly.

# However, we know that certain users will still want to invoke pip
# in-process. If you understand and accept the implications of using pip
# in an unsupported manner, the best approach is to use runpy to avoid
# depending on the exact location of this entry point.

# The following example shows how to use runpy to invoke pip in that
# case:
#
#     sys.argv = ["pip", your, args, here]
#     runpy.run_module("pip", run_name="__main__")
#
# Note that this will exit the process after running, unlike a direct
# call to main. As it is not safe to do any processing after calling
# main, this should not be an issue in practice.


def main(args: Optional[List[str]] = None) -> int:
    if args is None:
        args = sys.argv[1:]

    # Suppress the pkg_resources deprecation warning
    # Note - we use a module of .*pkg_resources to cover
    # the normal case (pip._vendor.pkg_resources) and the
    # devendored case (a bare pkg_resources)
    warnings.filterwarnings(
        action="ignore", category=DeprecationWarning, module=".*pkg_resources"
    )

    # Configure our deprecation warnings to be sent through loggers
    deprecation.install_warning_logger()

    autocomplete()

    try:
        cmd_name, cmd_args = parse_command(args)
    except PipError as exc:
        sys.stderr.write(f"ERROR: {exc}")
        sys.stderr.write(os.linesep)
        sys.exit(1)

    # Needed for locale.getpreferredencoding(False) to work
    # in pip._internal.utils.encoding.auto_decode
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error as e:
        # setlocale can apparently crash if locale are uninitialized
        logger.debug("Ignoring error %s when setting locale", e)
    command = create_command(cmd_name, isolated=("--isolated" in cmd_args))

    return command.main(cmd_args)


"""Logic for creating models."""

# Because `dict` is in the local namespace of the `BaseModel` class, we use `Dict` for annotations.
# TODO v3 fallback to `dict` when the deprecated `dict` method gets removed.
# ruff: noqa: UP035

from __future__ import annotations as _annotations

import operator
import sys
import types
import warnings
from collections.abc import Generator, Mapping
from copy import copy, deepcopy
from functools import cached_property
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    Generic,
    Literal,
    TypeVar,
    Union,
    cast,
    overload,
)

import pydantic_core
import typing_extensions
from pydantic_core import PydanticUndefined, ValidationError
from typing_extensions import Self, TypeAlias, Unpack

from . import PydanticDeprecatedSince20, PydanticDeprecatedSince211
from ._internal import (
    _config,
    _decorators,
    _fields,
    _forward_ref,
    _generics,
    _mock_val_ser,
    _model_construction,
    _namespace_utils,
    _repr,
    _typing_extra,
    _utils,
)
from ._migration import getattr_migration
from .aliases import AliasChoices, AliasPath
from .annotated_handlers import GetCoreSchemaHandler, GetJsonSchemaHandler
from .config import ConfigDict, ExtraValues
from .errors import PydanticUndefinedAnnotation, PydanticUserError
from .json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema, JsonSchemaMode, JsonSchemaValue, model_json_schema
from .plugin._schema_validator import PluggableSchemaValidator

if TYPE_CHECKING:
    from inspect import Signature
    from pathlib import Path

    from pydantic_core import CoreSchema, SchemaSerializer, SchemaValidator

    from ._internal._fields import PydanticExtraInfo
    from ._internal._namespace_utils import MappingNamespace
    from ._internal._utils import AbstractSetIntStr, MappingIntStrAny
    from .deprecated.parse import Protocol as DeprecatedParseProtocol
    from .fields import ComputedFieldInfo, FieldInfo, ModelPrivateAttr


__all__ = 'BaseModel', 'create_model'

# Keep these type aliases available at runtime:
TupleGenerator: TypeAlias = Generator[tuple[str, Any], None, None]
# NOTE: In reality, `bool` should be replaced by `Literal[True]` but mypy fails to correctly apply bidirectional
# type inference (e.g. when using `{'a': {'b': True}}`):
# NOTE: Keep this type alias in sync with the stub definition in `pydantic-core`:
IncEx: TypeAlias = Union[set[int], set[str], Mapping[int, Union['IncEx', bool]], Mapping[str, Union['IncEx', bool]]]

_object_setattr = _model_construction.object_setattr


def _check_frozen(model_cls: type[BaseModel], name: str, value: Any) -> None:
    if model_cls.model_config.get('frozen'):
        error_type = 'frozen_instance'
    elif getattr(model_cls.__pydantic_fields__.get(name), 'frozen', False):
        error_type = 'frozen_field'
    else:
        return

    raise ValidationError.from_exception_data(
        model_cls.__name__, [{'type': error_type, 'loc': (name,), 'input': value}]
    )


def _model_field_setattr_handler(model: BaseModel, name: str, val: Any) -> None:
    model.__dict__[name] = val
    model.__pydantic_fields_set__.add(name)


def _private_setattr_handler(model: BaseModel, name: str, val: Any) -> None:
    if getattr(model, '__pydantic_private__', None) is None:
        # While the attribute should be present at this point, this may not be the case if
        # users do unusual stuff with `model_post_init()` (which is where the  `__pydantic_private__`
        # is initialized, by wrapping the user-defined `model_post_init()`), e.g. if they mock
        # the `model_post_init()` call. Ideally we should find a better way to init private attrs.
        object.__setattr__(model, '__pydantic_private__', {})
    model.__pydantic_private__[name] = val  # pyright: ignore[reportOptionalSubscript]


_SIMPLE_SETATTR_HANDLERS: Mapping[str, Callable[[BaseModel, str, Any], None]] = {
    'model_field': _model_field_setattr_handler,
    'validate_assignment': lambda model, name, val: model.__pydantic_validator__.validate_assignment(model, name, val),  # pyright: ignore[reportAssignmentType]
    'private': _private_setattr_handler,
    'cached_property': lambda model, name, val: model.__dict__.__setitem__(name, val),
    'extra_known': lambda model, name, val: _object_setattr(model, name, val),
}


class BaseModel(metaclass=_model_construction.ModelMetaclass):
    """!!! abstract "Usage Documentation"
        [Models](../concepts/models.md)

    A base class for creating Pydantic models.

    Attributes:
        __class_vars__: The names of the class variables defined on the model.
        __private_attributes__: Metadata about the private attributes of the model.
        __signature__: The synthesized `__init__` [`Signature`][inspect.Signature] of the model.

        __pydantic_complete__: Whether model building is completed, or if there are still undefined fields.
        __pydantic_core_schema__: The core schema of the model.
        __pydantic_custom_init__: Whether the model has a custom `__init__` function.
        __pydantic_decorators__: Metadata containing the decorators defined on the model.
            This replaces `Model.__validators__` and `Model.__root_validators__` from Pydantic V1.
        __pydantic_generic_metadata__: A dictionary containing metadata about generic Pydantic models.
            The `origin` and `args` items map to the [`__origin__`][genericalias.__origin__]
            and [`__args__`][genericalias.__args__] attributes of [generic aliases][types-genericalias],
            and the `parameter` item maps to the `__parameter__` attribute of generic classes.
        __pydantic_parent_namespace__: Parent namespace of the model, used for automatic rebuilding of models.
        __pydantic_post_init__: The name of the post-init method for the model, if defined.
        __pydantic_root_model__: Whether the model is a [`RootModel`][pydantic.root_model.RootModel].
        __pydantic_serializer__: The `pydantic-core` `SchemaSerializer` used to dump instances of the model.
        __pydantic_validator__: The `pydantic-core` `SchemaValidator` used to validate instances of the model.

        __pydantic_fields__: A dictionary of field names and their corresponding [`FieldInfo`][pydantic.fields.FieldInfo] objects.
        __pydantic_computed_fields__: A dictionary of computed field names and their corresponding [`ComputedFieldInfo`][pydantic.fields.ComputedFieldInfo] objects.

        __pydantic_extra__: A dictionary containing extra values, if [`extra`][pydantic.config.ConfigDict.extra]
            is set to `'allow'`.
        __pydantic_fields_set__: The names of fields explicitly set during instantiation.
        __pydantic_private__: Values of private attributes set on the model instance.
    """

    # Note: Many of the below class vars are defined in the metaclass, but we define them here for type checking purposes.

    model_config: ClassVar[ConfigDict] = ConfigDict()
    """
    Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
    """

    __class_vars__: ClassVar[set[str]]
    """The names of the class variables defined on the model."""

    __private_attributes__: ClassVar[Dict[str, ModelPrivateAttr]]  # noqa: UP006
    """Metadata about the private attributes of the model."""

    __signature__: ClassVar[Signature]
    """The synthesized `__init__` [`Signature`][inspect.Signature] of the model."""

    __pydantic_complete__: ClassVar[bool] = False
    """Whether model building is completed, or if there are still undefined fields."""

    __pydantic_core_schema__: ClassVar[CoreSchema]
    """The core schema of the model."""

    __pydantic_custom_init__: ClassVar[bool]
    """Whether the model has a custom `__init__` method."""

    # Must be set for `GenerateSchema.model_schema` to work for a plain `BaseModel` annotation.
    __pydantic_decorators__: ClassVar[_decorators.DecoratorInfos] = _decorators.DecoratorInfos()
    """Metadata containing the decorators defined on the model.
    This replaces `Model.__validators__` and `Model.__root_validators__` from Pydantic V1."""

    __pydantic_generic_metadata__: ClassVar[_generics.PydanticGenericMetadata]
    """A dictionary containing metadata about generic Pydantic models.

    The `origin` and `args` items map to the [`__origin__`][genericalias.__origin__]
    and [`__args__`][genericalias.__args__] attributes of [generic aliases][types-genericalias],
    and the `parameter` item maps to the `__parameter__` attribute of generic classes.
    """

    __pydantic_parent_namespace__: ClassVar[Dict[str, Any] | None] = None  # noqa: UP006
    """Parent namespace of the model, used for automatic rebuilding of models."""

    __pydantic_post_init__: ClassVar[None | Literal['model_post_init']]
    """The name of the post-init method for the model, if defined."""

    __pydantic_root_model__: ClassVar[bool] = False
    """Whether the model is a [`RootModel`][pydantic.root_model.RootModel]."""

    __pydantic_serializer__: ClassVar[SchemaSerializer]
    """The `pydantic-core` `SchemaSerializer` used to dump instances of the model."""

    __pydantic_validator__: ClassVar[SchemaValidator | PluggableSchemaValidator]
    """The `pydantic-core` `SchemaValidator` used to validate instances of the model."""

    __pydantic_fields__: ClassVar[Dict[str, FieldInfo]]  # noqa: UP006
    """A dictionary of field names and their corresponding [`FieldInfo`][pydantic.fields.FieldInfo] objects.
    This replaces `Model.__fields__` from Pydantic V1.
    """

    __pydantic_setattr_handlers__: ClassVar[Dict[str, Callable[[BaseModel, str, Any], None]]]  # noqa: UP006
    """`__setattr__` handlers. Memoizing the handlers leads to a dramatic performance improvement in `__setattr__`"""

    __pydantic_computed_fields__: ClassVar[Dict[str, ComputedFieldInfo]]  # noqa: UP006
    """A dictionary of computed field names and their corresponding [`ComputedFieldInfo`][pydantic.fields.ComputedFieldInfo] objects."""

    __pydantic_extra_info__: ClassVar[PydanticExtraInfo | None]
    """A wrapper around the `__pydantic_extra__` annotation, if explicitly annotated on a model.

    This is a private attribute, not meant to be used outside Pydantic.
    """

    __pydantic_extra__: Dict[str, Any] | None = _model_construction.NoInitField(init=False)  # noqa: UP006
    """A dictionary containing extra values, if [`extra`][pydantic.config.ConfigDict.extra] is set to `'allow'`."""

    __pydantic_fields_set__: set[str] = _model_construction.NoInitField(init=False)
    """The names of fields explicitly set during instantiation."""

    __pydantic_private__: Dict[str, Any] | None = _model_construction.NoInitField(init=False)  # noqa: UP006
    """Values of private attributes set on the model instance."""

    if not TYPE_CHECKING:
        # Prevent `BaseModel` from being instantiated directly
        # (defined in an `if not TYPE_CHECKING` block for clarity and to avoid type checking errors):
        __pydantic_core_schema__ = _mock_val_ser.MockCoreSchema(
            'Pydantic models should inherit from BaseModel, BaseModel cannot be instantiated directly',
            code='base-model-instantiated',
        )
        __pydantic_validator__ = _mock_val_ser.MockValSer(
            'Pydantic models should inherit from BaseModel, BaseModel cannot be instantiated directly',
            val_or_ser='validator',
            code='base-model-instantiated',
        )
        __pydantic_serializer__ = _mock_val_ser.MockValSer(
            'Pydantic models should inherit from BaseModel, BaseModel cannot be instantiated directly',
            val_or_ser='serializer',
            code='base-model-instantiated',
        )

    __slots__ = '__dict__', '__pydantic_fields_set__', '__pydantic_extra__', '__pydantic_private__'

    def __init__(self, /, **data: Any) -> None:
        """Create a new model by parsing and validating input data from keyword arguments.

        Raises [`ValidationError`][pydantic_core.ValidationError] if the input data cannot be
        validated to form a valid model.

        `self` is explicitly positional-only to allow `self` as a field name.
        """
        # `__tracebackhide__` tells pytest and some other tools to omit this function from tracebacks
        __tracebackhide__ = True
        validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self)
        if self is not validated_self:
            warnings.warn(
                'A custom validator is returning a value other than `self`.\n'
                "Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.\n"
                'See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.',
                stacklevel=2,
            )

    # The following line sets a flag that we use to determine when `__init__` gets overridden by the user
    __init__.__pydantic_base_init__ = True  # pyright: ignore[reportFunctionMemberAccess]

    @_utils.deprecated_instance_property
    @classmethod
    def model_fields(cls) -> dict[str, FieldInfo]:
        """A mapping of field names to their respective [`FieldInfo`][pydantic.fields.FieldInfo] instances.

        !!! warning
            Accessing this attribute from a model instance is deprecated, and will not work in Pydantic V3.
            Instead, you should access this attribute from the model class.
        """
        return getattr(cls, '__pydantic_fields__', {})

    @_utils.deprecated_instance_property
    @classmethod
    def model_computed_fields(cls) -> dict[str, ComputedFieldInfo]:
        """A mapping of computed field names to their respective [`ComputedFieldInfo`][pydantic.fields.ComputedFieldInfo] instances.

        !!! warning
            Accessing this attribute from a model instance is deprecated, and will not work in Pydantic V3.
            Instead, you should access this attribute from the model class.
        """
        return getattr(cls, '__pydantic_computed_fields__', {})

    @property
    def model_extra(self) -> dict[str, Any] | None:
        """Get extra fields set during validation.

        Returns:
            A dictionary of extra fields, or `None` if `config.extra` is not set to `"allow"`.
        """
        return self.__pydantic_extra__

    @property
    def model_fields_set(self) -> set[str]:
        """Returns the set of fields that have been explicitly set on this model instance.

        Returns:
            A set of strings representing the fields that have been set,
                i.e. that were not filled from defaults.
        """
        return self.__pydantic_fields_set__

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:  # noqa: C901
        """Creates a new instance of the `Model` class with validated data.

        Creates a new model setting `__dict__` and `__pydantic_fields_set__` from trusted or pre-validated data.
        Default values are respected, but no other validation is performed.

        !!! note
            `model_construct()` generally respects the `model_config.extra` setting on the provided model.
            That is, if `model_config.extra == 'allow'`, then all extra passed values are added to the model instance's `__dict__`
            and `__pydantic_extra__` fields. If `model_config.extra == 'ignore'` (the default), then all extra passed values are ignored.
            Because no validation is performed with a call to `model_construct()`, having `model_config.extra == 'forbid'` does not result in
            an error if extra values are passed, but they will be ignored.

        Args:
            _fields_set: A set of field names that were originally explicitly set during instantiation. If provided,
                this is directly used for the [`model_fields_set`][pydantic.BaseModel.model_fields_set] attribute.
                Otherwise, the field names from the `values` argument will be used.
            values: Trusted or pre-validated data dictionary.

        Returns:
            A new instance of the `Model` class with validated data.
        """
        m = cls.__new__(cls)
        fields_values: dict[str, Any] = {}
        fields_set = set()

        for name, field in cls.__pydantic_fields__.items():
            if field.alias is not None and field.alias in values:
                fields_values[name] = values.pop(field.alias)
                fields_set.add(name)

            if (name not in fields_set) and (field.validation_alias is not None):
                validation_aliases: list[str | AliasPath] = (
                    field.validation_alias.choices
                    if isinstance(field.validation_alias, AliasChoices)
                    else [field.validation_alias]
                )

                for alias in validation_aliases:
                    if isinstance(alias, str) and alias in values:
                        fields_values[name] = values.pop(alias)
                        fields_set.add(name)
                        break
                    elif isinstance(alias, AliasPath):
                        value = alias.search_dict_for_path(values)
                        if value is not PydanticUndefined:
                            fields_values[name] = value
                            fields_set.add(name)
                            break

            if name not in fields_set:
                if name in values:
                    fields_values[name] = values.pop(name)
                    fields_set.add(name)
                elif not field.is_required():
                    fields_values[name] = field.get_default(call_default_factory=True, validated_data=fields_values)
        if _fields_set is None:
            _fields_set = fields_set

        _extra: dict[str, Any] | None = values if cls.model_config.get('extra') == 'allow' else None
        _object_setattr(m, '__dict__', fields_values)
        _object_setattr(m, '__pydantic_fields_set__', _fields_set)
        if not cls.__pydantic_root_model__:
            _object_setattr(m, '__pydantic_extra__', _extra)
            _object_setattr(m, '__pydantic_private__', None)

        if cls.__pydantic_post_init__:
            m.model_post_init(None)
            # update private attributes with values set
            if hasattr(m, '__pydantic_private__') and m.__pydantic_private__ is not None:
                for k, v in values.items():
                    if k in m.__private_attributes__:
                        m.__pydantic_private__[k] = v

        return m

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """!!! abstract "Usage Documentation"
            [`model_copy`](../concepts/models.md#model-copy)

        Returns a copy of the model.

        !!! note
            The underlying instance's [`__dict__`][object.__dict__] attribute is copied. This
            might have unexpected side effects if you store anything in it, on top of the model
            fields (e.g. the value of [cached properties][functools.cached_property]).

        Args:
            update: Values to change/add in the new model. Note: the data is not validated
                before creating the new model. You should trust this data.
            deep: Set to `True` to make a deep copy of the model.

        Returns:
            New model instance.
        """
        copied = self.__deepcopy__() if deep else self.__copy__()
        if update:
            if self.model_config.get('extra') == 'allow':
                for k, v in update.items():
                    if k in self.__pydantic_fields__:
                        copied.__dict__[k] = v
                    else:
                        if copied.__pydantic_extra__ is None:
                            copied.__pydantic_extra__ = {}
                        copied.__pydantic_extra__[k] = v
            else:
                copied.__dict__.update(update)
            copied.__pydantic_fields_set__.update(update.keys())
        return copied

    def model_dump(
        self,
        *,
        mode: Literal['json', 'python'] | str = 'python',
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        exclude_computed_fields: bool = False,
        round_trip: bool = False,
        warnings: bool | Literal['none', 'warn', 'error'] = True,
        fallback: Callable[[Any], Any] | None = None,
        serialize_as_any: bool = False,
        polymorphic_serialization: bool | None = None,
    ) -> dict[str, Any]:
        """!!! abstract "Usage Documentation"
            [`model_dump`](../concepts/serialization.md#python-mode)

        Generate a dictionary representation of the model, optionally specifying which fields to include or exclude.

        Args:
            mode: The mode in which `to_python` should run.
                If mode is 'json', the output will only contain JSON serializable types.
                If mode is 'python', the output may contain non-JSON-serializable Python objects.
            include: A set of fields to include in the output.
            exclude: A set of fields to exclude from the output.
            context: Additional context to pass to the serializer.
            by_alias: Whether to use the field's alias in the dictionary key if defined.
            exclude_unset: Whether to exclude fields that have not been explicitly set.
            exclude_defaults: Whether to exclude fields that are set to their default value.
            exclude_none: Whether to exclude fields that have a value of `None`.
            exclude_computed_fields: Whether to exclude computed fields.
                While this can be useful for round-tripping, it is usually recommended to use the dedicated
                `round_trip` parameter instead.
            round_trip: If True, dumped values should be valid as input for non-idempotent types such as Json[T].
            warnings: How to handle serialization errors. False/"none" ignores them, True/"warn" logs errors,
                "error" raises a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError].
            fallback: A function to call when an unknown value is encountered. If not provided,
                a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError] error is raised.
            serialize_as_any: Whether to serialize fields with duck-typing serialization behavior.
            polymorphic_serialization: Whether to use model and dataclass polymorphic serialization for this call.

        Returns:
            A dictionary representation of the model.
        """
        return self.__pydantic_serializer__.to_python(
            self,
            mode=mode,
            by_alias=by_alias,
            include=include,
            exclude=exclude,
            context=context,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            exclude_computed_fields=exclude_computed_fields,
            round_trip=round_trip,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
            polymorphic_serialization=polymorphic_serialization,
        )

    def model_dump_json(
        self,
        *,
        indent: int | None = None,
        ensure_ascii: bool = False,
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        exclude_computed_fields: bool = False,
        round_trip: bool = False,
        warnings: bool | Literal['none', 'warn', 'error'] = True,
        fallback: Callable[[Any], Any] | None = None,
        serialize_as_any: bool = False,
        polymorphic_serialization: bool | None = None,
    ) -> str:
        """!!! abstract "Usage Documentation"
            [`model_dump_json`](../concepts/serialization.md#json-mode)

        Generates a JSON representation of the model using Pydantic's `to_json` method.

        Args:
            indent: Indentation to use in the JSON output. If None is passed, the output will be compact.
            ensure_ascii: If `True`, the output is guaranteed to have all incoming non-ASCII characters escaped.
                If `False` (the default), these characters will be output as-is.
            include: Field(s) to include in the JSON output.
            exclude: Field(s) to exclude from the JSON output.
            context: Additional context to pass to the serializer.
            by_alias: Whether to serialize using field aliases.
            exclude_unset: Whether to exclude fields that have not been explicitly set.
            exclude_defaults: Whether to exclude fields that are set to their default value.
            exclude_none: Whether to exclude fields that have a value of `None`.
            exclude_computed_fields: Whether to exclude computed fields.
                While this can be useful for round-tripping, it is usually recommended to use the dedicated
                `round_trip` parameter instead.
            round_trip: If True, dumped values should be valid as input for non-idempotent types such as Json[T].
            warnings: How to handle serialization errors. False/"none" ignores them, True/"warn" logs errors,
                "error" raises a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError].
            fallback: A function to call when an unknown value is encountered. If not provided,
                a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError] error is raised.
            serialize_as_any: Whether to serialize fields with duck-typing serialization behavior.
            polymorphic_serialization: Whether to use model and dataclass polymorphic serialization for this call.

        Returns:
            A JSON string representation of the model.
        """
        return self.__pydantic_serializer__.to_json(
            self,
            indent=indent,
            ensure_ascii=ensure_ascii,
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            exclude_computed_fields=exclude_computed_fields,
            round_trip=round_trip,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
            polymorphic_serialization=polymorphic_serialization,
        ).decode()

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = 'validation',
        *,
        union_format: Literal['any_of', 'primitive_type_array'] = 'any_of',
    ) -> dict[str, Any]:
        """Generates a JSON schema for a model class.

        Args:
            by_alias: Whether to use attribute aliases or not.
            ref_template: The reference template.
            union_format: The format to use when combining schemas from unions together. Can be one of:

                - `'any_of'`: Use the [`anyOf`](https://json-schema.org/understanding-json-schema/reference/combining#anyOf)
                keyword to combine schemas (the default).
                - `'primitive_type_array'`: Use the [`type`](https://json-schema.org/understanding-json-schema/reference/type)
                keyword as an array of strings, containing each type of the combination. If any of the schemas is not a primitive
                type (`string`, `boolean`, `null`, `integer` or `number`) or contains constraints/metadata, falls back to
                `any_of`.
            schema_generator: To override the logic used to generate the JSON schema, as a subclass of
                `GenerateJsonSchema` with your desired modifications
            mode: The mode in which to generate the schema.

        Returns:
            The JSON schema for the given model class.
        """
        return model_json_schema(
            cls,
            by_alias=by_alias,
            ref_template=ref_template,
            union_format=union_format,
            schema_generator=schema_generator,
            mode=mode,
        )

    @classmethod
    def model_parametrized_name(cls, params: tuple[type[Any], ...]) -> str:
        """Compute the class name for parametrizations of generic classes.

        This method can be overridden to achieve a custom naming scheme for generic BaseModels.

        Args:
            params: Tuple of types of the class. Given a generic class
                `Model` with 2 type variables and a concrete model `Model[str, int]`,
                the value `(str, int)` would be passed to `params`.

        Returns:
            String representing the new class where `params` are passed to `cls` as type variables.

        Raises:
            TypeError: Raised when trying to generate concrete names for non-generic models.
        """
        if not issubclass(cls, Generic):
            raise TypeError('Concrete names should only be generated for generic models.')

        # Any strings received should represent forward references, so we handle them specially below.
        # If we eventually move toward wrapping them in a ForwardRef in __class_getitem__ in the future,
        # we may be able to remove this special case.
        param_names = [param if isinstance(param, str) else _repr.display_as_type(param) for param in params]
        params_component = ', '.join(param_names)
        return f'{cls.__name__}[{params_component}]'

    def model_post_init(self, context: Any, /) -> None:
        """Override this method to perform additional initialization after `__init__` and `model_construct`.
        This is useful if you want to do some validation that requires the entire model to be initialized.
        """

    @classmethod
    def model_rebuild(
        cls,
        *,
        force: bool = False,
        raise_errors: bool = True,
        _parent_namespace_depth: int = 2,
        _types_namespace: MappingNamespace | None = None,
    ) -> bool | None:
        """Try to rebuild the pydantic-core schema for the model.

        This may be necessary when one of the annotations is a ForwardRef which could not be resolved during
        the initial attempt to build the schema, and automatic rebuilding fails.

        Args:
            force: Whether to force the rebuilding of the model schema, defaults to `False`.
            raise_errors: Whether to raise errors, defaults to `True`.
            _parent_namespace_depth: The depth level of the parent namespace, defaults to 2.
            _types_namespace: The types namespace, defaults to `None`.

        Returns:
            Returns `None` if the schema is already "complete" and rebuilding was not required.
            If rebuilding _was_ required, returns `True` if rebuilding was successful, otherwise `False`.
        """
        already_complete = cls.__pydantic_complete__
        if already_complete and not force:
            return None

        cls.__pydantic_complete__ = False

        for attr in ('__pydantic_core_schema__', '__pydantic_validator__', '__pydantic_serializer__'):
            if attr in cls.__dict__ and not isinstance(getattr(cls, attr), _mock_val_ser.MockValSer):
                # Deleting the validator/serializer is necessary as otherwise they can get reused in
                # pydantic-core. We do so only if they aren't mock instances, otherwise ??? as `model_rebuild()`
                # isn't thread-safe ??? concurrent model instantiations can lead to the parent validator being used.
                # Same applies for the core schema that can be reused in schema generation.
                delattr(cls, attr)

        if _types_namespace is not None:
            rebuild_ns = _types_namespace
        elif _parent_namespace_depth > 0:
            rebuild_ns = _typing_extra.parent_frame_namespace(parent_depth=_parent_namespace_depth, force=True) or {}
        else:
            rebuild_ns = {}

        parent_ns = _model_construction.unpack_lenient_weakvaluedict(cls.__pydantic_parent_namespace__) or {}

        ns_resolver = _namespace_utils.NsResolver(
            parent_namespace={**rebuild_ns, **parent_ns},
        )

        return _model_construction.complete_model_class(
            cls,
            _config.ConfigWrapper(cls.model_config, check=False),
            ns_resolver,
            raise_errors=raise_errors,
            # If the model was already complete, we don't need to call the hook again.
            call_on_complete_hook=not already_complete,
            is_force_rebuild=force,
        )

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        extra: ExtraValues | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        """Validate a pydantic model instance.

        Args:
            obj: The object to validate.
            strict: Whether to enforce types strictly.
            extra: Whether to ignore, allow, or forbid extra data during model validation.
                See the [`extra` configuration value][pydantic.ConfigDict.extra] for details.
            from_attributes: Whether to extract data from object attributes.
            context: Additional context to pass to the validator.
            by_alias: Whether to use the field's alias when validating against the provided input data.
            by_name: Whether to use the field's name when validating against the provided input data.

        Raises:
            ValidationError: If the object could not be validated.

        Returns:
            The validated model instance.
        """
        # `__tracebackhide__` tells pytest and some other tools to omit this function from tracebacks
        __tracebackhide__ = True

        if by_alias is False and by_name is not True:
            raise PydanticUserError(
                'At least one of `by_alias` or `by_name` must be set to True.',
                code='validate-by-alias-and-name-false',
            )

        return cls.__pydantic_validator__.validate_python(
            obj,
            strict=strict,
            extra=extra,
            from_attributes=from_attributes,
            context=context,
            by_alias=by_alias,
            by_name=by_name,
        )

    @classmethod
    def model_validate_json(
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        extra: ExtraValues | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        """!!! abstract "Usage Documentation"
            [JSON Parsing](../concepts/json.md#json-parsing)

        Validate the given JSON data against the Pydantic model.

        Args:
            json_data: The JSON data to validate.
            strict: Whether to enforce types strictly.
            extra: Whether to ignore, allow, or forbid extra data during model validation.
                See the [`extra` configuration value][pydantic.ConfigDict.extra] for details.
            context: Extra variables to pass to the validator.
            by_alias: Whether to use the field's alias when validating against the provided input data.
            by_name: Whether to use the field's name when validating against the provided input data.

        Returns:
            The validated Pydantic model.

        Raises:
            ValidationError: If `json_data` is not a JSON string or the object could not be validated.
        """
        # `__tracebackhide__` tells pytest and some other tools to omit this function from tracebacks
        __tracebackhide__ = True

        if by_alias is False and by_name is not True:
            raise PydanticUserError(
                'At least one of `by_alias` or `by_name` must be set to True.',
                code='validate-by-alias-and-name-false',
            )

        return cls.__pydantic_validator__.validate_json(
            json_data, strict=strict, extra=extra, context=context, by_alias=by_alias, by_name=by_name
        )

    @classmethod
    def model_validate_strings(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        extra: ExtraValues | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        """Validate the given object with string data against the Pydantic model.

        Args:
            obj: The object containing string data to validate.
            strict: Whether to enforce types strictly.
            extra: Whether to ignore, allow, or forbid extra data during model validation.
                See the [`extra` configuration value][pydantic.ConfigDict.extra] for details.
            context: Extra variables to pass to the validator.
            by_alias: Whether to use the field's alias when validating against the provided input data.
            by_name: Whether to use the field's name when validating against the provided input data.

        Returns:
            The validated Pydantic model.
        """
        # `__tracebackhide__` tells pytest and some other tools to omit this function from tracebacks
        __tracebackhide__ = True

        if by_alias is False and by_name is not True:
            raise PydanticUserError(
                'At least one of `by_alias` or `by_name` must be set to True.',
                code='validate-by-alias-and-name-false',
            )

        return cls.__pydantic_validator__.validate_strings(
            obj, strict=strict, extra=extra, context=context, by_alias=by_alias, by_name=by_name
        )

    @classmethod
    def __get_pydantic_core_schema__(cls, source: type[BaseModel], handler: GetCoreSchemaHandler, /) -> CoreSchema:
        # This warning is only emitted when calling `super().__get_pydantic_core_schema__` from a model subclass.
        # In the generate schema logic, this method (`BaseModel.__get_pydantic_core_schema__`) is special cased to
        # *not* be called if not overridden.
        warnings.warn(
            'The `__get_pydantic_core_schema__` method of the `BaseModel` class is deprecated. If you are calling '
            '`super().__get_pydantic_core_schema__` when overriding the method on a Pydantic model, consider using '
            '`handler(source)` instead. However, note that overriding this method on models can lead to unexpected '
            'side effects.',
            PydanticDeprecatedSince211,
            stacklevel=2,
        )
        # Logic copied over from `GenerateSchema._model_schema`:
        schema = cls.__dict__.get('__pydantic_core_schema__')
        if schema is not None and not isinstance(schema, _mock_val_ser.MockCoreSchema):
            return cls.__pydantic_core_schema__

        return handler(source)

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
        /,
    ) -> JsonSchemaValue:
        """Hook into generating the model's JSON schema.

        Args:
            core_schema: A `pydantic-core` CoreSchema.
                You can ignore this argument and call the handler with a new CoreSchema,
                wrap this CoreSchema (`{'type': 'nullable', 'schema': current_schema}`),
                or just call the handler with the original schema.
            handler: Call into Pydantic's internal JSON schema generation.
                This will raise a `pydantic.errors.PydanticInvalidForJsonSchema` if JSON schema
                generation fails.
                Since this gets called by `BaseModel.model_json_schema` you can override the
                `schema_generator` argument to that function to change JSON schema generation globally
                for a type.

        Returns:
            A JSON schema, as a Python object.
        """
        return handler(core_schema)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """This is intended to behave just like `__init_subclass__`, but is called by `ModelMetaclass`
        only after basic class initialization is complete. In particular, attributes like `model_fields` will
        be present when this is called, but forward annotations are not guaranteed to be resolved yet,
        meaning that creating an instance of the class may fail.

        This is necessary because `__init_subclass__` will always be called by `type.__new__`,
        and it would require a prohibitively large refactor to the `ModelMetaclass` to ensure that
        `type.__new__` was called in such a manner that the class would already be sufficiently initialized.

        This will receive the same `kwargs` that would be passed to the standard `__init_subclass__`, namely,
        any kwargs passed to the class definition that aren't used internally by Pydantic.

        Args:
            **kwargs: Any keyword arguments passed to the class definition that aren't used internally
                by Pydantic.

        Note:
            You may want to override [`__pydantic_on_complete__()`][pydantic.main.BaseModel.__pydantic_on_complete__]
            instead, which is called once the class and its fields are fully initialized and ready for validation.
        """

    @classmethod
    def __pydantic_on_complete__(cls) -> None:
        """This is called once the class and its fields are fully initialized and ready to be used.

        This typically happens when the class is created (just before
        [`__pydantic_init_subclass__()`][pydantic.main.BaseModel.__pydantic_init_subclass__] is called on the superclass),
        except when forward annotations are used that could not immediately be resolved.
        In that case, it will be called later, when the model is rebuilt automatically or explicitly using
        [`model_rebuild()`][pydantic.main.BaseModel.model_rebuild].
        """

    def __class_getitem__(
        cls, typevar_values: type[Any] | tuple[type[Any], ...]
    ) -> type[BaseModel] | _forward_ref.PydanticRecursiveRef:
        cached = _generics.get_cached_generic_type_early(cls, typevar_values)
        if cached is not None:
            return cached

        if cls is BaseModel:
            raise TypeError('Type parameters should be placed on typing.Generic, not BaseModel')
        if not hasattr(cls, '__parameters__'):
            raise TypeError(f'{cls} cannot be parametrized because it does not inherit from typing.Generic')
        if not cls.__pydantic_generic_metadata__['parameters'] and Generic not in cls.__bases__:
            raise TypeError(f'{cls} is not a generic class')

        if not isinstance(typevar_values, tuple):
            typevar_values = (typevar_values,)

        # For a model `class Model[T, U, V = int](BaseModel): ...` parametrized with `(str, bool)`,
        # this gives us `{T: str, U: bool, V: int}`:
        typevars_map = _generics.map_generic_model_arguments(cls, typevar_values)
        # We also update the provided args to use defaults values (`(str, bool)` becomes `(str, bool, int)`):
        typevar_values = tuple(v for v in typevars_map.values())

        if _utils.all_identical(typevars_map.keys(), typevars_map.values()) and typevars_map:
            submodel = cls  # if arguments are equal to parameters it's the same object
            _generics.set_cached_generic_type(cls, typevar_values, submodel)
        else:
            parent_args = cls.__pydantic_generic_metadata__['args']
            if not parent_args:
                args = typevar_values
            else:
                args = tuple(_generics.replace_types(arg, typevars_map) for arg in parent_args)

            origin = cls.__pydantic_generic_metadata__['origin'] or cls
            model_name = origin.model_parametrized_name(args)
            params = tuple(
                dict.fromkeys(_generics.iter_contained_typevars(typevars_map.values()))
            )  # use dict as ordered set

            with _generics.generic_recursion_self_type(origin, args) as maybe_self_type:
                cached = _generics.get_cached_generic_type_late(cls, typevar_values, origin, args)
                if cached is not None:
                    return cached

                if maybe_self_type is not None:
                    return maybe_self_type

                # Attempt to rebuild the origin in case new types have been defined
                try:
                    # depth 2 gets you above this __class_getitem__ call.
                    # Note that we explicitly provide the parent ns, otherwise
                    # `model_rebuild` will use the parent ns no matter if it is the ns of a module.
                    # We don't want this here, as this has unexpected effects when a model
                    # is being parametrized during a forward annotation evaluation.
                    parent_ns = _typing_extra.parent_frame_namespace(parent_depth=2) or {}
                    origin.model_rebuild(_types_namespace=parent_ns)
                except PydanticUndefinedAnnotation:
                    # It's okay if it fails, it just means there are still undefined types
                    # that could be evaluated later.
                    pass

                submodel = _generics.create_generic_submodel(model_name, origin, args, params)

                _generics.set_cached_generic_type(cls, typevar_values, submodel, origin, args)

        return submodel

    def __copy__(self) -> Self:
        """Returns a shallow copy of the model."""
        cls = type(self)
        m = cls.__new__(cls)
        _object_setattr(m, '__dict__', copy(self.__dict__))
        _object_setattr(m, '__pydantic_extra__', copy(self.__pydantic_extra__))
        _object_setattr(m, '__pydantic_fields_set__', copy(self.__pydantic_fields_set__))

        if not hasattr(self, '__pydantic_private__') or self.__pydantic_private__ is None:
            _object_setattr(m, '__pydantic_private__', None)
        else:
            _object_setattr(
                m,
                '__pydantic_private__',
                {k: v for k, v in self.__pydantic_private__.items() if v is not PydanticUndefined},
            )

        return m

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        """Returns a deep copy of the model."""
        cls = type(self)
        m = cls.__new__(cls)
        _object_setattr(m, '__dict__', deepcopy(self.__dict__, memo=memo))
        _object_setattr(m, '__pydantic_extra__', deepcopy(self.__pydantic_extra__, memo=memo))
        # This next line doesn't need a deepcopy because __pydantic_fields_set__ is a set[str],
        # and attempting a deepcopy would be marginally slower.
        _object_setattr(m, '__pydantic_fields_set__', copy(self.__pydantic_fields_set__))

        if not hasattr(self, '__pydantic_private__') or self.__pydantic_private__ is None:
            _object_setattr(m, '__pydantic_private__', None)
        else:
            _object_setattr(
                m,
                '__pydantic_private__',
                deepcopy({k: v for k, v in self.__pydantic_private__.items() if v is not PydanticUndefined}, memo=memo),
            )

        return m

    if not TYPE_CHECKING:
        # We put `__getattr__` in a non-TYPE_CHECKING block because otherwise, mypy allows arbitrary attribute access
        # The same goes for __setattr__ and __delattr__, see: https://github.com/pydantic/pydantic/issues/8643

        def __getattr__(self, item: str) -> Any:
            private_attributes = object.__getattribute__(self, '__private_attributes__')
            if item in private_attributes:
                attribute = private_attributes[item]
                if hasattr(attribute, '__get__'):
                    return attribute.__get__(self, type(self))  # type: ignore

                try:
                    # Note: self.__pydantic_private__ cannot be None if self.__private_attributes__ has items
                    return self.__pydantic_private__[item]  # type: ignore
                except KeyError as exc:
                    raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}') from exc
            else:
                # `__pydantic_extra__` can fail to be set if the model is not yet fully initialized.
                # See `BaseModel.__repr_args__` for more details
                try:
                    pydantic_extra = object.__getattribute__(self, '__pydantic_extra__')
                except AttributeError:
                    pydantic_extra = None

                if pydantic_extra and item in pydantic_extra:
                    return pydantic_extra[item]
                else:
                    if hasattr(self.__class__, item):
                        return super().__getattribute__(item)  # Raises AttributeError if appropriate
                    else:
                        # this is the current error
                        raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}')

        def __setattr__(self, name: str, value: Any) -> None:
            if (setattr_handler := self.__pydantic_setattr_handlers__.get(name)) is not None:
                setattr_handler(self, name, value)
            # if None is returned from _setattr_handler, the attribute was set directly
            elif (setattr_handler := self._setattr_handler(name, value)) is not None:
                setattr_handler(self, name, value)  # call here to not memo on possibly unknown fields
                self.__pydantic_setattr_handlers__[name] = setattr_handler  # memoize the handler for faster access

        def _setattr_handler(self, name: str, value: Any) -> Callable[[BaseModel, str, Any], None] | None:
            """Get a handler for setting an attribute on the model instance.

            Returns:
                A handler for setting an attribute on the model instance. Used for memoization of the handler.
                Memoizing the handlers leads to a dramatic performance improvement in `__setattr__`
                Returns `None` when memoization is not safe, then the attribute is set directly.
            """
            cls = self.__class__
            if name in cls.__class_vars__:
                raise AttributeError(
                    f'{name!r} is a ClassVar of `{cls.__name__}` and cannot be set on an instance. '
                    f'If you want to set a value on the class, use `{cls.__name__}.{name} = value`.'
                )
            elif not _fields.is_valid_field_name(name):
                if (attribute := cls.__private_attributes__.get(name)) is not None:
                    if hasattr(attribute, '__set__'):
                        return lambda model, _name, val: attribute.__set__(model, val)
                    else:
                        return _SIMPLE_SETATTR_HANDLERS['private']
                else:
                    _object_setattr(self, name, value)
                    return None  # Can not return memoized handler with possibly freeform attr names

            attr = getattr(cls, name, None)
            # NOTE: We currently special case properties and `cached_property`, but we might need
            # to generalize this to all data/non-data descriptors at some point. For non-data descriptors
            # (such as `cached_property`), it isn't obvious though. `cached_property` caches the value
            # to the instance's `__dict__`, but other non-data descriptors might do things differently.
            if isinstance(attr, cached_property):
                return _SIMPLE_SETATTR_HANDLERS['cached_property']

            _check_frozen(cls, name, value)

            # We allow properties to be set only on non frozen models for now (to match dataclasses).
            # This can be changed if it ever gets requested.
            if isinstance(attr, property):
                return lambda model, _name, val: attr.__set__(model, val)
            elif cls.model_config.get('validate_assignment'):
                return _SIMPLE_SETATTR_HANDLERS['validate_assignment']
            elif name not in cls.__pydantic_fields__:
                if cls.model_config.get('extra') != 'allow':
                    # TODO - matching error
                    raise ValueError(f'"{cls.__name__}" object has no field "{name}"')
                elif attr is None:
                    # attribute does not exist, so put it in extra
                    self.__pydantic_extra__[name] = value
                    self.__pydantic_fields_set__.add(name)
                    return None  # Can not return memoized handler with possibly freeform attr names
                else:
                    # attribute _does_ exist, and was not in extra, so update it
                    return _SIMPLE_SETATTR_HANDLERS['extra_known']
            else:
                return _SIMPLE_SETATTR_HANDLERS['model_field']

        def __delattr__(self, item: str) -> Any:
            cls = self.__class__

            if item in self.__private_attributes__:
                attribute = self.__private_attributes__[item]
                if hasattr(attribute, '__delete__'):
                    attribute.__delete__(self)  # type: ignore
                    return

                try:
                    # Note: self.__pydantic_private__ cannot be None if self.__private_attributes__ has items
                    del self.__pydantic_private__[item]  # type: ignore
                    return
                except KeyError as exc:
                    raise AttributeError(f'{cls.__name__!r} object has no attribute {item!r}') from exc

            # Allow cached properties to be deleted (even if the class is frozen):
            attr = getattr(cls, item, None)
            if isinstance(attr, cached_property):
                return object.__delattr__(self, item)

            _check_frozen(cls, name=item, value=None)

            if item in self.__pydantic_fields__:
                object.__delattr__(self, item)
            elif self.__pydantic_extra__ is not None and item in self.__pydantic_extra__:
                del self.__pydantic_extra__[item]
            else:
                try:
                    object.__delattr__(self, item)
                except AttributeError:
                    raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}')

        # Because we make use of `@dataclass_transform()`, `__replace__` is already synthesized by
        # type checkers, so we define the implementation in this `if not TYPE_CHECKING:` block:
        def __replace__(self, **changes: Any) -> Self:
            return self.model_copy(update=changes)

    def __getstate__(self) -> dict[Any, Any]:
        private = self.__pydantic_private__
        if private:
            private = {k: v for k, v in private.items() if v is not PydanticUndefined}
        return {
            '__dict__': self.__dict__,
            '__pydantic_extra__': self.__pydantic_extra__,
            '__pydantic_fields_set__': self.__pydantic_fields_set__,
            '__pydantic_private__': private,
        }

    def __setstate__(self, state: dict[Any, Any]) -> None:
        _object_setattr(self, '__pydantic_fields_set__', state.get('__pydantic_fields_set__', {}))
        _object_setattr(self, '__pydantic_extra__', state.get('__pydantic_extra__', {}))
        _object_setattr(self, '__pydantic_private__', state.get('__pydantic_private__', {}))
        _object_setattr(self, '__dict__', state.get('__dict__', {}))

    if not TYPE_CHECKING:

        def __eq__(self, other: Any) -> bool:
            if isinstance(other, BaseModel):
                # When comparing instances of generic types for equality, as long as all field values are equal,
                # only require their generic origin types to be equal, rather than exact type equality.
                # This prevents headaches like MyGeneric(x=1) != MyGeneric[Any](x=1).
                self_type = self.__pydantic_generic_metadata__['origin'] or self.__class__
                other_type = other.__pydantic_generic_metadata__['origin'] or other.__class__

                # Perform common checks first
                if not (
                    self_type is other_type
                    and getattr(self, '__pydantic_private__', None) == getattr(other, '__pydantic_private__', None)
                    # We need to assume `None` and `{}`??are equivalent, because extra behavior
                    # can be controlled at validation time:
                    and (self.__pydantic_extra__ or {}) == (other.__pydantic_extra__ or {})
                ):
                    return False

                # We only want to compare pydantic fields but ignoring fields is costly.
                # We'll perform a fast check first, and fallback only when needed
                # See GH-7444 and GH-7825 for rationale and a performance benchmark

                # First, do the fast (and sometimes faulty) __dict__ comparison
                if self.__dict__ == other.__dict__:
                    # If the check above passes, then pydantic fields are equal, we can return early
                    return True

                # We don't want to trigger unnecessary costly filtering of __dict__ on all unequal objects, so we return
                # early if there are no keys to ignore (we would just return False later on anyway)
                model_fields = type(self).__pydantic_fields__.keys()
                if self.__dict__.keys() <= model_fields and other.__dict__.keys() <= model_fields:
                    return False

                # If we reach here, there are non-pydantic-fields keys, mapped to unequal values, that we need to ignore
                # Resort to costly filtering of the __dict__ objects
                # We use operator.itemgetter because it is much faster than dict comprehensions
                # NOTE: Contrary to standard python class and instances, when the Model class has a default value for an
                # attribute and the model instance doesn't have a corresponding attribute, accessing the missing attribute
                # raises an error in BaseModel.__getattr__ instead of returning the class attribute
                # So we can use operator.itemgetter() instead of operator.attrgetter()
                getter = operator.itemgetter(*model_fields) if model_fields else lambda _: _utils._SENTINEL
                try:
                    return getter(self.__dict__) == getter(other.__dict__)
                except KeyError:
                    # In rare cases (such as when using the deprecated BaseModel.copy() method),
                    # the __dict__ may not contain all model fields, which is how we can get here.
                    # getter(self.__dict__) is much faster than any 'safe' method that accounts
                    # for missing keys, and wrapping it in a `try` doesn't slow things down much
                    # in the common case.
                    self_fields_proxy = _utils.SafeGetItemProxy(self.__dict__)
                    other_fields_proxy = _utils.SafeGetItemProxy(other.__dict__)
                    return getter(self_fields_proxy) == getter(other_fields_proxy)

            # other instance is not a BaseModel
            else:
                return NotImplemented  # delegate to the other item in the comparison

    if TYPE_CHECKING:
        # We put `__init_subclass__` in a TYPE_CHECKING block because, even though we want the type-checking benefits
        # described in the signature of `__init_subclass__` below, we don't want to modify the default behavior of
        # subclass initialization.

        def __init_subclass__(cls, **kwargs: Unpack[ConfigDict]):
            """This signature is included purely to help type-checkers check arguments to class declaration, which
            provides a way to conveniently set model_config key/value pairs.

            ```python
            from pydantic import BaseModel

            class MyModel(BaseModel, extra='allow'): ...
            ```

            However, this may be deceiving, since the _actual_ calls to `__init_subclass__` will not receive any
            of the config arguments, and will only receive any keyword arguments passed during class initialization
            that are _not_ expected keys in ConfigDict. (This is due to the way `ModelMetaclass.__new__` works.)

            Args:
                **kwargs: Keyword arguments passed to the class definition, which set model_config

            Note:
                You may want to override `__pydantic_init_subclass__` instead, which behaves similarly but is called
                *after* the class is fully initialized.
            """

    def __iter__(self) -> TupleGenerator:
        """So `dict(model)` works."""
        yield from [(k, v) for (k, v) in self.__dict__.items() if not k.startswith('_')]
        extra = self.__pydantic_extra__
        if extra:
            yield from extra.items()

    def __repr__(self) -> str:
        return f'{self.__repr_name__()}({self.__repr_str__(", ")})'

    def __repr_args__(self) -> _repr.ReprArgs:
        # Eagerly create the repr of computed fields, as this may trigger access of cached properties and as such
        # modify the instance's `__dict__`. If we don't do it now, it could happen when iterating over the `__dict__`
        # below if the instance happens to be referenced in a field, and would modify the `__dict__` size *during* iteration.
        computed_fields_repr_args = [
            (k, getattr(self, k)) for k, v in self.__pydantic_computed_fields__.items() if v.repr
        ]

        for k, v in self.__dict__.items():
            field = self.__pydantic_fields__.get(k)
            if field and field.repr:
                if v is not self:
                    yield k, v
                else:
                    yield k, self.__repr_recursion__(v)
        # `__pydantic_extra__` can fail to be set if the model is not yet fully initialized.
        # This can happen if a `ValidationError` is raised during initialization and the instance's
        # repr is generated as part of the exception handling. Therefore, we use `getattr` here
        # with a fallback, even though the type hints indicate the attribute will always be present.
        try:
            pydantic_extra = object.__getattribute__(self, '__pydantic_extra__')
        except AttributeError:
            pydantic_extra = None

        if pydantic_extra is not None:
            yield from ((k, v) for k, v in pydantic_extra.items())
        yield from computed_fields_repr_args

    # take logic from `_repr.Representation` without the side effects of inheritance, see #5740
    __repr_name__ = _repr.Representation.__repr_name__
    __repr_recursion__ = _repr.Representation.__repr_recursion__
    __repr_str__ = _repr.Representation.__repr_str__
    __pretty__ = _repr.Representation.__pretty__
    __rich_repr__ = _repr.Representation.__rich_repr__

    def __str__(self) -> str:
        return self.__repr_str__(' ')

    # ##### Deprecated methods from v1 #####
    @property
    @typing_extensions.deprecated(
        'The `__fields__` attribute is deprecated, use the `model_fields` class property instead.', category=None
    )
    def __fields__(self) -> dict[str, FieldInfo]:
        warnings.warn(
            'The `__fields__` attribute is deprecated, use the `model_fields` class property instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        return getattr(type(self), '__pydantic_fields__', {})

    @property
    @typing_extensions.deprecated(
        'The `__fields_set__` attribute is deprecated, use `model_fields_set` instead.',
        category=None,
    )
    def __fields_set__(self) -> set[str]:
        warnings.warn(
            'The `__fields_set__` attribute is deprecated, use `model_fields_set` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        return self.__pydantic_fields_set__

    @typing_extensions.deprecated('The `dict` method is deprecated; use `model_dump` instead.', category=None)
    def dict(  # noqa: D102
        self,
        *,
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
    ) -> Dict[str, Any]:  # noqa UP006
        warnings.warn(
            'The `dict` method is deprecated; use `model_dump` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        return self.model_dump(
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )

    @typing_extensions.deprecated('The `json` method is deprecated; use `model_dump_json` instead.', category=None)
    def json(  # noqa: D102
        self,
        *,
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        encoder: Callable[[Any], Any] | None = PydanticUndefined,  # type: ignore[assignment]
        models_as_dict: bool = PydanticUndefined,  # type: ignore[assignment]
        **dumps_kwargs: Any,
    ) -> str:
        warnings.warn(
            'The `json` method is deprecated; use `model_dump_json` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        if encoder is not PydanticUndefined:
            raise TypeError('The `encoder` argument is no longer supported; use field serializers instead.')
        if models_as_dict is not PydanticUndefined:
            raise TypeError('The `models_as_dict` argument is no longer supported; use a model serializer instead.')
        if dumps_kwargs:
            raise TypeError('`dumps_kwargs` keyword arguments are no longer supported.')
        return self.model_dump_json(
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )

    @classmethod
    @typing_extensions.deprecated('The `parse_obj` method is deprecated; use `model_validate` instead.', category=None)
    def parse_obj(cls, obj: Any) -> Self:  # noqa: D102
        warnings.warn(
            'The `parse_obj` method is deprecated; use `model_validate` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        return cls.model_validate(obj)

    @classmethod
    @typing_extensions.deprecated(
        'The `parse_raw` method is deprecated; if your data is JSON use `model_validate_json`, '
        'otherwise load the data then use `model_validate` instead.',
        category=None,
    )
    def parse_raw(  # noqa: D102
        cls,
        b: str | bytes,
        *,
        content_type: str | None = None,
        encoding: str = 'utf8',
        proto: DeprecatedParseProtocol | None = None,
        allow_pickle: bool = False,
    ) -> Self:  # pragma: no cover
        warnings.warn(
            'The `parse_raw` method is deprecated; if your data is JSON use `model_validate_json`, '
            'otherwise load the data then use `model_validate` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        from .deprecated import parse

        try:
            obj = parse.load_str_bytes(
                b,
                proto=proto,
                content_type=content_type,
                encoding=encoding,
                allow_pickle=allow_pickle,
            )
        except (ValueError, TypeError) as exc:
            import json

            # try to match V1
            if isinstance(exc, UnicodeDecodeError):
                type_str = 'value_error.unicodedecode'
            elif isinstance(exc, json.JSONDecodeError):
                type_str = 'value_error.jsondecode'
            elif isinstance(exc, ValueError):
                type_str = 'value_error'
            else:
                type_str = 'type_error'

            # ctx is missing here, but since we've added `input` to the error, we're not pretending it's the same
            error: pydantic_core.InitErrorDetails = {
                # The type: ignore on the next line is to ignore the requirement of LiteralString
                'type': pydantic_core.PydanticCustomError(type_str, str(exc)),  # type: ignore
                'loc': ('__root__',),
                'input': b,
            }
            raise pydantic_core.ValidationError.from_exception_data(cls.__name__, [error])
        return cls.model_validate(obj)

    @classmethod
    @typing_extensions.deprecated(
        'The `parse_file` method is deprecated; load the data from file, then if your data is JSON '
        'use `model_validate_json`, otherwise `model_validate` instead.',
        category=None,
    )
    def parse_file(  # noqa: D102
        cls,
        path: str | Path,
        *,
        content_type: str | None = None,
        encoding: str = 'utf8',
        proto: DeprecatedParseProtocol | None = None,
        allow_pickle: bool = False,
    ) -> Self:
        warnings.warn(
            'The `parse_file` method is deprecated; load the data from file, then if your data is JSON '
            'use `model_validate_json`, otherwise `model_validate` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        from .deprecated import parse

        obj = parse.load_file(
            path,
            proto=proto,
            content_type=content_type,
            encoding=encoding,
            allow_pickle=allow_pickle,
        )
        return cls.parse_obj(obj)

    @classmethod
    @typing_extensions.deprecated(
        'The `from_orm` method is deprecated; set '
        "`model_config['from_attributes']=True` and use `model_validate` instead.",
        category=None,
    )
    def from_orm(cls, obj: Any) -> Self:  # noqa: D102
        warnings.warn(
            'The `from_orm` method is deprecated; set '
            "`model_config['from_attributes']=True` and use `model_validate` instead.",
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        if not cls.model_config.get('from_attributes', None):
            raise PydanticUserError(
                'You must set the config attribute `from_attributes=True` to use from_orm', code=None
            )
        return cls.model_validate(obj)

    @classmethod
    @typing_extensions.deprecated('The `construct` method is deprecated; use `model_construct` instead.', category=None)
    def construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:  # noqa: D102
        warnings.warn(
            'The `construct` method is deprecated; use `model_construct` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        return cls.model_construct(_fields_set=_fields_set, **values)

    @typing_extensions.deprecated(
        'The `copy` method is deprecated; use `model_copy` instead. '
        'See the docstring of `BaseModel.copy` for details about how to handle `include` and `exclude`.',
        category=None,
    )
    def copy(
        self,
        *,
        include: AbstractSetIntStr | MappingIntStrAny | None = None,
        exclude: AbstractSetIntStr | MappingIntStrAny | None = None,
        update: Dict[str, Any] | None = None,  # noqa UP006
        deep: bool = False,
    ) -> Self:  # pragma: no cover
        """Returns a copy of the model.

        !!! warning "Deprecated"
            This method is now deprecated; use `model_copy` instead.

        If you need `include` or `exclude`, use:

        ```python {test="skip" lint="skip"}
        data = self.model_dump(include=include, exclude=exclude, round_trip=True)
        data = {**data, **(update or {})}
        copied = self.model_validate(data)
        ```

        Args:
            include: Optional set or mapping specifying which fields to include in the copied model.
            exclude: Optional set or mapping specifying which fields to exclude in the copied model.
            update: Optional dictionary of field-value pairs to override field values in the copied model.
            deep: If True, the values of fields that are Pydantic models will be deep-copied.

        Returns:
            A copy of the model with included, excluded and updated fields as specified.
        """
        warnings.warn(
            'The `copy` method is deprecated; use `model_copy` instead. '
            'See the docstring of `BaseModel.copy` for details about how to handle `include` and `exclude`.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        from .deprecated import copy_internals

        values = dict(
            copy_internals._iter(
                self, to_dict=False, by_alias=False, include=include, exclude=exclude, exclude_unset=False
            ),
            **(update or {}),
        )
        if self.__pydantic_private__ is None:
            private = None
        else:
            private = {k: v for k, v in self.__pydantic_private__.items() if v is not PydanticUndefined}

        if self.__pydantic_extra__ is None:
            extra: dict[str, Any] | None = None
        else:
            extra = self.__pydantic_extra__.copy()
            for k in list(self.__pydantic_extra__):
                if k not in values:  # k was in the exclude
                    extra.pop(k)
            for k in list(values):
                if k in self.__pydantic_extra__:  # k must have come from extra
                    extra[k] = values.pop(k)

        # new `__pydantic_fields_set__` can have unset optional fields with a set value in `update` kwarg
        if update:
            fields_set = self.__pydantic_fields_set__ | update.keys()
        else:
            fields_set = set(self.__pydantic_fields_set__)

        # removing excluded fields from `__pydantic_fields_set__`
        if exclude:
            fields_set -= set(exclude)

        return copy_internals._copy_and_set_values(self, values, fields_set, extra, private, deep=deep)

    @classmethod
    @typing_extensions.deprecated('The `schema` method is deprecated; use `model_json_schema` instead.', category=None)
    def schema(  # noqa: D102
        cls, by_alias: bool = True, ref_template: str = DEFAULT_REF_TEMPLATE
    ) -> Dict[str, Any]:  # noqa UP006
        warnings.warn(
            'The `schema` method is deprecated; use `model_json_schema` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        return cls.model_json_schema(by_alias=by_alias, ref_template=ref_template)

    @classmethod
    @typing_extensions.deprecated(
        'The `schema_json` method is deprecated; use `model_json_schema` and json.dumps instead.',
        category=None,
    )
    def schema_json(  # noqa: D102
        cls, *, by_alias: bool = True, ref_template: str = DEFAULT_REF_TEMPLATE, **dumps_kwargs: Any
    ) -> str:  # pragma: no cover
        warnings.warn(
            'The `schema_json` method is deprecated; use `model_json_schema` and json.dumps instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        import json

        from .deprecated.json import pydantic_encoder

        return json.dumps(
            cls.model_json_schema(by_alias=by_alias, ref_template=ref_template),
            default=pydantic_encoder,
            **dumps_kwargs,
        )

    @classmethod
    @typing_extensions.deprecated('The `validate` method is deprecated; use `model_validate` instead.', category=None)
    def validate(cls, value: Any) -> Self:  # noqa: D102
        warnings.warn(
            'The `validate` method is deprecated; use `model_validate` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        return cls.model_validate(value)

    @classmethod
    @typing_extensions.deprecated(
        'The `update_forward_refs` method is deprecated; use `model_rebuild` instead.',
        category=None,
    )
    def update_forward_refs(cls, **localns: Any) -> None:  # noqa: D102
        warnings.warn(
            'The `update_forward_refs` method is deprecated; use `model_rebuild` instead.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        if localns:  # pragma: no cover
            raise TypeError('`localns` arguments are not longer accepted.')
        cls.model_rebuild(force=True)

    @typing_extensions.deprecated(
        'The private method `_iter` will be removed and should no longer be used.', category=None
    )
    def _iter(self, *args: Any, **kwargs: Any) -> Any:
        warnings.warn(
            'The private method `_iter` will be removed and should no longer be used.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        from .deprecated import copy_internals

        return copy_internals._iter(self, *args, **kwargs)

    @typing_extensions.deprecated(
        'The private method `_copy_and_set_values` will be removed and should no longer be used.',
        category=None,
    )
    def _copy_and_set_values(self, *args: Any, **kwargs: Any) -> Any:
        warnings.warn(
            'The private method `_copy_and_set_values` will be removed and should no longer be used.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        from .deprecated import copy_internals

        return copy_internals._copy_and_set_values(self, *args, **kwargs)

    @classmethod
    @typing_extensions.deprecated(
        'The private method `_get_value` will be removed and should no longer be used.',
        category=None,
    )
    def _get_value(cls, *args: Any, **kwargs: Any) -> Any:
        warnings.warn(
            'The private method `_get_value` will be removed and should no longer be used.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        from .deprecated import copy_internals

        return copy_internals._get_value(cls, *args, **kwargs)

    @typing_extensions.deprecated(
        'The private method `_calculate_keys` will be removed and should no longer be used.',
        category=None,
    )
    def _calculate_keys(self, *args: Any, **kwargs: Any) -> Any:
        warnings.warn(
            'The private method `_calculate_keys` will be removed and should no longer be used.',
            category=PydanticDeprecatedSince20,
            stacklevel=2,
        )
        from .deprecated import copy_internals

        return copy_internals._calculate_keys(self, *args, **kwargs)


ModelT = TypeVar('ModelT', bound=BaseModel)


@overload
def create_model(
    model_name: str,
    /,
    *,
    __config__: ConfigDict | None = None,
    __doc__: str | None = None,
    __base__: None = None,
    __module__: str = __name__,
    __validators__: dict[str, Callable[..., Any]] | None = None,
    __cls_kwargs__: dict[str, Any] | None = None,
    __qualname__: str | None = None,
    **field_definitions: Any | tuple[Any, Any],
) -> type[BaseModel]: ...


@overload
def create_model(
    model_name: str,
    /,
    *,
    __config__: ConfigDict | None = None,
    __doc__: str | None = None,
    __base__: type[ModelT] | tuple[type[ModelT], ...],
    __module__: str = __name__,
    __validators__: dict[str, Callable[..., Any]] | None = None,
    __cls_kwargs__: dict[str, Any] | None = None,
    __qualname__: str | None = None,
    **field_definitions: Any | tuple[Any, Any],
) -> type[ModelT]: ...


def create_model(  # noqa: C901
    model_name: str,
    /,
    *,
    __config__: ConfigDict | None = None,
    __doc__: str | None = None,
    __base__: type[ModelT] | tuple[type[ModelT], ...] | None = None,
    __module__: str | None = None,
    __validators__: dict[str, Callable[..., Any]] | None = None,
    __cls_kwargs__: dict[str, Any] | None = None,
    __qualname__: str | None = None,
    # TODO PEP 747: replace `Any` by the TypeForm:
    **field_definitions: Any | tuple[Any, Any],
) -> type[ModelT]:
    """!!! abstract "Usage Documentation"
        [Dynamic Model Creation](../concepts/models.md#dynamic-model-creation)

    Dynamically creates and returns a new Pydantic model, in other words, `create_model` dynamically creates a
    subclass of [`BaseModel`][pydantic.BaseModel].

    !!! warning
        This function may execute arbitrary code contained in field annotations, if string references need to be evaluated.

        See [Security implications of introspecting annotations](https://docs.python.org/3/library/annotationlib.html#annotationlib-security) for more information.

    Args:
        model_name: The name of the newly created model.
        __config__: The configuration of the new model.
        __doc__: The docstring of the new model.
        __base__: The base class or classes for the new model.
        __module__: The name of the module that the model belongs to;
            if `None`, the value is taken from `sys._getframe(1)`
        __validators__: A dictionary of methods that validate fields. The keys are the names of the validation methods to
            be added to the model, and the values are the validation methods themselves. You can read more about functional
            validators [here](https://docs.pydantic.dev/2.9/concepts/validators/#field-validators).
        __cls_kwargs__: A dictionary of keyword arguments for class creation, such as `metaclass`.
        __qualname__: The qualified name of the newly created model.
        **field_definitions: Field definitions of the new model. Either:

            - a single element, representing the type annotation of the field.
            - a two-tuple, the first element being the type and the second element the assigned value
              (either a default or the [`Field()`][pydantic.Field] function).

    Returns:
        The new [model][pydantic.BaseModel].

    Raises:
        PydanticUserError: If `__base__` and `__config__` are both passed.
    """
    if __base__ is None:
        __base__ = (cast('type[ModelT]', BaseModel),)
    elif not isinstance(__base__, tuple):
        __base__ = (__base__,)

    __cls_kwargs__ = __cls_kwargs__ or {}

    fields: dict[str, Any] = {}
    annotations: dict[str, Any] = {}

    for f_name, f_def in field_definitions.items():
        if isinstance(f_def, tuple):
            if len(f_def) != 2:
                raise PydanticUserError(
                    f'Field definition for {f_name!r} should a single element representing the type or a two-tuple, the first element '
                    'being the type and the second element the assigned value (either a default or the `Field()` function).',
                    code='create-model-field-definitions',
                )

            annotations[f_name] = f_def[0]
            fields[f_name] = f_def[1]
        else:
            annotations[f_name] = f_def

    if __module__ is None:
        f = sys._getframe(1)
        __module__ = f.f_globals['__name__']

    namespace: dict[str, Any] = {'__annotations__': annotations, '__module__': __module__}
    if __doc__:
        namespace['__doc__'] = __doc__
    if __qualname__ is not None:
        namespace['__qualname__'] = __qualname__
    if __validators__:
        namespace.update(__validators__)
    namespace.update(fields)
    if __config__:
        namespace['model_config'] = __config__
    resolved_bases = types.resolve_bases(__base__)
    meta, ns, kwds = types.prepare_class(model_name, resolved_bases, kwds=__cls_kwargs__)
    if resolved_bases is not __base__:
        ns['__orig_bases__'] = __base__
    namespace.update(ns)

    return meta(
        model_name,
        resolved_bases,
        namespace,
        __pydantic_reset_parent_namespace__=False,
        _create_model_module=__module__,
        **kwds,
    )


__getattr__ = getattr_migration(__name__)


import sys
import warnings
from abc import ABCMeta
from copy import deepcopy
from enum import Enum
from functools import partial
from pathlib import Path
from types import FunctionType, prepare_class, resolve_bases
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    no_type_check,
    overload,
)

from typing_extensions import dataclass_transform

from pydantic.v1.class_validators import ValidatorGroup, extract_root_validators, extract_validators, inherit_validators
from pydantic.v1.config import BaseConfig, Extra, inherit_config, prepare_config
from pydantic.v1.error_wrappers import ErrorWrapper, ValidationError
from pydantic.v1.errors import ConfigError, DictError, ExtraError, MissingError
from pydantic.v1.fields import (
    MAPPING_LIKE_SHAPES,
    Field,
    ModelField,
    ModelPrivateAttr,
    PrivateAttr,
    Undefined,
    is_finalvar_with_default_val,
)
from pydantic.v1.json import custom_pydantic_encoder, pydantic_encoder
from pydantic.v1.parse import Protocol, load_file, load_str_bytes
from pydantic.v1.schema import default_ref_template, model_schema
from pydantic.v1.types import PyObject, StrBytes
from pydantic.v1.typing import (
    AnyCallable,
    get_args,
    get_origin,
    is_classvar,
    is_namedtuple,
    is_union,
    resolve_annotations,
    update_model_forward_refs,
)
from pydantic.v1.utils import (
    DUNDER_ATTRIBUTES,
    ROOT_KEY,
    ClassAttribute,
    GetterDict,
    Representation,
    ValueItems,
    generate_model_signature,
    is_valid_field,
    is_valid_private_name,
    lenient_issubclass,
    sequence_like,
    smart_deepcopy,
    unique_list,
    validate_field_name,
)

if TYPE_CHECKING:
    from inspect import Signature

    from pydantic.v1.class_validators import ValidatorListDict
    from pydantic.v1.types import ModelOrDc
    from pydantic.v1.typing import (
        AbstractSetIntStr,
        AnyClassMethod,
        CallableGenerator,
        DictAny,
        DictStrAny,
        MappingIntStrAny,
        ReprArgs,
        SetStr,
        TupleGenerator,
    )

    Model = TypeVar('Model', bound='BaseModel')

__all__ = 'BaseModel', 'create_model', 'validate_model'

_T = TypeVar('_T')


def validate_custom_root_type(fields: Dict[str, ModelField]) -> None:
    if len(fields) > 1:
        raise ValueError(f'{ROOT_KEY} cannot be mixed with other fields')


def generate_hash_function(frozen: bool) -> Optional[Callable[[Any], int]]:
    def hash_function(self_: Any) -> int:
        return hash(self_.__class__) + hash(tuple(self_.__dict__.values()))

    return hash_function if frozen else None


# If a field is of type `Callable`, its default value should be a function and cannot to ignored.
ANNOTATED_FIELD_UNTOUCHED_TYPES: Tuple[Any, ...] = (property, type, classmethod, staticmethod)
# When creating a `BaseModel` instance, we bypass all the methods, properties... added to the model
UNTOUCHED_TYPES: Tuple[Any, ...] = (FunctionType,) + ANNOTATED_FIELD_UNTOUCHED_TYPES
# Note `ModelMetaclass` refers to `BaseModel`, but is also used to *create* `BaseModel`, so we need to add this extra
# (somewhat hacky) boolean to keep track of whether we've created the `BaseModel` class yet, and therefore whether it's
# safe to refer to it. If it *hasn't* been created, we assume that the `__new__` call we're in the middle of is for
# the `BaseModel` class, since that's defined immediately after the metaclass.
_is_base_model_class_defined = False


@dataclass_transform(kw_only_default=True, field_specifiers=(Field,))
class ModelMetaclass(ABCMeta):
    @no_type_check  # noqa C901
    def __new__(mcs, name, bases, namespace, **kwargs):  # noqa C901
        fields: Dict[str, ModelField] = {}
        config = BaseConfig
        validators: 'ValidatorListDict' = {}

        pre_root_validators, post_root_validators = [], []
        private_attributes: Dict[str, ModelPrivateAttr] = {}
        base_private_attributes: Dict[str, ModelPrivateAttr] = {}
        slots: SetStr = namespace.get('__slots__', ())
        slots = {slots} if isinstance(slots, str) else set(slots)
        class_vars: SetStr = set()
        hash_func: Optional[Callable[[Any], int]] = None

        for base in reversed(bases):
            if _is_base_model_class_defined and issubclass(base, BaseModel) and base != BaseModel:
                fields.update(smart_deepcopy(base.__fields__))
                config = inherit_config(base.__config__, config)
                validators = inherit_validators(base.__validators__, validators)
                pre_root_validators += base.__pre_root_validators__
                post_root_validators += base.__post_root_validators__
                base_private_attributes.update(base.__private_attributes__)
                class_vars.update(base.__class_vars__)
                hash_func = base.__hash__

        resolve_forward_refs = kwargs.pop('__resolve_forward_refs__', True)
        allowed_config_kwargs: SetStr = {
            key
            for key in dir(config)
            if not (key.startswith('__') and key.endswith('__'))  # skip dunder methods and attributes
        }
        config_kwargs = {key: kwargs.pop(key) for key in kwargs.keys() & allowed_config_kwargs}
        config_from_namespace = namespace.get('Config')
        if config_kwargs and config_from_namespace:
            raise TypeError('Specifying config in two places is ambiguous, use either Config attribute or class kwargs')
        config = inherit_config(config_from_namespace, config, **config_kwargs)

        validators = inherit_validators(extract_validators(namespace), validators)
        vg = ValidatorGroup(validators)

        for f in fields.values():
            f.set_config(config)
            extra_validators = vg.get_validators(f.name)
            if extra_validators:
                f.class_validators.update(extra_validators)
                # re-run prepare to add extra validators
                f.populate_validators()

        prepare_config(config, name)

        untouched_types = ANNOTATED_FIELD_UNTOUCHED_TYPES

        def is_untouched(v: Any) -> bool:
            return isinstance(v, untouched_types) or v.__class__.__name__ == 'cython_function_or_method'

        if (namespace.get('__module__'), namespace.get('__qualname__')) != ('pydantic.main', 'BaseModel'):
            if sys.version_info >= (3, 14):
                if '__annotations__' in namespace:
                    # `from __future__ import annotations` was used in the model's module
                    raw_annotations = namespace['__annotations__']
                else:
                    # See https://docs.python.org/3/library/annotationlib.html#using-annotations-in-a-metaclass:
                    from annotationlib import Format, call_annotate_function, get_annotate_from_class_namespace

                    annotate = get_annotate_from_class_namespace(namespace)
                    if annotate is not None:
                        raw_annotations = call_annotate_function(annotate, format=Format.FORWARDREF)
                    else:
                        raw_annotations = {}
            else:
                raw_annotations = namespace.get('__annotations__', {})

            annotations = resolve_annotations(raw_annotations, namespace.get('__module__', None))
            # annotation only fields need to come first in fields
            for ann_name, ann_type in annotations.items():
                if is_classvar(ann_type):
                    class_vars.add(ann_name)
                elif is_finalvar_with_default_val(ann_type, namespace.get(ann_name, Undefined)):
                    class_vars.add(ann_name)
                elif is_valid_field(ann_name):
                    validate_field_name(bases, ann_name)
                    value = namespace.get(ann_name, Undefined)
                    allowed_types = get_args(ann_type) if is_union(get_origin(ann_type)) else (ann_type,)
                    if (
                        is_untouched(value)
                        and ann_type != PyObject
                        and not any(
                            lenient_issubclass(get_origin(allowed_type), Type) for allowed_type in allowed_types
                        )
                    ):
                        continue
                    fields[ann_name] = ModelField.infer(
                        name=ann_name,
                        value=value,
                        annotation=ann_type,
                        class_validators=vg.get_validators(ann_name),
                        config=config,
                    )
                elif ann_name not in namespace and config.underscore_attrs_are_private:
                    private_attributes[ann_name] = PrivateAttr()

            untouched_types = UNTOUCHED_TYPES + config.keep_untouched
            for var_name, value in namespace.items():
                can_be_changed = var_name not in class_vars and not is_untouched(value)
                if isinstance(value, ModelPrivateAttr):
                    if not is_valid_private_name(var_name):
                        raise NameError(
                            f'Private attributes "{var_name}" must not be a valid field name; '
                            f'Use sunder or dunder names, e. g. "_{var_name}" or "__{var_name}__"'
                        )
                    private_attributes[var_name] = value
                elif config.underscore_attrs_are_private and is_valid_private_name(var_name) and can_be_changed:
                    private_attributes[var_name] = PrivateAttr(default=value)
                elif is_valid_field(var_name) and var_name not in annotations and can_be_changed:
                    validate_field_name(bases, var_name)
                    inferred = ModelField.infer(
                        name=var_name,
                        value=value,
                        annotation=annotations.get(var_name, Undefined),
                        class_validators=vg.get_validators(var_name),
                        config=config,
                    )
                    if var_name in fields:
                        if lenient_issubclass(inferred.type_, fields[var_name].type_):
                            inferred.type_ = fields[var_name].type_
                        else:
                            raise TypeError(
                                f'The type of {name}.{var_name} differs from the new default value; '
                                f'if you wish to change the type of this field, please use a type annotation'
                            )
                    fields[var_name] = inferred

        _custom_root_type = ROOT_KEY in fields
        if _custom_root_type:
            validate_custom_root_type(fields)
        vg.check_for_unused()
        if config.json_encoders:
            json_encoder = partial(custom_pydantic_encoder, config.json_encoders)
        else:
            json_encoder = pydantic_encoder
        pre_rv_new, post_rv_new = extract_root_validators(namespace)

        if hash_func is None:
            hash_func = generate_hash_function(config.frozen)

        exclude_from_namespace = fields | private_attributes.keys() | {'__slots__'}
        new_namespace = {
            '__config__': config,
            '__fields__': fields,
            '__exclude_fields__': {
                name: field.field_info.exclude for name, field in fields.items() if field.field_info.exclude is not None
            }
            or None,
            '__include_fields__': {
                name: field.field_info.include for name, field in fields.items() if field.field_info.include is not None
            }
            or None,
            '__validators__': vg.validators,
            '__pre_root_validators__': unique_list(
                pre_root_validators + pre_rv_new,
                name_factory=lambda v: v.__name__,
            ),
            '__post_root_validators__': unique_list(
                post_root_validators + post_rv_new,
                name_factory=lambda skip_on_failure_and_v: skip_on_failure_and_v[1].__name__,
            ),
            '__schema_cache__': {},
            '__json_encoder__': staticmethod(json_encoder),
            '__custom_root_type__': _custom_root_type,
            '__private_attributes__': {**base_private_attributes, **private_attributes},
            '__slots__': slots | private_attributes.keys(),
            '__hash__': hash_func,
            '__class_vars__': class_vars,
            **{n: v for n, v in namespace.items() if n not in exclude_from_namespace},
        }

        cls = super().__new__(mcs, name, bases, new_namespace, **kwargs)
        # set __signature__ attr only for model class, but not for its instances
        cls.__signature__ = ClassAttribute('__signature__', generate_model_signature(cls.__init__, fields, config))

        if not _is_base_model_class_defined:
            # Cython does not understand the `if TYPE_CHECKING:` condition in the
            # BaseModel's body (where annotations are set), so clear them manually:
            getattr(cls, '__annotations__', {}).clear()

        if resolve_forward_refs:
            cls.__try_update_forward_refs__()

        # preserve `__set_name__` protocol defined in https://peps.python.org/pep-0487
        # for attributes not in `new_namespace` (e.g. private attributes)
        for name, obj in namespace.items():
            if name not in new_namespace:
                set_name = getattr(obj, '__set_name__', None)
                if callable(set_name):
                    set_name(cls, name)

        return cls

    def __instancecheck__(self, instance: Any) -> bool:
        """
        Avoid calling ABC _abc_subclasscheck unless we're pretty sure.

        See #3829 and python/cpython#92810
        """
        return hasattr(instance, '__post_root_validators__') and super().__instancecheck__(instance)


object_setattr = object.__setattr__


class BaseModel(Representation, metaclass=ModelMetaclass):
    if TYPE_CHECKING:
        # populated by the metaclass, defined here to help IDEs only
        __fields__: ClassVar[Dict[str, ModelField]] = {}
        __include_fields__: ClassVar[Optional[Mapping[str, Any]]] = None
        __exclude_fields__: ClassVar[Optional[Mapping[str, Any]]] = None
        __validators__: ClassVar[Dict[str, AnyCallable]] = {}
        __pre_root_validators__: ClassVar[List[AnyCallable]]
        __post_root_validators__: ClassVar[List[Tuple[bool, AnyCallable]]]
        __config__: ClassVar[Type[BaseConfig]] = BaseConfig
        __json_encoder__: ClassVar[Callable[[Any], Any]] = lambda x: x
        __schema_cache__: ClassVar['DictAny'] = {}
        __custom_root_type__: ClassVar[bool] = False
        __signature__: ClassVar['Signature']
        __private_attributes__: ClassVar[Dict[str, ModelPrivateAttr]]
        __class_vars__: ClassVar[SetStr]
        __fields_set__: ClassVar[SetStr] = set()

    Config = BaseConfig
    __slots__ = ('__dict__', '__fields_set__')
    __doc__ = ''  # Null out the Representation docstring

    def __init__(__pydantic_self__, **data: Any) -> None:
        """
        Create a new model by parsing and validating input data from keyword arguments.

        Raises ValidationError if the input data cannot be parsed to form a valid model.
        """
        # Uses something other than `self` the first arg to allow "self" as a settable attribute
        values, fields_set, validation_error = validate_model(__pydantic_self__.__class__, data)
        if validation_error:
            raise validation_error
        try:
            object_setattr(__pydantic_self__, '__dict__', values)
        except TypeError as e:
            raise TypeError(
                'Model values must be a dict; you may not have returned a dictionary from a root validator'
            ) from e
        object_setattr(__pydantic_self__, '__fields_set__', fields_set)
        __pydantic_self__._init_private_attributes()

    @no_type_check
    def __setattr__(self, name, value):  # noqa: C901 (ignore complexity)
        if name in self.__private_attributes__ or name in DUNDER_ATTRIBUTES:
            return object_setattr(self, name, value)

        if self.__config__.extra is not Extra.allow and name not in self.__fields__:
            raise ValueError(f'"{self.__class__.__name__}" object has no field "{name}"')
        elif not self.__config__.allow_mutation or self.__config__.frozen:
            raise TypeError(f'"{self.__class__.__name__}" is immutable and does not support item assignment')
        elif name in self.__fields__ and self.__fields__[name].final:
            raise TypeError(
                f'"{self.__class__.__name__}" object "{name}" field is final and does not support reassignment'
            )
        elif self.__config__.validate_assignment:
            new_values = {**self.__dict__, name: value}

            for validator in self.__pre_root_validators__:
                try:
                    new_values = validator(self.__class__, new_values)
                except (ValueError, TypeError, AssertionError) as exc:
                    raise ValidationError([ErrorWrapper(exc, loc=ROOT_KEY)], self.__class__)

            known_field = self.__fields__.get(name, None)
            if known_field:
                # We want to
                # - make sure validators are called without the current value for this field inside `values`
                # - keep other values (e.g. submodels) untouched (using `BaseModel.dict()` will change them into dicts)
                # - keep the order of the fields
                if not known_field.field_info.allow_mutation:
                    raise TypeError(f'"{known_field.name}" has allow_mutation set to False and cannot be assigned')
                dict_without_original_value = {k: v for k, v in self.__dict__.items() if k != name}
                value, error_ = known_field.validate(value, dict_without_original_value, loc=name, cls=self.__class__)
                if error_:
                    raise ValidationError([error_], self.__class__)
                else:
                    new_values[name] = value

            errors = []
            for skip_on_failure, validator in self.__post_root_validators__:
                if skip_on_failure and errors:
                    continue
                try:
                    new_values = validator(self.__class__, new_values)
                except (ValueError, TypeError, AssertionError) as exc:
                    errors.append(ErrorWrapper(exc, loc=ROOT_KEY))
            if errors:
                raise ValidationError(errors, self.__class__)

            # update the whole __dict__ as other values than just `value`
            # may be changed (e.g. with `root_validator`)
            object_setattr(self, '__dict__', new_values)
        else:
            self.__dict__[name] = value

        self.__fields_set__.add(name)

    def __getstate__(self) -> 'DictAny':
        private_attrs = ((k, getattr(self, k, Undefined)) for k in self.__private_attributes__)
        return {
            '__dict__': self.__dict__,
            '__fields_set__': self.__fields_set__,
            '__private_attribute_values__': {k: v for k, v in private_attrs if v is not Undefined},
        }

    def __setstate__(self, state: 'DictAny') -> None:
        object_setattr(self, '__dict__', state['__dict__'])
        object_setattr(self, '__fields_set__', state['__fields_set__'])
        for name, value in state.get('__private_attribute_values__', {}).items():
            object_setattr(self, name, value)

    def _init_private_attributes(self) -> None:
        for name, private_attr in self.__private_attributes__.items():
            default = private_attr.get_default()
            if default is not Undefined:
                object_setattr(self, name, default)

    def dict(
        self,
        *,
        include: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']] = None,
        exclude: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']] = None,
        by_alias: bool = False,
        skip_defaults: Optional[bool] = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
    ) -> 'DictStrAny':
        """
        Generate a dictionary representation of the model, optionally specifying which fields to include or exclude.

        """
        if skip_defaults is not None:
            warnings.warn(
                f'{self.__class__.__name__}.dict(): "skip_defaults" is deprecated and replaced by "exclude_unset"',
                DeprecationWarning,
            )
            exclude_unset = skip_defaults

        return dict(
            self._iter(
                to_dict=True,
                by_alias=by_alias,
                include=include,
                exclude=exclude,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
            )
        )

    def json(
        self,
        *,
        include: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']] = None,
        exclude: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']] = None,
        by_alias: bool = False,
        skip_defaults: Optional[bool] = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        encoder: Optional[Callable[[Any], Any]] = None,
        models_as_dict: bool = True,
        **dumps_kwargs: Any,
    ) -> str:
        """
        Generate a JSON representation of the model, `include` and `exclude` arguments as per `dict()`.

        `encoder` is an optional function to supply as `default` to json.dumps(), other arguments as per `json.dumps()`.
        """
        if skip_defaults is not None:
            warnings.warn(
                f'{self.__class__.__name__}.json(): "skip_defaults" is deprecated and replaced by "exclude_unset"',
                DeprecationWarning,
            )
            exclude_unset = skip_defaults
        encoder = cast(Callable[[Any], Any], encoder or self.__json_encoder__)

        # We don't directly call `self.dict()`, which does exactly this with `to_dict=True`
        # because we want to be able to keep raw `BaseModel` instances and not as `dict`.
        # This allows users to write custom JSON encoders for given `BaseModel` classes.
        data = dict(
            self._iter(
                to_dict=models_as_dict,
                by_alias=by_alias,
                include=include,
                exclude=exclude,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
            )
        )
        if self.__custom_root_type__:
            data = data[ROOT_KEY]
        return self.__config__.json_dumps(data, default=encoder, **dumps_kwargs)

    @classmethod
    def _enforce_dict_if_root(cls, obj: Any) -> Any:
        if cls.__custom_root_type__ and (
            not (isinstance(obj, dict) and obj.keys() == {ROOT_KEY})
            and not (isinstance(obj, BaseModel) and obj.__fields__.keys() == {ROOT_KEY})
            or cls.__fields__[ROOT_KEY].shape in MAPPING_LIKE_SHAPES
        ):
            return {ROOT_KEY: obj}
        else:
            return obj

    @classmethod
    def parse_obj(cls: Type['Model'], obj: Any) -> 'Model':
        obj = cls._enforce_dict_if_root(obj)
        if not isinstance(obj, dict):
            try:
                obj = dict(obj)
            except (TypeError, ValueError) as e:
                exc = TypeError(f'{cls.__name__} expected dict not {obj.__class__.__name__}')
                raise ValidationError([ErrorWrapper(exc, loc=ROOT_KEY)], cls) from e
        return cls(**obj)

    @classmethod
    def parse_raw(
        cls: Type['Model'],
        b: StrBytes,
        *,
        content_type: str = None,
        encoding: str = 'utf8',
        proto: Protocol = None,
        allow_pickle: bool = False,
    ) -> 'Model':
        try:
            obj = load_str_bytes(
                b,
                proto=proto,
                content_type=content_type,
                encoding=encoding,
                allow_pickle=allow_pickle,
                json_loads=cls.__config__.json_loads,
            )
        except (ValueError, TypeError, UnicodeDecodeError) as e:
            raise ValidationError([ErrorWrapper(e, loc=ROOT_KEY)], cls)
        return cls.parse_obj(obj)

    @classmethod
    def parse_file(
        cls: Type['Model'],
        path: Union[str, Path],
        *,
        content_type: str = None,
        encoding: str = 'utf8',
        proto: Protocol = None,
        allow_pickle: bool = False,
    ) -> 'Model':
        obj = load_file(
            path,
            proto=proto,
            content_type=content_type,
            encoding=encoding,
            allow_pickle=allow_pickle,
            json_loads=cls.__config__.json_loads,
        )
        return cls.parse_obj(obj)

    @classmethod
    def from_orm(cls: Type['Model'], obj: Any) -> 'Model':
        if not cls.__config__.orm_mode:
            raise ConfigError('You must have the config attribute orm_mode=True to use from_orm')
        obj = {ROOT_KEY: obj} if cls.__custom_root_type__ else cls._decompose_class(obj)
        m = cls.__new__(cls)
        values, fields_set, validation_error = validate_model(cls, obj)
        if validation_error:
            raise validation_error
        object_setattr(m, '__dict__', values)
        object_setattr(m, '__fields_set__', fields_set)
        m._init_private_attributes()
        return m

    @classmethod
    def construct(cls: Type['Model'], _fields_set: Optional['SetStr'] = None, **values: Any) -> 'Model':
        """
        Creates a new model setting __dict__ and __fields_set__ from trusted or pre-validated data.
        Default values are respected, but no other validation is performed.
        Behaves as if `Config.extra = 'allow'` was set since it adds all passed values
        """
        m = cls.__new__(cls)
        fields_values: Dict[str, Any] = {}
        for name, field in cls.__fields__.items():
            if field.alt_alias and field.alias in values:
                fields_values[name] = values[field.alias]
            elif name in values:
                fields_values[name] = values[name]
            elif not field.required:
                fields_values[name] = field.get_default()
        fields_values.update(values)
        object_setattr(m, '__dict__', fields_values)
        if _fields_set is None:
            _fields_set = set(values.keys())
        object_setattr(m, '__fields_set__', _fields_set)
        m._init_private_attributes()
        return m

    def _copy_and_set_values(self: 'Model', values: 'DictStrAny', fields_set: 'SetStr', *, deep: bool) -> 'Model':
        if deep:
            # chances of having empty dict here are quite low for using smart_deepcopy
            values = deepcopy(values)

        cls = self.__class__
        m = cls.__new__(cls)
        object_setattr(m, '__dict__', values)
        object_setattr(m, '__fields_set__', fields_set)
        for name in self.__private_attributes__:
            value = getattr(self, name, Undefined)
            if value is not Undefined:
                if deep:
                    value = deepcopy(value)
                object_setattr(m, name, value)

        return m

    def copy(
        self: 'Model',
        *,
        include: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']] = None,
        exclude: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']] = None,
        update: Optional['DictStrAny'] = None,
        deep: bool = False,
    ) -> 'Model':
        """
        Duplicate a model, optionally choose which fields to include, exclude and change.

        :param include: fields to include in new model
        :param exclude: fields to exclude from new model, as with values this takes precedence over include
        :param update: values to change/add in the new model. Note: the data is not validated before creating
            the new model: you should trust this data
        :param deep: set to `True` to make a deep copy of the model
        :return: new model instance
        """

        values = dict(
            self._iter(to_dict=False, by_alias=False, include=include, exclude=exclude, exclude_unset=False),
            **(update or {}),
        )

        # new `__fields_set__` can have unset optional fields with a set value in `update` kwarg
        if update:
            fields_set = self.__fields_set__ | update.keys()
        else:
            fields_set = set(self.__fields_set__)

        return self._copy_and_set_values(values, fields_set, deep=deep)

    @classmethod
    def schema(cls, by_alias: bool = True, ref_template: str = default_ref_template) -> 'DictStrAny':
        cached = cls.__schema_cache__.get((by_alias, ref_template))
        if cached is not None:
            return cached
        s = model_schema(cls, by_alias=by_alias, ref_template=ref_template)
        cls.__schema_cache__[(by_alias, ref_template)] = s
        return s

    @classmethod
    def schema_json(
        cls, *, by_alias: bool = True, ref_template: str = default_ref_template, **dumps_kwargs: Any
    ) -> str:
        from pydantic.v1.json import pydantic_encoder

        return cls.__config__.json_dumps(
            cls.schema(by_alias=by_alias, ref_template=ref_template), default=pydantic_encoder, **dumps_kwargs
        )

    @classmethod
    def __get_validators__(cls) -> 'CallableGenerator':
        yield cls.validate

    @classmethod
    def validate(cls: Type['Model'], value: Any) -> 'Model':
        if isinstance(value, cls):
            copy_on_model_validation = cls.__config__.copy_on_model_validation
            # whether to deep or shallow copy the model on validation, None means do not copy
            deep_copy: Optional[bool] = None
            if copy_on_model_validation not in {'deep', 'shallow', 'none'}:
                # Warn about deprecated behavior
                warnings.warn(
                    "`copy_on_model_validation` should be a string: 'deep', 'shallow' or 'none'", DeprecationWarning
                )
                if copy_on_model_validation:
                    deep_copy = False

            if copy_on_model_validation == 'shallow':
                # shallow copy
                deep_copy = False
            elif copy_on_model_validation == 'deep':
                # deep copy
                deep_copy = True

            if deep_copy is None:
                return value
            else:
                return value._copy_and_set_values(value.__dict__, value.__fields_set__, deep=deep_copy)

        value = cls._enforce_dict_if_root(value)

        if isinstance(value, dict):
            return cls(**value)
        elif cls.__config__.orm_mode:
            return cls.from_orm(value)
        else:
            try:
                value_as_dict = dict(value)
            except (TypeError, ValueError) as e:
                raise DictError() from e
            return cls(**value_as_dict)

    @classmethod
    def _decompose_class(cls: Type['Model'], obj: Any) -> GetterDict:
        if isinstance(obj, GetterDict):
            return obj
        return cls.__config__.getter_dict(obj)

    @classmethod
    @no_type_check
    def _get_value(
        cls,
        v: Any,
        to_dict: bool,
        by_alias: bool,
        include: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']],
        exclude: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']],
        exclude_unset: bool,
        exclude_defaults: bool,
        exclude_none: bool,
    ) -> Any:
        if isinstance(v, BaseModel):
            if to_dict:
                v_dict = v.dict(
                    by_alias=by_alias,
                    exclude_unset=exclude_unset,
                    exclude_defaults=exclude_defaults,
                    include=include,
                    exclude=exclude,
                    exclude_none=exclude_none,
                )
                if ROOT_KEY in v_dict:
                    return v_dict[ROOT_KEY]
                return v_dict
            else:
                return v.copy(include=include, exclude=exclude)

        value_exclude = ValueItems(v, exclude) if exclude else None
        value_include = ValueItems(v, include) if include else None

        if isinstance(v, dict):
            return {
                k_: cls._get_value(
                    v_,
                    to_dict=to_dict,
                    by_alias=by_alias,
                    exclude_unset=exclude_unset,
                    exclude_defaults=exclude_defaults,
                    include=value_include and value_include.for_element(k_),
                    exclude=value_exclude and value_exclude.for_element(k_),
                    exclude_none=exclude_none,
                )
                for k_, v_ in v.items()
                if (not value_exclude or not value_exclude.is_excluded(k_))
                and (not value_include or value_include.is_included(k_))
            }

        elif sequence_like(v):
            seq_args = (
                cls._get_value(
                    v_,
                    to_dict=to_dict,
                    by_alias=by_alias,
                    exclude_unset=exclude_unset,
                    exclude_defaults=exclude_defaults,
                    include=value_include and value_include.for_element(i),
                    exclude=value_exclude and value_exclude.for_element(i),
                    exclude_none=exclude_none,
                )
                for i, v_ in enumerate(v)
                if (not value_exclude or not value_exclude.is_excluded(i))
                and (not value_include or value_include.is_included(i))
            )

            return v.__class__(*seq_args) if is_namedtuple(v.__class__) else v.__class__(seq_args)

        elif isinstance(v, Enum) and getattr(cls.Config, 'use_enum_values', False):
            return v.value

        else:
            return v

    @classmethod
    def __try_update_forward_refs__(cls, **localns: Any) -> None:
        """
        Same as update_forward_refs but will not raise exception
        when forward references are not defined.
        """
        update_model_forward_refs(cls, cls.__fields__.values(), cls.__config__.json_encoders, localns, (NameError,))

    @classmethod
    def update_forward_refs(cls, **localns: Any) -> None:
        """
        Try to update ForwardRefs on fields based on this Model, globalns and localns.
        """
        update_model_forward_refs(cls, cls.__fields__.values(), cls.__config__.json_encoders, localns)

    def __iter__(self) -> 'TupleGenerator':
        """
        so `dict(model)` works
        """
        yield from self.__dict__.items()

    def _iter(
        self,
        to_dict: bool = False,
        by_alias: bool = False,
        include: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']] = None,
        exclude: Optional[Union['AbstractSetIntStr', 'MappingIntStrAny']] = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
    ) -> 'TupleGenerator':
        # Merge field set excludes with explicit exclude parameter with explicit overriding field set options.
        # The extra "is not None" guards are not logically necessary but optimizes performance for the simple case.
        if exclude is not None or self.__exclude_fields__ is not None:
            exclude = ValueItems.merge(self.__exclude_fields__, exclude)

        if include is not None or self.__include_fields__ is not None:
            include = ValueItems.merge(self.__include_fields__, include, intersect=True)

        allowed_keys = self._calculate_keys(
            include=include, exclude=exclude, exclude_unset=exclude_unset  # type: ignore
        )
        if allowed_keys is None and not (to_dict or by_alias or exclude_unset or exclude_defaults or exclude_none):
            # huge boost for plain _iter()
            yield from self.__dict__.items()
            return

        value_exclude = ValueItems(self, exclude) if exclude is not None else None
        value_include = ValueItems(self, include) if include is not None else None

        for field_key, v in self.__dict__.items():
            if (allowed_keys is not None and field_key not in allowed_keys) or (exclude_none and v is None):
                continue

            if exclude_defaults:
                model_field = self.__fields__.get(field_key)
                if not getattr(model_field, 'required', True) and getattr(model_field, 'default', _missing) == v:
                    continue

            if by_alias and field_key in self.__fields__:
                dict_key = self.__fields__[field_key].alias
            else:
                dict_key = field_key

            if to_dict or value_include or value_exclude:
                v = self._get_value(
                    v,
                    to_dict=to_dict,
                    by_alias=by_alias,
                    include=value_include and value_include.for_element(field_key),
                    exclude=value_exclude and value_exclude.for_element(field_key),
                    exclude_unset=exclude_unset,
                    exclude_defaults=exclude_defaults,
                    exclude_none=exclude_none,
                )
            yield dict_key, v

    def _calculate_keys(
        self,
        include: Optional['MappingIntStrAny'],
        exclude: Optional['MappingIntStrAny'],
        exclude_unset: bool,
        update: Optional['DictStrAny'] = None,
    ) -> Optional[AbstractSet[str]]:
        if include is None and exclude is None and exclude_unset is False:
            return None

        keys: AbstractSet[str]
        if exclude_unset:
            keys = self.__fields_set__.copy()
        else:
            keys = self.__dict__.keys()

        if include is not None:
            keys &= include.keys()

        if update:
            keys -= update.keys()

        if exclude:
            keys -= {k for k, v in exclude.items() if ValueItems.is_true(v)}

        return keys

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, BaseModel):
            return self.dict() == other.dict()
        else:
            return self.dict() == other

    def __repr_args__(self) -> 'ReprArgs':
        return [
            (k, v)
            for k, v in self.__dict__.items()
            if k not in DUNDER_ATTRIBUTES and (k not in self.__fields__ or self.__fields__[k].field_info.repr)
        ]


_is_base_model_class_defined = True


@overload
def create_model(
    __model_name: str,
    *,
    __config__: Optional[Type[BaseConfig]] = None,
    __base__: None = None,
    __module__: str = __name__,
    __validators__: Dict[str, 'AnyClassMethod'] = None,
    __cls_kwargs__: Dict[str, Any] = None,
    **field_definitions: Any,
) -> Type['BaseModel']:
    ...


@overload
def create_model(
    __model_name: str,
    *,
    __config__: Optional[Type[BaseConfig]] = None,
    __base__: Union[Type['Model'], Tuple[Type['Model'], ...]],
    __module__: str = __name__,
    __validators__: Dict[str, 'AnyClassMethod'] = None,
    __cls_kwargs__: Dict[str, Any] = None,
    **field_definitions: Any,
) -> Type['Model']:
    ...


def create_model(
    __model_name: str,
    *,
    __config__: Optional[Type[BaseConfig]] = None,
    __base__: Union[None, Type['Model'], Tuple[Type['Model'], ...]] = None,
    __module__: str = __name__,
    __validators__: Dict[str, 'AnyClassMethod'] = None,
    __cls_kwargs__: Dict[str, Any] = None,
    __slots__: Optional[Tuple[str, ...]] = None,
    **field_definitions: Any,
) -> Type['Model']:
    """
    Dynamically create a model.
    :param __model_name: name of the created model
    :param __config__: config class to use for the new model
    :param __base__: base class for the new model to inherit from
    :param __module__: module of the created model
    :param __validators__: a dict of method names and @validator class methods
    :param __cls_kwargs__: a dict for class creation
    :param __slots__: Deprecated, `__slots__` should not be passed to `create_model`
    :param field_definitions: fields of the model (or extra fields if a base is supplied)
        in the format `<name>=(<type>, <default default>)` or `<name>=<default value>, e.g.
        `foobar=(str, ...)` or `foobar=123`, or, for complex use-cases, in the format
        `<name>=<Field>` or `<name>=(<type>, <FieldInfo>)`, e.g.
        `foo=Field(datetime, default_factory=datetime.utcnow, alias='bar')` or
        `foo=(str, FieldInfo(title='Foo'))`
    """
    if __slots__ is not None:
        # __slots__ will be ignored from here on
        warnings.warn('__slots__ should not be passed to create_model', RuntimeWarning)

    if __base__ is not None:
        if __config__ is not None:
            raise ConfigError('to avoid confusion __config__ and __base__ cannot be used together')
        if not isinstance(__base__, tuple):
            __base__ = (__base__,)
    else:
        __base__ = (cast(Type['Model'], BaseModel),)

    __cls_kwargs__ = __cls_kwargs__ or {}

    fields = {}
    annotations = {}

    for f_name, f_def in field_definitions.items():
        if not is_valid_field(f_name):
            warnings.warn(f'fields may not start with an underscore, ignoring "{f_name}"', RuntimeWarning)
        if isinstance(f_def, tuple):
            try:
                f_annotation, f_value = f_def
            except ValueError as e:
                raise ConfigError(
                    'field definitions should either be a tuple of (<type>, <default>) or just a '
                    'default value, unfortunately this means tuples as '
                    'default values are not allowed'
                ) from e
        else:
            f_annotation, f_value = None, f_def

        if f_annotation:
            annotations[f_name] = f_annotation
        fields[f_name] = f_value

    namespace: 'DictStrAny' = {'__annotations__': annotations, '__module__': __module__}
    if __validators__:
        namespace.update(__validators__)
    namespace.update(fields)
    if __config__:
        namespace['Config'] = inherit_config(__config__, BaseConfig)
    resolved_bases = resolve_bases(__base__)
    meta, ns, kwds = prepare_class(__model_name, resolved_bases, kwds=__cls_kwargs__)
    if resolved_bases is not __base__:
        ns['__orig_bases__'] = __base__
    namespace.update(ns)
    return meta(__model_name, resolved_bases, namespace, **kwds)


_missing = object()


def validate_model(  # noqa: C901 (ignore complexity)
    model: Type[BaseModel], input_data: 'DictStrAny', cls: 'ModelOrDc' = None
) -> Tuple['DictStrAny', 'SetStr', Optional[ValidationError]]:
    """
    validate data against a model.
    """
    values = {}
    errors = []
    # input_data names, possibly alias
    names_used = set()
    # field names, never aliases
    fields_set = set()
    config = model.__config__
    check_extra = config.extra is not Extra.ignore
    cls_ = cls or model

    for validator in model.__pre_root_validators__:
        try:
            input_data = validator(cls_, input_data)
        except (ValueError, TypeError, AssertionError) as exc:
            return {}, set(), ValidationError([ErrorWrapper(exc, loc=ROOT_KEY)], cls_)

    for name, field in model.__fields__.items():
        value = input_data.get(field.alias, _missing)
        using_name = False
        if value is _missing and config.allow_population_by_field_name and field.alt_alias:
            value = input_data.get(field.name, _missing)
            using_name = True

        if value is _missing:
            if field.required:
                errors.append(ErrorWrapper(MissingError(), loc=field.alias))
                continue

            value = field.get_default()

            if not config.validate_all and not field.validate_always:
                values[name] = value
                continue
        else:
            fields_set.add(name)
            if check_extra:
                names_used.add(field.name if using_name else field.alias)

        v_, errors_ = field.validate(value, values, loc=field.alias, cls=cls_)
        if isinstance(errors_, ErrorWrapper):
            errors.append(errors_)
        elif isinstance(errors_, list):
            errors.extend(errors_)
        else:
            values[name] = v_

    if check_extra:
        if isinstance(input_data, GetterDict):
            extra = input_data.extra_keys() - names_used
        else:
            extra = input_data.keys() - names_used
        if extra:
            fields_set |= extra
            if config.extra is Extra.allow:
                for f in extra:
                    values[f] = input_data[f]
            else:
                for f in sorted(extra):
                    errors.append(ErrorWrapper(ExtraError(), loc=f))

    for skip_on_failure, validator in model.__post_root_validators__:
        if skip_on_failure and errors:
            continue
        try:
            values = validator(cls_, values)
        except (ValueError, TypeError, AssertionError) as exc:
            errors.append(ErrorWrapper(exc, loc=ROOT_KEY))

    if errors:
        return values, fields_set, ValidationError(errors, cls_)
    else:
        return values, fields_set, None


from __future__ import annotations

import asyncio
import logging
import os
import platform
import ssl
import sys
import warnings
from collections.abc import Callable
from configparser import RawConfigParser
from typing import IO, Any, get_args

import click

import uvicorn
from uvicorn._types import ASGIApplication
from uvicorn.config import (
    INTERFACES,
    LIFESPAN,
    LOG_LEVELS,
    LOGGING_CONFIG,
    SSL_PROTOCOL_VERSION,
    STARTUP_FAILURE,
    Config,
    HTTPProtocolType,
    InterfaceType,
    LifespanType,
    LoopFactoryType,
    WSProtocolType,
)
from uvicorn.server import Server
from uvicorn.supervisors import ChangeReload, Multiprocess

LEVEL_CHOICES = click.Choice(list(LOG_LEVELS.keys()))
LIFESPAN_CHOICES = click.Choice(list(LIFESPAN.keys()))
INTERFACE_CHOICES = click.Choice(INTERFACES)


def _metavar_from_type(_type: Any) -> str:
    return f"[{'|'.join(key for key in get_args(_type) if key != 'none')}]"


logger = logging.getLogger("uvicorn.error")


def print_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(
        "Running uvicorn {version} with {py_implementation} {py_version} on {system}".format(  # noqa: UP032
            version=uvicorn.__version__,
            py_implementation=platform.python_implementation(),
            py_version=platform.python_version(),
            system=platform.system(),
        )
    )
    ctx.exit()


@click.command(context_settings={"auto_envvar_prefix": "UVICORN"})
@click.argument("app", envvar="UVICORN_APP")
@click.option(
    "--host",
    type=str,
    default="127.0.0.1",
    help="Bind socket to this host.",
    show_default=True,
)
@click.option(
    "--port",
    type=int,
    default=8000,
    help="Bind socket to this port. If 0, an available port will be picked.",
    show_default=True,
)
@click.option("--uds", type=str, default=None, help="Bind to a UNIX domain socket.")
@click.option("--fd", type=int, default=None, help="Bind to socket from this file descriptor.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload.")
@click.option(
    "--reload-dir",
    "reload_dirs",
    multiple=True,
    help="Set reload directories explicitly, instead of using the current working directory.",
    type=click.Path(exists=True),
)
@click.option(
    "--reload-include",
    "reload_includes",
    multiple=True,
    help="Set glob patterns to include while watching for files. Includes '*.py' "
    "by default; these defaults can be overridden with `--reload-exclude`. "
    "This option has no effect unless watchfiles is installed.",
)
@click.option(
    "--reload-exclude",
    "reload_excludes",
    multiple=True,
    help="Set glob patterns to exclude while watching for files. Includes "
    "'.*, .py[cod], .sw.*, ~*' by default; these defaults can be overridden "
    "with `--reload-include`. This option has no effect unless watchfiles is "
    "installed.",
)
@click.option(
    "--reload-delay",
    type=float,
    default=0.25,
    show_default=True,
    help="Delay between previous and next check if application needs to be. Defaults to 0.25s.",
)
@click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of worker processes. Defaults to the $WEB_CONCURRENCY environment"
    " variable if available, or 1. Not valid with --reload.",
)
@click.option(
    "--loop",
    type=str,
    metavar=_metavar_from_type(LoopFactoryType),
    default="auto",
    help="Event loop factory implementation.",
    show_default=True,
)
@click.option(
    "--http",
    type=str,
    metavar=_metavar_from_type(HTTPProtocolType),
    default="auto",
    help="HTTP protocol implementation.",
    show_default=True,
)
@click.option(
    "--ws",
    type=str,
    metavar=_metavar_from_type(WSProtocolType),
    default="auto",
    help="WebSocket protocol implementation.",
    show_default=True,
)
@click.option(
    "--ws-max-size",
    type=int,
    default=16777216,
    help="WebSocket max size message in bytes",
    show_default=True,
)
@click.option(
    "--ws-max-queue",
    type=int,
    default=32,
    help="The maximum length of the WebSocket message queue.",
    show_default=True,
)
@click.option(
    "--ws-ping-interval",
    type=float,
    default=20.0,
    help="WebSocket ping interval in seconds.",
    show_default=True,
)
@click.option(
    "--ws-ping-timeout",
    type=float,
    default=20.0,
    help="WebSocket ping timeout in seconds.",
    show_default=True,
)
@click.option(
    "--ws-per-message-deflate",
    type=bool,
    default=True,
    help="WebSocket per-message-deflate compression",
    show_default=True,
)
@click.option(
    "--lifespan",
    type=LIFESPAN_CHOICES,
    default="auto",
    help="Lifespan implementation.",
    show_default=True,
)
@click.option(
    "--interface",
    type=INTERFACE_CHOICES,
    default="auto",
    help="Select ASGI3, ASGI2, or WSGI as the application interface.",
    show_default=True,
)
@click.option(
    "--env-file",
    type=click.Path(exists=True),
    default=None,
    help="Environment configuration file.",
    show_default=True,
)
@click.option(
    "--log-config",
    type=click.Path(exists=True),
    default=None,
    help="Logging configuration file. Supported formats: .ini, .json, .yaml.",
    show_default=True,
)
@click.option(
    "--log-level",
    type=LEVEL_CHOICES,
    default=None,
    help="Log level. [default: info]",
    show_default=True,
)
@click.option(
    "--access-log/--no-access-log",
    is_flag=True,
    default=True,
    help="Enable/Disable access log.",
)
@click.option(
    "--use-colors/--no-use-colors",
    is_flag=True,
    default=None,
    help="Enable/Disable colorized logging.",
)
@click.option(
    "--proxy-headers/--no-proxy-headers",
    is_flag=True,
    default=True,
    help="Enable/Disable X-Forwarded-Proto, X-Forwarded-For to populate url scheme and remote address info.",
)
@click.option(
    "--server-header/--no-server-header",
    is_flag=True,
    default=True,
    help="Enable/Disable default Server header.",
)
@click.option(
    "--date-header/--no-date-header",
    is_flag=True,
    default=True,
    help="Enable/Disable default Date header.",
)
@click.option(
    "--forwarded-allow-ips",
    type=str,
    default=None,
    help="Comma separated list of IP Addresses, IP Networks, or literals "
    "(e.g. UNIX Socket path) to trust with proxy headers. Defaults to the "
    "$FORWARDED_ALLOW_IPS environment variable if available, or '127.0.0.1'. "
    "The literal '*' means trust everything.",
)
@click.option(
    "--root-path",
    type=str,
    default="",
    help="Set the ASGI 'root_path' for applications submounted below a given URL path.",
)
@click.option(
    "--limit-concurrency",
    type=int,
    default=None,
    help="Maximum number of concurrent connections or tasks to allow, before issuing HTTP 503 responses.",
)
@click.option(
    "--backlog",
    type=int,
    default=2048,
    help="Maximum number of connections to hold in backlog",
)
@click.option(
    "--limit-max-requests",
    type=int,
    default=None,
    help="Maximum number of requests to service before terminating the process.",
)
@click.option(
    "--limit-max-requests-jitter",
    type=int,
    default=0,
    help="Maximum jitter to add to limit_max_requests."
    " Staggers worker restarts to avoid all workers restarting simultaneously.",
    show_default=True,
)
@click.option(
    "--timeout-keep-alive",
    type=int,
    default=5,
    help="Close Keep-Alive connections if no new data is received within this timeout (in seconds).",
    show_default=True,
)
@click.option(
    "--timeout-graceful-shutdown",
    type=int,
    default=None,
    help="Maximum number of seconds to wait for graceful shutdown.",
)
@click.option(
    "--timeout-worker-healthcheck",
    type=int,
    default=5,
    help="Maximum number of seconds to wait for a worker to respond to a healthcheck.",
    show_default=True,
)
@click.option("--ssl-keyfile", type=str, default=None, help="SSL key file", show_default=True)
@click.option(
    "--ssl-certfile",
    type=str,
    default=None,
    help="SSL certificate file",
    show_default=True,
)
@click.option(
    "--ssl-keyfile-password",
    type=str,
    default=None,
    help="SSL keyfile password",
    show_default=True,
)
@click.option(
    "--ssl-version",
    type=int,
    default=int(SSL_PROTOCOL_VERSION),
    help="SSL version to use (see stdlib ssl module's)",
    show_default=True,
)
@click.option(
    "--ssl-cert-reqs",
    type=int,
    default=int(ssl.CERT_NONE),
    help="Whether client certificate is required (see stdlib ssl module's)",
    show_default=True,
)
@click.option(
    "--ssl-ca-certs",
    type=str,
    default=None,
    help="CA certificates file",
    show_default=True,
)
@click.option(
    "--ssl-ciphers",
    type=str,
    default=None,
    help="Ciphers to use (see stdlib ssl module's). Defaults to OpenSSL's safe defaults.",
    show_default=True,
)
@click.option(
    "--header",
    "headers",
    multiple=True,
    help="Specify custom default HTTP response headers as a Name:Value pair",
)
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Display the uvicorn version and exit.",
)
@click.option(
    "--app-dir",
    default="",
    show_default=True,
    help="Look for APP in the specified directory, by adding this to the PYTHONPATH."
    " Defaults to the current working directory.",
)
@click.option(
    "--h11-max-incomplete-event-size",
    "h11_max_incomplete_event_size",
    type=int,
    default=None,
    help="For h11, the maximum number of bytes to buffer of an incomplete event.",
)
@click.option(
    "--reset-contextvars",
    is_flag=True,
    default=False,
    help="Run each ASGI request in a fresh contextvars.Context. Hides context set in the lifespan.",
    show_default=True,
)
@click.option(
    "--factory",
    is_flag=True,
    default=False,
    help="Treat APP as an application factory, i.e. a () -> <ASGI app> callable.",
    show_default=True,
)
def main(
    app: str,
    host: str,
    port: int,
    uds: str,
    fd: int,
    loop: LoopFactoryType | str,
    http: HTTPProtocolType | str,
    ws: WSProtocolType | str,
    ws_max_size: int,
    ws_max_queue: int,
    ws_ping_interval: float,
    ws_ping_timeout: float,
    ws_per_message_deflate: bool,
    lifespan: LifespanType,
    interface: InterfaceType,
    reload: bool,
    reload_dirs: list[str],
    reload_includes: list[str],
    reload_excludes: list[str],
    reload_delay: float,
    workers: int,
    env_file: str,
    log_config: str,
    log_level: str,
    access_log: bool,
    proxy_headers: bool,
    server_header: bool,
    date_header: bool,
    forwarded_allow_ips: str,
    root_path: str,
    limit_concurrency: int,
    backlog: int,
    limit_max_requests: int,
    limit_max_requests_jitter: int,
    timeout_keep_alive: int,
    timeout_graceful_shutdown: int | None,
    timeout_worker_healthcheck: int,
    ssl_keyfile: str,
    ssl_certfile: str,
    ssl_keyfile_password: str,
    ssl_version: int,
    ssl_cert_reqs: int,
    ssl_ca_certs: str,
    ssl_ciphers: str | None,
    headers: list[str],
    use_colors: bool,
    app_dir: str,
    h11_max_incomplete_event_size: int | None,
    reset_contextvars: bool,
    factory: bool,
) -> None:
    run(
        app,
        host=host,
        port=port,
        uds=uds,
        fd=fd,
        loop=loop,
        http=http,
        ws=ws,
        ws_max_size=ws_max_size,
        ws_max_queue=ws_max_queue,
        ws_ping_interval=ws_ping_interval,
        ws_ping_timeout=ws_ping_timeout,
        ws_per_message_deflate=ws_per_message_deflate,
        lifespan=lifespan,
        env_file=env_file,
        log_config=LOGGING_CONFIG if log_config is None else log_config,
        log_level=log_level,
        access_log=access_log,
        interface=interface,
        reload=reload,
        reload_dirs=reload_dirs or None,
        reload_includes=reload_includes or None,
        reload_excludes=reload_excludes or None,
        reload_delay=reload_delay,
        workers=workers,
        proxy_headers=proxy_headers,
        server_header=server_header,
        date_header=date_header,
        forwarded_allow_ips=forwarded_allow_ips,
        root_path=root_path,
        limit_concurrency=limit_concurrency,
        backlog=backlog,
        limit_max_requests=limit_max_requests,
        limit_max_requests_jitter=limit_max_requests_jitter,
        timeout_keep_alive=timeout_keep_alive,
        timeout_graceful_shutdown=timeout_graceful_shutdown,
        timeout_worker_healthcheck=timeout_worker_healthcheck,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        ssl_keyfile_password=ssl_keyfile_password,
        ssl_version=ssl_version,
        ssl_cert_reqs=ssl_cert_reqs,
        ssl_ca_certs=ssl_ca_certs,
        ssl_ciphers=ssl_ciphers,
        headers=[header.split(":", 1) for header in headers],  # type: ignore[misc]
        use_colors=use_colors,
        factory=factory,
        app_dir=app_dir,
        h11_max_incomplete_event_size=h11_max_incomplete_event_size,
        reset_contextvars=reset_contextvars,
    )


def run(
    app: ASGIApplication | Callable[..., Any] | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    uds: str | None = None,
    fd: int | None = None,
    loop: LoopFactoryType | str = "auto",
    http: type[asyncio.Protocol] | HTTPProtocolType | str = "auto",
    ws: type[asyncio.Protocol] | WSProtocolType | str = "auto",
    ws_max_size: int = 16777216,
    ws_max_queue: int = 32,
    ws_ping_interval: float | None = 20.0,
    ws_ping_timeout: float | None = 20.0,
    ws_per_message_deflate: bool = True,
    lifespan: LifespanType = "auto",
    interface: InterfaceType = "auto",
    reload: bool = False,
    reload_dirs: list[str] | str | None = None,
    reload_includes: list[str] | str | None = None,
    reload_excludes: list[str] | str | None = None,
    reload_delay: float = 0.25,
    workers: int | None = None,
    env_file: str | os.PathLike[str] | None = None,
    log_config: dict[str, Any] | str | os.PathLike[str] | RawConfigParser | IO[Any] | None = LOGGING_CONFIG,
    log_level: str | int | None = None,
    access_log: bool = True,
    proxy_headers: bool = True,
    server_header: bool = True,
    date_header: bool = True,
    forwarded_allow_ips: list[str] | str | None = None,
    root_path: str = "",
    limit_concurrency: int | None = None,
    backlog: int = 2048,
    limit_max_requests: int | None = None,
    limit_max_requests_jitter: int = 0,
    timeout_keep_alive: int = 5,
    timeout_graceful_shutdown: int | None = None,
    timeout_worker_healthcheck: int = 5,
    ssl_keyfile: str | os.PathLike[str] | None = None,
    ssl_certfile: str | os.PathLike[str] | None = None,
    ssl_keyfile_password: str | None = None,
    ssl_version: int = SSL_PROTOCOL_VERSION,
    ssl_cert_reqs: int = ssl.CERT_NONE,
    ssl_ca_certs: str | os.PathLike[str] | None = None,
    ssl_ciphers: str | None = None,
    ssl_context_factory: Callable[[Config, Callable[[], ssl.SSLContext]], ssl.SSLContext] | None = None,
    headers: list[tuple[str, str]] | None = None,
    use_colors: bool | None = None,
    app_dir: str | None = None,
    factory: bool = False,
    h11_max_incomplete_event_size: int | None = None,
    reset_contextvars: bool = False,
) -> None:
    if app_dir is not None:
        sys.path.insert(0, app_dir)

    config = Config(
        app,
        host=host,
        port=port,
        uds=uds,
        fd=fd,
        loop=loop,
        http=http,
        ws=ws,
        ws_max_size=ws_max_size,
        ws_max_queue=ws_max_queue,
        ws_ping_interval=ws_ping_interval,
        ws_ping_timeout=ws_ping_timeout,
        ws_per_message_deflate=ws_per_message_deflate,
        lifespan=lifespan,
        interface=interface,
        reload=reload,
        reload_dirs=reload_dirs,
        reload_includes=reload_includes,
        reload_excludes=reload_excludes,
        reload_delay=reload_delay,
        workers=workers,
        env_file=env_file,
        log_config=log_config,
        log_level=log_level,
        access_log=access_log,
        proxy_headers=proxy_headers,
        server_header=server_header,
        date_header=date_header,
        forwarded_allow_ips=forwarded_allow_ips,
        root_path=root_path,
        limit_concurrency=limit_concurrency,
        backlog=backlog,
        limit_max_requests=limit_max_requests,
        limit_max_requests_jitter=limit_max_requests_jitter,
        timeout_keep_alive=timeout_keep_alive,
        timeout_graceful_shutdown=timeout_graceful_shutdown,
        timeout_worker_healthcheck=timeout_worker_healthcheck,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        ssl_keyfile_password=ssl_keyfile_password,
        ssl_version=ssl_version,
        ssl_cert_reqs=ssl_cert_reqs,
        ssl_ca_certs=ssl_ca_certs,
        ssl_ciphers=ssl_ciphers,
        ssl_context_factory=ssl_context_factory,
        headers=headers,
        use_colors=use_colors,
        factory=factory,
        h11_max_incomplete_event_size=h11_max_incomplete_event_size,
        reset_contextvars=reset_contextvars,
    )
    if config.reload or config.workers > 1:
        if not isinstance(app, str):
            logger = logging.getLogger("uvicorn.error")
            logger.warning("You must pass the application as an import string to enable 'reload' or 'workers'.")
            sys.exit(STARTUP_FAILURE)
    else:
        config.load_app()

    server = Server(config=config)

    try:
        if config.should_reload:
            sock = config.bind_socket()
            ChangeReload(config, target=server.run, sockets=[sock]).run()
        elif config.workers > 1:
            sock = config.bind_socket()
            Multiprocess(config, sockets=[sock]).run()
        else:
            server.run()
    except KeyboardInterrupt:  # pragma: full coverage
        pass
    finally:
        if config.uds and os.path.exists(config.uds):
            os.remove(config.uds)  # pragma: py-win32

    if not server.started and not config.should_reload and config.workers == 1:
        sys.exit(STARTUP_FAILURE)


def __getattr__(name: str) -> Any:
    if name == "ServerState":
        warnings.warn(
            "uvicorn.main.ServerState is deprecated, use uvicorn.server.ServerState instead.",
            DeprecationWarning,
        )
        from uvicorn.server import ServerState

        return ServerState
    raise AttributeError(f"module {__name__} has no attribute {name}")


if __name__ == "__main__":
    main()  # pragma: no cover


