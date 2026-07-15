#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2020-2026, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

"""
Ansible module: bodsch.systemd.service_info

Locate one or more systemd units by name, glob or regex. Faster and more
targeted than ``ansible.builtin.service_facts`` because the query goes
directly through the systemd D-Bus API (no subprocess fork, no shell parsing).

Backed by the ``SystemdClient`` abstraction in
``ansible_collections.bodsch.systemd.plugins.module_utils.systemd``.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ansible.module_utils.basic import AnsibleModule

try:
    from ansible_collections.bodsch.systemd.plugins.module_utils.systemd import (
        SystemdClient,
        SystemdError,
        UnitStatus,
    )
    HAS_SYSTEMD_CLIENT = True
    SYSTEMD_CLIENT_IMPORT_ERROR: Optional[str] = None
except ImportError as exc:
    HAS_SYSTEMD_CLIENT = False
    SYSTEMD_CLIENT_IMPORT_ERROR = str(exc)

# ---------------------------------------------------------------------------------------

DOCUMENTATION = """
module: service_info
author:
  - Bodo 'bodsch' Schulz (@bodsch)

short_description: Locate systemd units by name, glob or regex via D-Bus.
version_added: 1.7.0

description:
  - Read-only lookup for systemd units matching one or more names/patterns.
  - Uses the systemd D-Bus API directly (no ``systemctl`` fork/parse).
  - Combines the runtime view (``ListUnits``) with the install-time view
    (``ListUnitFiles``) so both loaded and installed-but-inactive units are
    reported with a consistent shape.
  - Handles template units (``foo@.service``) and template instances
    (``foo@bar.service``) explicitly.

requirements:
  - python3-dbus on the managed node
  - Access to the system (or session) bus

options:
  name:
    description:
      - One or more unit names / glob patterns / regular expressions.
      - A scalar value is auto-promoted to a single-element list.
      - Patterns without a recognized unit suffix
        (C(.service), C(.socket), C(.timer), C(.mount), C(.path), C(.target),
        C(.slice), C(.scope), C(.device), C(.swap), C(.automount))
        get C(.service) appended automatically.
      - See C(use_regex) for how patterns are interpreted.
    type: list
    elements: str
    required: true
  fields:
    description:
      - Whitelist of fields to include in each service entry.
      - Defaults to a compact set (C(name), C(active_state), C(is_enabled),
        C(installed)) - enough to answer "is it there and running?".
      - Pass a list of field names to opt-in to more.
      - Pass ``["all"]`` for the full payload (equivalent to the previous
        default).
      - Unknown field names cause the task to fail.
      - C(name) is always retained regardless of this setting.
    type: list
    elements: str
    choices:
      - name
      - kind
      - description
      - active_state
      - sub_state
      - load_state
      - unit_file_state
      - is_enabled
      - is_masked
      - installed
      - loaded
      - is_template
      - is_instance
      - template_base
      - all
  use_regex:
    description:
      - When C(false) (default), each pattern is interpreted as a shell glob
        (``*``, ``?``, ``[...]``) and internally converted to an anchored,
        case-insensitive regex.
      - When C(true), each pattern is passed through unchanged and applied
        with C(re.search), so partial matches are possible.
    type: bool
    default: false
  state:
    description:
      - Post-filter on the results.
      - C(any) returns everything that matched.
      - C(loaded) keeps units currently loaded by systemd.
      - C(active) keeps units whose active state is C(active).
      - C(enabled) keeps units whose unit file state is
        C(enabled)/C(enabled-runtime)/C(alias) and not masked.
    type: str
    choices: [any, loaded, active, enabled]
    default: any
  first_match:
    description:
      - When true, restrict C(services) to the alphabetically first matching
        unit. C(service) always holds the first match regardless of this flag.
    type: bool
    default: false
  must_exist:
    description:
      - Fail the task if no unit matches any of the patterns after filtering.
    type: bool
    default: false
  include_templates:
    description:
      - Include template units (``foo@.service``) in the results.
    type: bool
    default: true
  include_instances:
    description:
      - Include template instances (``foo@bar.service``) in the results.
    type: bool
    default: true
  scope:
    description:
      - Which systemd instance to query.
    type: str
    choices: [system, user]
    default: system
"""

EXAMPLES = """
- name: locate PHP-FPM regardless of distro / version
  bodsch.systemd.service_info:
    name:
      - php-fpm
      - php*-fpm
      - php-fpm-legacy
    first_match: true
  register: php_fpm

- name: restart whichever PHP-FPM was found
  ansible.builtin.systemd:
    name: "{{ php_fpm.service.name }}"
    state: restarted
  when: php_fpm.found

- name: enforce that syslog-ng (template or non-template) is installed
  bodsch.systemd.service_info:
    name:
      - syslog-ng
      - syslog-ng@
    must_exist: true

- name: query only currently active backup timers
  bodsch.systemd.service_info:
    name: "backup-*.timer"
    state: active

- name: advanced regex query
  bodsch.systemd.service_info:
    name: "^(nginx|caddy|apache2)\\\\.service$"
    use_regex: true
"""

RETURN = """
# changed:
  description: Always ``false`` (read-only module).
  type: bool
  returned: always
found:
  description: True if at least one unit matched after filtering.
  type: bool
  returned: always
count:
  description: Number of matching units after filtering.
  type: int
  returned: always
patterns_used:
  description: Normalized patterns actually queried (after auto-suffix).
  type: list
  elements: str
  returned: always
types_queried:
  description: Unit type suffixes derived from the patterns (e.g. ``["service"]``).
  type: list
  elements: str
  returned: always
fields_returned:
  description: Actual field whitelist applied to each service entry.
  type: list
  elements: str
  returned: always
service:
  description:
    - Convenience shortcut. Holds the first matching entry, or null.
    - Identical to ``services[0]`` when there is at least one match.
  type: dict
  returned: always
services:
  description: List of matching units.
  type: list
  elements: dict
  returned: always
  contains:
    name:
      description: Full unit name including the extension.
      type: str
    kind:
      description: Unit type suffix (``service``, ``socket``, ``timer``, ...).
      type: str
    description:
      description: Human-readable description (empty for units not loaded).
      type: str
    active_state:
      description: ``active`` / ``inactive`` / ``failed`` / ...
      type: str
    sub_state:
      description: Unit-type specific sub-state (``running``, ``dead``, ...).
      type: str
    load_state:
      description: ``loaded`` / ``not-found`` / ``masked`` / ``error`` or null.
      type: str
    unit_file_state:
      description: ``enabled`` / ``disabled`` / ``static`` / ``masked`` / ... or null.
      type: str
    is_enabled:
      description: True if effectively enabled (and not masked).
      type: bool
    is_masked:
      description: True if masked.
      type: bool
    installed:
      description: True if a unit file exists on disk.
      type: bool
    loaded:
      description: True if currently loaded by systemd.
      type: bool
    is_template:
      description: True for template unit files (``foo@.service``).
      type: bool
    is_instance:
      description: True for template instances (``foo@bar.service``).
      type: bool
    template_base:
      description: For templates/instances, the part before ``@``; otherwise null.
      type: str
"""

# ---------------------------------------------------------------------------------------

_UNIT_SUFFIXES: Tuple[str, ...] = (
    "service", "socket", "timer", "mount", "automount",
    "swap", "target", "path", "device", "scope", "slice",
)


class ServiceInfo:
    """
    Locate systemd units matching one or more patterns.

    Optimized read-only wrapper around ``SystemdClient``. When the caller
    provides a single exact name (no wildcards, no regex), a direct D-Bus
    lookup is used and the more expensive ``ListUnits``/``ListUnitFiles``
    pair is skipped entirely. Callers may also restrict the returned
    fields via the ``fields`` parameter to keep the payload small.
    """

    _GLOB_CHARS: Tuple[str, ...] = ("*", "?", "[")

    # Superset of everything a match result can expose. Kept in sync with
    # :meth:`_serialize` and the module's RETURN documentation.
    ALL_FIELDS: Tuple[str, ...] = (
        "name", "kind", "description",
        "active_state", "sub_state",
        "load_state", "unit_file_state",
        "is_enabled", "is_masked",
        "installed", "loaded",
        "is_template", "is_instance", "template_base",
    )

    # Sensible defaults: enough to answer "does it exist and is it running".
    DEFAULT_FIELDS: Tuple[str, ...] = (
        "name", "active_state", "is_enabled", "installed",
    )

    def __init__(self, module: AnsibleModule) -> None:
        """
        :param module: The active AnsibleModule instance.
        """
        self.module: AnsibleModule = module

        self.raw_names: List[str] = list(module.params["name"] or [])
        self.use_regex: bool = bool(module.params["use_regex"])
        self.state_filter: str = module.params["state"]
        self.first_match: bool = bool(module.params["first_match"])
        self.must_exist: bool = bool(module.params["must_exist"])
        self.include_templates: bool = bool(module.params["include_templates"])
        self.include_instances: bool = bool(module.params["include_instances"])
        self.scope: str = module.params["scope"]
        self.fields: Tuple[str, ...] = self._resolve_fields(
            module.params.get("fields")
        )

        self.patterns: List[str] = self._normalize_patterns(self.raw_names)
        self.types: Set[str] = self._derive_types(self.patterns)
        self.regexes: List[str] = self._to_regexes(self.patterns, self.use_regex)

    # -- public API ----------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """
        Execute the query and assemble the result dict.

        :returns: Result dict suitable for ``module.exit_json``.
        """
        if not self.patterns:
            self.module.fail_json(msg="'name' must contain at least one pattern")

        try:
            with SystemdClient(user_manager=(self.scope == "user")) as client:
                if self._can_use_fast_path():
                    services = self._fast_path(client, self.patterns[0])
                else:
                    services = self._match_path(client)
        except SystemdError as exc:
            self.module.fail_json(
                msg=f"Cannot query systemd via D-Bus: {exc}",
                patterns_used=self.patterns,
            )
        except Exception as exc:  # noqa: BLE001 - defensive
            self.module.fail_json(
                msg=f"Unexpected error querying systemd: {exc}",
                patterns_used=self.patterns,
            )

        if not self.include_templates:
            services = [s for s in services if s.get("is_template") is not True]
        if not self.include_instances:
            services = [s for s in services if s.get("is_instance") is not True]

        services = self._apply_state_filter(services)
        services.sort(key=lambda s: s.get("name", ""))
        services = [self._project_fields(s) for s in services]

        count: int = len(services)
        found: bool = count > 0

        if self.must_exist and not found:
            self.module.fail_json(
                msg=(
                    "No unit matched any of the patterns: "
                    f"{', '.join(self.patterns)}"
                ),
                found=False,
                count=0,
                patterns_used=self.patterns,
                types_queried=sorted(self.types),
                fields_returned=list(self.fields),
                service=None,
                services=[],
                changed=False,
            )

        first: Optional[Dict[str, Any]] = services[0] if services else None
        reported: List[Dict[str, Any]] = (
            [first] if (self.first_match and first) else services
        )

        return dict(
            changed=False,
            found=found,
            count=count,
            patterns_used=self.patterns,
            types_queried=sorted(self.types),
            fields_returned=list(self.fields),
            service=first,
            services=reported,
        )

    # -- fast path (single exact name) ---------------------------------------------------

    def _can_use_fast_path(self) -> bool:
        """
        Decide whether the direct-lookup path applies.

        Requires exactly one pattern, no regex mode and no glob metacharacters.

        :returns: True if the fast path is safe to use.
        """
        if self.use_regex:
            return False
        if len(self.patterns) != 1:
            return False
        pattern = self.patterns[0]
        return not any(ch in pattern for ch in self._GLOB_CHARS)

    def _fast_path(
        self,
        client: "SystemdClient",
        name: str,
    ) -> List[Dict[str, Any]]:
        """
        Resolve a single exact unit name with the cheapest possible calls.

        Only the fields actually requested are populated so we can skip any
        D-Bus call that would only feed unused data. ``installed`` alone
        needs a single ``GetUnitFileState``; ``active_state``/``sub_state``
        additionally require ``GetUnit`` + a property fetch.

        :param client: The connected SystemdClient.
        :param name: Exact unit name.
        :returns: One-element list (empty when nothing was found).
        """
        needs_runtime: bool = bool(
            {"active_state", "sub_state", "load_state", "description", "loaded"}
            & set(self.fields)
        )
        needs_file: bool = bool(
            {"unit_file_state", "is_enabled", "is_masked", "installed"}
            & set(self.fields)
        )

        # Cheapest existence check first: does a unit file exist?
        file_state: Optional[str] = None
        installed: bool = False
        if needs_file:
            try:
                file_state = client._manager.GetUnitFileState(name)
                file_state = str(file_state) if file_state is not None else None
                installed = True
            except Exception:  # noqa: BLE001 - covers DBusException + subclasses
                installed = False

        # If we never needed runtime info and the file doesn't exist, we're done.
        if not needs_runtime and not installed:
            return []

        active_state: Optional[str] = None
        sub_state: Optional[str] = None
        load_state: Optional[str] = None
        description: str = ""
        loaded: bool = False

        if needs_runtime:
            try:
                props = client.get_unit_properties(
                    name,
                    keys=("ActiveState", "SubState", "LoadState", "Description"),
                )
                active_state = props.get("ActiveState")
                sub_state = props.get("SubState")
                load_state = props.get("LoadState")
                description = props.get("Description") or ""
                loaded = load_state == "loaded"
            except SystemdError:
                # Not loaded and no unit file either - genuinely not there.
                if not installed:
                    return []

        is_masked: bool = (file_state or "").lower() in {"masked", "masked-runtime"}
        is_enabled: bool = (
            (file_state or "").lower()
            in {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}
            and not is_masked
        )

        entry: Dict[str, Any] = self._build_entry(
            name=name,
            active_state=active_state,
            sub_state=sub_state,
            load_state=load_state,
            unit_file_state=file_state,
            description=description,
            installed=installed,
            loaded=loaded,
            is_enabled=is_enabled,
            is_masked=is_masked,
        )
        return [entry]

    # -- match path (patterns / globs / regex) -------------------------------------------

    def _match_path(self, client: "SystemdClient") -> List[Dict[str, Any]]:
        """
        Full match path using ``SystemdClient.match_units``.

        :param client: The connected SystemdClient.
        :returns: List of serialized match entries.
        """
        matches: List[UnitStatus] = client.match_units(
            patterns=self.regexes,
            types=self.types or set(_UNIT_SUFFIXES),
            flags=0 if self.use_regex else re.IGNORECASE,
            include_inactive_files=True,
        )
        return [self._serialize(u) for u in matches]

    # -- serialization / classification -------------------------------------------------

    def _serialize(self, unit: "UnitStatus") -> Dict[str, Any]:
        """
        Turn a :class:`UnitStatus` dataclass into a plain, fully-populated dict.

        Field projection happens later in :meth:`_project_fields`; keeping
        the intermediate representation complete keeps filtering code simple.

        :param unit: A UnitStatus record from ``SystemdClient.match_units``.
        :returns: Dict with all fields defined by :attr:`ALL_FIELDS`.
        """
        return self._build_entry(
            name=unit.name,
            active_state=unit.active_state,
            sub_state=unit.sub_state,
            load_state=unit.load_state,
            unit_file_state=unit.unit_file_state,
            description=unit.description or "",
            installed=unit.unit_file_state is not None,
            loaded=unit.load_state == "loaded",
            is_enabled=bool(unit.is_enabled),
            is_masked=bool(unit.is_masked),
        )

    @classmethod
    def _build_entry(
        cls,
        *,
        name: str,
        active_state: Optional[str],
        sub_state: Optional[str],
        load_state: Optional[str],
        unit_file_state: Optional[str],
        description: str,
        installed: bool,
        loaded: bool,
        is_enabled: bool,
        is_masked: bool,
    ) -> Dict[str, Any]:
        """
        Assemble a full entry dict (all fields present) from raw inputs.

        :returns: Dict shaped according to :attr:`ALL_FIELDS`.
        """
        is_template, is_instance, template_base = cls._classify(name)
        kind = name.rsplit(".", 1)[-1] if "." in name else ""
        return dict(
            name=name,
            kind=kind,
            description=description or "",
            active_state=active_state,
            sub_state=sub_state,
            load_state=load_state,
            unit_file_state=unit_file_state,
            is_enabled=is_enabled,
            is_masked=is_masked,
            installed=installed,
            loaded=loaded,
            is_template=is_template,
            is_instance=is_instance,
            template_base=template_base,
        )

    @staticmethod
    def _classify(name: str) -> Tuple[bool, bool, Optional[str]]:
        """
        Classify a unit name w.r.t. template semantics.

        :param name: Full unit name including the extension.
        :returns: Tuple ``(is_template, is_instance, template_base)``.
        """
        base = name.rsplit(".", 1)[0] if "." in name else name
        if "@" not in base:
            return False, False, None
        head, _at, tail = base.partition("@")
        if tail == "":
            return True, False, head or None
        return False, True, head or None

    # -- field projection ----------------------------------------------------------------

    @classmethod
    def _resolve_fields(cls, requested: Optional[List[str]]) -> Tuple[str, ...]:
        """
        Turn the ``fields`` parameter into a validated tuple.

        Special value ``"all"`` expands to :attr:`ALL_FIELDS`. Unknown field
        names raise via ``AnsibleModule.fail_json``.

        :param requested: Raw list from module params (may be None).
        :returns: Ordered, de-duplicated tuple of field names.
        """
        if not requested:
            return cls.DEFAULT_FIELDS

        # Sentinel: user passes ["all"] to opt into the full payload.
        if len(requested) == 1 and requested[0] == "all":
            return cls.ALL_FIELDS

        allowed: Set[str] = set(cls.ALL_FIELDS)
        seen: Set[str] = set()
        out: List[str] = []
        unknown: List[str] = []

        # ``name`` is always retained so results are addressable.
        out.append("name")
        seen.add("name")

        for field in requested:
            if field == "name":
                continue
            if field not in allowed:
                unknown.append(field)
                continue
            if field not in seen:
                out.append(field)
                seen.add(field)

        if unknown:
            raise ValueError(
                f"Unknown field(s) in 'fields': {', '.join(sorted(unknown))}. "
                f"Allowed: {', '.join(cls.ALL_FIELDS)} or 'all'."
            )

        return tuple(out)

    def _project_fields(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Reduce a full entry dict to the configured field whitelist.

        :param entry: Full entry produced by :meth:`_build_entry`.
        :returns: Dict containing only the requested fields.
        """
        return {k: entry.get(k) for k in self.fields}

    # -- pattern handling ---------------------------------------------------------------

    @staticmethod
    def _normalize_patterns(names: List[str]) -> List[str]:
        """
        Auto-append ``.service`` to patterns that lack a known unit suffix.

        :param names: Raw pattern list from the caller.
        :returns: Normalized pattern list.
        """
        out: List[str] = []
        seen: Set[str] = set()
        for raw in names:
            if not isinstance(raw, str):
                continue
            candidate = raw.strip()
            if not candidate:
                continue
            if not ServiceInfo._has_known_suffix(candidate):
                candidate = f"{candidate}.service"
            if candidate not in seen:
                out.append(candidate)
                seen.add(candidate)
        return out

    @staticmethod
    def _has_known_suffix(pattern: str) -> bool:
        """
        Return True if ``pattern`` ends in a known systemd unit suffix.

        :param pattern: Raw pattern string.
        :returns: True if the pattern ends in a supported unit type.
        """
        for suffix in _UNIT_SUFFIXES:
            if pattern.endswith(f".{suffix}"):
                return True
        return False

    @staticmethod
    def _derive_types(patterns: List[str]) -> Set[str]:
        """
        Extract unit type suffixes from normalized patterns.

        :param patterns: Normalized patterns (with suffix guaranteed).
        :returns: Set of type strings without leading dot.
        """
        found: Set[str] = set()
        for pattern in patterns:
            for suffix in _UNIT_SUFFIXES:
                if pattern.endswith(f".{suffix}"):
                    found.add(suffix)
                    break
        return found

    @staticmethod
    def _to_regexes(patterns: List[str], use_regex: bool) -> List[str]:
        """
        Convert normalized patterns to regex strings.

        :param patterns: Normalized patterns.
        :param use_regex: If True, patterns are treated as regex verbatim.
        :returns: List of regex strings.
        """
        if use_regex:
            return list(patterns)
        return [r"\A" + fnmatch.translate(p) for p in patterns]

    # -- filtering ----------------------------------------------------------------------

    def _apply_state_filter(
        self,
        services: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Post-filter the merged list based on ``state``.

        :param services: Full entry dicts.
        :returns: Filtered list.
        """
        if self.state_filter == "any":
            return services
        if self.state_filter == "loaded":
            return [s for s in services if s.get("loaded")]
        if self.state_filter == "active":
            return [s for s in services if s.get("active_state") == "active"]
        if self.state_filter == "enabled":
            return [
                s for s in services
                if s.get("is_enabled") and not s.get("is_masked")
            ]
        return services

# ---------------------------------------------------------------------------------------


def main() -> None:
    """
    Module entry point. Wires up the argument spec and delegates to
    :class:`ServiceInfo`.
    """
    argument_spec: Dict[str, Any] = dict(
        name=dict(required=True, type="list", elements="str"),
        use_regex=dict(required=False, type="bool", default=False),
        state=dict(
            required=False, type="str", default="any",
            choices=["any", "loaded", "active", "enabled"],
        ),
        first_match=dict(required=False, type="bool", default=False),
        must_exist=dict(required=False, type="bool", default=False),
        include_templates=dict(required=False, type="bool", default=True),
        include_instances=dict(required=False, type="bool", default=True),
        scope=dict(
            required=False, type="str", default="system",
            choices=["system", "user"],
        ),
        fields=dict(
            required=False,
            type="list",
            elements="str",
            default=None,
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    if not HAS_SYSTEMD_CLIENT:
        module.fail_json(
            msg=(
                "The 'SystemdClient' module_utils could not be imported. "
                "Install 'python3-dbus' on the managed node. "
                f"Original error: {SYSTEMD_CLIENT_IMPORT_ERROR}"
            )
        )

    try:
        worker = ServiceInfo(module)
    except ValueError as exc:
        module.fail_json(msg=str(exc))

    result = worker.run()
    module.exit_json(**result)


# import module snippets
if __name__ == "__main__":
    main()
