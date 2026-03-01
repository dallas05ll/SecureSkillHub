"""
Inter-agent output sanitizer.

Runs BETWEEN agent outputs to validate, trim, and strip injection
patterns from all structured data flowing through the pipeline.
This is a critical security boundary — every agent output passes through
the Sanitizer before being consumed by the next agent.
"""

from __future__ import annotations

import logging
import re
import types
from typing import Any, TypeVar, Union

from pydantic import BaseModel, ValidationError

from src.sanitizer.schemas import (
    AgentAOutput,
    AgentBOutput,
    ScannerOutput,
    ScorerOutput,
    SupervisorOutput,
)
from src.scanner.regex_patterns import INJECTION_PATTERNS, PatternEntry

logger = logging.getLogger(__name__)

# Type variable for generic sanitize() signature
T = TypeVar("T", bound=BaseModel)

# All agent output types that the sanitizer knows how to handle
AgentOutput = Union[
    AgentAOutput,
    AgentBOutput,
    ScannerOutput,
    ScorerOutput,
    SupervisorOutput,
]

# Pre-compile a single combined injection regex for fast stripping
_INJECTION_COMBINED: re.Pattern[str] = re.compile(
    "|".join(f"(?:{entry.pattern.pattern})" for entry in INJECTION_PATTERNS),
    re.IGNORECASE,
)


class SanitizationError(Exception):
    """Raised when a model instance fails validation and cannot be repaired."""


class Sanitizer:
    """
    Validates and sanitizes agent output models.

    Operations performed:
    1. Re-parse (validate) the model via Pydantic
    2. Trim all string fields to their declared max_length
    3. Strip injection patterns from all string fields
    4. Sanitize enum fields to contain only valid values

    Usage:
        sanitizer = Sanitizer()
        clean_output = sanitizer.sanitize(agent_a_output)
    """

    def __init__(self, *, strict: bool = True) -> None:
        """
        Args:
            strict: If True, raise SanitizationError on validation failure.
                    If False, attempt best-effort repair before raising.
        """
        self._strict = strict

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sanitize(self, model_instance: T) -> T:
        """
        Validate and sanitize a Pydantic model instance.

        Args:
            model_instance: Any Pydantic BaseModel instance (typically an
                            agent output schema).

        Returns:
            A new, sanitized model instance of the same type.

        Raises:
            SanitizationError: If validation fails and repair is not possible.
            TypeError: If the input is not a Pydantic BaseModel.
        """
        if not isinstance(model_instance, BaseModel):
            raise TypeError(
                f"Expected a Pydantic BaseModel instance, got {type(model_instance).__name__}"
            )

        model_class = type(model_instance)

        # Step 1: Export to dict for manipulation
        raw_data = model_instance.model_dump()

        # Step 2: Recursively sanitize all fields
        sanitized_data = self._sanitize_dict(raw_data, model_class)

        # Step 3: Re-validate by constructing a new model instance
        try:
            return model_class.model_validate(sanitized_data)
        except ValidationError as exc:
            msg = f"Sanitized data failed re-validation for {model_class.__name__}: {exc}"
            logger.error(msg)
            if self._strict:
                raise SanitizationError(msg) from exc
            # Best-effort: return the original (it already passed initial validation)
            logger.warning("Returning original model instance due to re-validation failure")
            return model_instance

    def sanitize_raw(self, data: dict[str, Any], model_class: type[T]) -> T:
        """
        Sanitize raw dict data and validate against a model class.

        Useful when receiving data from external sources (JSON payloads)
        that haven't been parsed into a model yet.

        Args:
            data: Raw dictionary of field values.
            model_class: The Pydantic model class to validate against.

        Returns:
            A validated and sanitized model instance.
        """
        sanitized_data = self._sanitize_dict(data, model_class)
        try:
            return model_class.model_validate(sanitized_data)
        except ValidationError as exc:
            raise SanitizationError(
                f"Raw data failed validation for {model_class.__name__}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Internal recursive sanitizer
    # ------------------------------------------------------------------

    def _sanitize_dict(
        self, data: dict[str, Any], model_class: type[BaseModel]
    ) -> dict[str, Any]:
        """Recursively sanitize all fields in a data dict based on the model schema."""
        result: dict[str, Any] = {}
        schema = model_class.model_fields

        for field_name, value in data.items():
            field_info = schema.get(field_name)
            if field_info is None:
                # Unknown field — drop it silently (prevents injection via extra fields)
                logger.debug("Dropping unknown field: %s", field_name)
                continue

            result[field_name] = self._sanitize_value(value, field_info, field_name)

        return result

    def _sanitize_value(self, value: Any, field_info: Any, field_name: str) -> Any:
        """Sanitize a single field value based on its type and constraints."""
        if value is None:
            return None

        # Handle lists recursively
        if isinstance(value, list):
            return [self._sanitize_list_item(item, field_info, field_name) for item in value]

        # Handle nested dicts (sub-models or plain dicts)
        if isinstance(value, dict):
            return self._sanitize_nested_dict(value, field_info, field_name)

        # Handle strings — the primary target for injection and overflow
        if isinstance(value, str):
            return self._sanitize_string(value, field_info)

        # Handle enums represented as strings
        # (Pydantic str Enums serialize to their string values)

        # Numeric and boolean values pass through
        return value

    def _sanitize_list_item(self, item: Any, field_info: Any, field_name: str) -> Any:
        """Sanitize a single item within a list field."""
        if isinstance(item, str):
            # List[str] fields — apply string sanitization with a reasonable default max
            max_len = self._get_max_length(field_info)
            if max_len is None:
                max_len = 500  # Sensible default for list string items
            return self._strip_and_trim(item, max_len)

        if isinstance(item, dict):
            # Try to resolve the nested model class for proper field-level sanitization
            nested_class = self._resolve_nested_model(field_info)
            if nested_class is not None:
                return self._sanitize_dict(item, nested_class)
            # Fallback: sanitize all string values in the dict
            return {
                k: self._strip_and_trim(v, 500) if isinstance(v, str) else v
                for k, v in item.items()
            }

        return item

    def _sanitize_nested_dict(
        self, value: dict, field_info: Any, field_name: str
    ) -> dict:
        """Sanitize a nested dict, resolving its model class if possible."""
        nested_class = self._resolve_nested_model(field_info)
        if nested_class is not None:
            return self._sanitize_dict(value, nested_class)

        # Plain dict field (e.g., dict[str, int]) — sanitize string keys/values
        result = {}
        for k, v in value.items():
            clean_key = self._strip_and_trim(k, 200) if isinstance(k, str) else k
            clean_val = self._strip_and_trim(v, 500) if isinstance(v, str) else v
            result[clean_key] = clean_val
        return result

    def _sanitize_string(self, value: str, field_info: Any) -> str:
        """Sanitize a string field: trim to max_length and strip injections."""
        max_len = self._get_max_length(field_info)
        return self._strip_and_trim(value, max_len)

    # ------------------------------------------------------------------
    # Core string operations
    # ------------------------------------------------------------------

    def _strip_and_trim(self, value: str, max_length: int | None) -> str:
        """
        Strip injection patterns and trim a string to max_length.

        Order matters:
        1. Strip injection patterns first (may shorten the string)
        2. Trim to max_length after stripping
        """
        # Strip injection patterns
        cleaned = self._strip_injections(value)

        # Trim to max_length
        if max_length is not None and len(cleaned) > max_length:
            cleaned = cleaned[:max_length]

        return cleaned

    @staticmethod
    def _strip_injections(value: str) -> str:
        """
        Remove injection patterns from a string.

        Replaces matched injection patterns with '[STRIPPED]' to make
        tampering visible in downstream processing.
        """
        if not value:
            return value

        return _INJECTION_COMBINED.sub("[STRIPPED]", value)

    # ------------------------------------------------------------------
    # Schema introspection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_max_length(field_info: Any) -> int | None:
        """Extract max_length from a Pydantic field's metadata."""
        # Pydantic v2 stores constraints in metadata
        if hasattr(field_info, "metadata"):
            for meta in field_info.metadata:
                if hasattr(meta, "max_length") and meta.max_length is not None:
                    return meta.max_length

        # Fallback: check json_schema_extra or direct attribute
        if hasattr(field_info, "max_length"):
            return field_info.max_length

        return None

    @staticmethod
    def _resolve_nested_model(field_info: Any) -> type[BaseModel] | None:
        """
        Attempt to resolve the Pydantic model class for a nested field.

        Works for fields typed as SubModel, list[SubModel], Optional[SubModel].
        """
        annotation = field_info.annotation
        if annotation is None:
            return None

        # Direct model class
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation

        # Generic types: list[SubModel], Optional[SubModel], etc.
        origin = getattr(annotation, "__origin__", None)
        args = getattr(annotation, "__args__", ())

        if origin is list and args:
            inner = args[0]
            if isinstance(inner, type) and issubclass(inner, BaseModel):
                return inner

        # Optional[SubModel] = Union[SubModel, None]
        if origin is Union or isinstance(annotation, types.UnionType):
            for arg in args:
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    return arg

        return None


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

# Pre-instantiated sanitizer for simple usage
_default_sanitizer = Sanitizer(strict=True)


def sanitize(model_instance: T) -> T:
    """Module-level convenience function for sanitizing agent outputs."""
    return _default_sanitizer.sanitize(model_instance)


def sanitize_raw(data: dict[str, Any], model_class: type[T]) -> T:
    """Module-level convenience function for sanitizing raw dict data."""
    return _default_sanitizer.sanitize_raw(data, model_class)
