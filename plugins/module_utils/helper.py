from typing import Any, List, Optional

from ansible_collections.bodsch.systemd.plugins.module_utils.static import (
    VALID_WEEKDAY_TOKENS,
    WEEKDAY_ALIASES,
)


def snake_to_systemd(key: str) -> str:
    """
    Convert a snake_case or mixed-style key into a systemd option name.

    Examples:
        "randomized_delay_sec" -> "RandomizedDelaySec"
        "WantedBy"             -> "WantedBy" (unchanged)

    Keys that are already written in CamelCase / systemd style are returned as-is.
    Falsy input is returned unchanged.
    """
    if not key:
        return key

    # already CamelCase/systemd-style: leave untouched
    if "_" not in key and any(c.isupper() for c in key[1:]):
        return key

    parts = str(key).split("_")

    return "".join(p.capitalize() for p in parts if p)


def bool_to_systemd(value: Any) -> str:
    """
    Normalize a Python boolean to a systemd boolean string.

    Args:
        value: Boolean value or any other type.

    Returns:
        "true" or "false" if value is a bool, otherwise str(value).
    """
    if isinstance(value, bool):
        return "true" if value else "false"

    return str(value)


def normalize_list_or_scalar(
    value: Any, default: Optional[str] = None
) -> Optional[str]:
    """
    Normalize a scalar or iterable value into a comma-separated string.

    Args:
        value: None, a scalar or an iterable (list/tuple/set) of scalars.
        default: Value to return if the input is None.

    Returns:
        default if value is None, otherwise a string representation:
        - iterables are joined with commas
        - scalars are converted via str(value)
    """
    if value is None:
        return default

    if isinstance(value, (list, tuple, set)):
        return ",".join(str(v) for v in value)

    return str(value)


def timer_component(
    value: Any,
    default: str = "*",
    pad_width: Optional[int] = None,
) -> str:
    """
    Convert a single calendar component (year, month, day, hour, minute, second)
    to a systemd-compatible string.

    Supports:
      * None  -> default (usually "*")
      * str   -> returned unchanged (e.g. "*/15")
      * int   -> optionally zero-padded according to pad_width
      * list/tuple/set -> each element is converted individually and combined
                          as a comma-separated string

    Args:
        value: Component value or iterable of component values.
        default: Fallback value when value is None.
        pad_width: Optional zero-padding width for integer values.

    Returns:
        A normalized string representation usable in OnCalendar expressions.
    """
    if value is None:
        return default

    # already a complex expression like "*/15" etc.
    if isinstance(value, str):
        return value

    if isinstance(value, (list, tuple, set)):
        # treat each element individually, keep inner strings untouched
        parts: List[str] = []
        for v in value:
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, int):
                if pad_width:
                    parts.append(f"{v:0{pad_width}d}")
                else:
                    parts.append(str(v))
            else:
                parts.append(str(v))

        return ",".join(parts)

    if isinstance(value, int):
        if pad_width:
            return f"{value:0{pad_width}d}"

        return str(value)

    # fallback
    return str(value)


def normalize_weekday_token(token: str, module: Any = None) -> str:
    """
    Normalize a weekday token for use in systemd calendar expressions.

    Accepted forms:
      * official tokens: "Mon" .. "Sun"
      * digits: "0" .. "7" (systemd accepts 0/7 = Sunday)
      * configured aliases (for example "monday" -> "Mon")

    On invalid input, either module.fail_json is called (if provided) or
    a ValueError is raised.

    Args:
        token: Weekday token as provided by the caller.
        module: Optional AnsibleModule-like object used to report errors via
                module.fail_json(msg=..., value=token).

    Returns:
        A normalized weekday token suitable for systemd (e.g. "Mon", "Tue").

    Raises:
        ValueError: If the token cannot be normalized to a valid weekday.
    """
    raw = str(token).strip()
    if not raw:
        msg = "weekday token must not be empty"
        if module is not None and hasattr(module, "fail_json"):
            module.fail_json(msg=msg, value=token)
        raise ValueError(msg)

    # numeric weekday (systemd: 1..7, 0/7 = Sunday)
    if raw.isdigit():
        n = int(raw)
        if 0 <= n <= 7:
            return raw
        msg = f"invalid numeric weekday '{raw}', expected 0..7"
        if module is not None and hasattr(module, "fail_json"):
            module.fail_json(msg=msg, value=token)
        raise ValueError(msg)

    # official token directly allowed
    if raw in VALID_WEEKDAY_TOKENS:
        return raw

    # alias mapping (case-insensitive)
    lower = raw.lower()
    if lower in WEEKDAY_ALIASES:
        return WEEKDAY_ALIASES[lower]

    msg = (
        f"unsupported weekday value '{raw}', "
        f"expected one of {sorted(VALID_WEEKDAY_TOKENS)} or 1..7"
    )
    if module is not None and hasattr(module, "fail_json"):
        module.fail_json(msg=msg, value=token)

    raise ValueError(msg)
