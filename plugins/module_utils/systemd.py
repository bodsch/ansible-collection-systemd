#!/usr/bin/env python3
# file: systemd_client_dbus.py
"""
SystemdClient (python-dbus) mit Regex-Matching für Services/Sockets/Timer.

Install:
  sudo apt-get install python3-dbus python3-gi
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import dbus
from dbus import Interface
from dbus.exceptions import DBusException

try:
    from dbus.mainloop.glib import DBusGMainLoop  # type: ignore
    from gi.repository import GLib  # type: ignore
except Exception:  # pragma: no cover
    DBusGMainLoop = None  # type: ignore
    GLib = None  # type: ignore

SERVICE = "org.freedesktop.systemd1"
MANAGER_PATH = "/org/freedesktop/systemd1"
IFACE_MANAGER = "org.freedesktop.systemd1.Manager"
IFACE_PROPS = "org.freedesktop.DBus.Properties"
IFACE_UNIT = "org.freedesktop.systemd1.Unit"
IFACE_SERVICE = "org.freedesktop.systemd1.Service"

ENABLED_STATES = {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}
MASKED_STATES = {"masked", "masked-runtime"}

# ---------- Exceptions ----------


class SystemdError(Exception):
    """Base exception for all SystemdClient-related errors."""


class UnitNotFoundError(SystemdError):
    """Raised when a requested unit does not exist."""


class AccessDeniedError(SystemdError):
    """Raised when access is denied (PolicyKit/root permissions)."""


class JobFailedError(SystemdError):
    """Raised when a systemd job finishes with a failure state."""


class DBusIOError(SystemdError):
    """Raised for generic D-Bus or transport-level errors."""


def _map_dbus_error(e: DBusException, ctx: str = "") -> SystemdError:
    name = getattr(e, "get_dbus_name", lambda: "")() or ""
    msg = f"{ctx}: {e}" if ctx else str(e)
    if name in (
        "org.freedesktop.systemd1.NoSuchUnit",
        "org.freedesktop.DBus.Error.UnknownObject",
    ):
        return UnitNotFoundError(msg)
    if name == "org.freedesktop.DBus.Error.AccessDenied":
        return AccessDeniedError(msg)
    if name == "org.freedesktop.systemd1.JobFailed":
        return JobFailedError(msg)
    return DBusIOError(msg)


# ---------- Helpers ----------


def _py(v: Any) -> Any:
    if isinstance(v, (dbus.String, dbus.ObjectPath)):
        return str(v)
    if isinstance(
        v, (dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64)
    ):
        return int(v)
    if isinstance(v, dbus.Boolean):
        return bool(v)
    if isinstance(v, dbus.Double):
        return float(v)
    if isinstance(v, (dbus.ByteArray, bytes, bytearray)):
        return bytes(v)
    if isinstance(v, (list, tuple, dbus.Array)):
        return type(v)(_py(x) for x in v)
    if isinstance(v, (dict, dbus.Dictionary)):
        return {_py(k): _py(val) for k, val in v.items()}
    return v


def _basename_or_name(s: str) -> str:
    return os.path.basename(s) if "/" in s else s


def _kind_from_name(name: str) -> str:
    return name.split(".")[-1] if "." in name else ""


# ---------- Data ----------


@dataclass(frozen=True)
class Unit:
    name: str
    description: str
    load_state: str
    active_state: str
    sub_state: str
    followed: str
    object_path: str
    job_id: int
    job_type: str
    job_path: str


@dataclass(frozen=True)
class UnitFile:
    path: str
    state: str  # enabled, disabled, masked, ...


@dataclass(frozen=True)
class InstallChange:
    type: str
    file: str
    destination: str


@dataclass(frozen=True)
class UnitStatus:
    """Combined view of runtime unit status and install-time unit file state."""

    name: str
    kind: str  # service|socket|timer|...
    description: str
    active_state: str  # active|inactive|failed|...
    sub_state: str  # running|dead|...
    unit_file_state: Optional[str]  # enabled|disabled|masked|generated|transient|None
    load_state: Optional[str]  # loaded|not-found|...
    is_enabled: bool  # True falls "effectively enabled"
    is_masked: bool  # True falls masked/masked-runtime


# ---------- Client ----------


class SystemdClient:
    """
    """

    def __init__(self, *, user_manager: bool = False, use_glib: bool = False) -> None:
        """
        Create a new SystemdClient instance.

        Args:
            user_manager: If True, connect to the per-user systemd manager
                (session bus). If False, connect to the system-wide manager
                (system bus).
            use_glib: If True, initialize a GLib main loop and enable
                signal-based waiting for jobs. If False, a pure polling-based
                approach is used instead.
        """
        self._glib_enabled = bool(use_glib)

        if use_glib:
            if DBusGMainLoop is None:
                raise RuntimeError(
                    "GLib is not available. Install 'python3-gi' and 'python3-dbus'."
                )
            DBusGMainLoop(set_as_default=True)

        self._bus = dbus.SessionBus() if user_manager else dbus.SystemBus()
        self._mgr_obj = self._bus.get_object(SERVICE, MANAGER_PATH)
        self._manager: Interface = Interface(self._mgr_obj, IFACE_MANAGER)
        self._signals_enabled = False
        self._signal_handlers: List[Tuple[Callable, Dict[str, Any]]] = []
        self._unit_props_cache: Dict[str, Interface] = {}

    def __enter__(self) -> "SystemdClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass
        for func, kwargs in self._signal_handlers:
            try:
                self._bus.remove_signal_receiver(func, **kwargs)
            except Exception:
                pass
        self._signal_handlers.clear()
        self._unit_props_cache.clear()

    # --------- Existence / Status ---------

    def exists(self, unit: str, *, installed_ok: bool = True) -> bool:
        """
        Check whether a unit exists.

        A unit counts as existing if it is currently loaded or if a unit file
        for it exists on disk. When installed_ok is False, only a loaded unit
        counts as existing.
        """
        try:
            self._manager.GetUnit(unit)  # geladen?
            return True
        except DBusException:
            if not installed_ok:
                return False
            try:
                self._manager.GetUnitFileState(unit)  # Datei vorhanden?
                return True
            except DBusException:
                return False

    def ensure_loaded(self, unit: str) -> str:
        """
        Ensure that a unit is loaded and return its D-Bus object path.

        The method first tries GetUnit() and falls back to LoadUnit() if
        the unit is not currently loaded.
        """
        try:
            return str(self._manager.GetUnit(unit))
        except DBusException:
            try:
                return str(self._manager.LoadUnit(unit))
            except DBusException as e:
                raise _map_dbus_error(e, f"LoadUnit({unit})")

    def is_active(self, unit: str) -> bool:
        return self.active_state(unit, default="inactive") == "active"

    def active_state(self, unit: str, *, default: Optional[str] = None) -> str:
        try:
            return self._get_unit_prop_str(unit, "ActiveState")
        except UnitNotFoundError:
            if default is not None:
                return default
            raise

    def sub_state(self, unit: str, *, default: Optional[str] = None) -> str:
        try:
            return self._get_unit_prop_str(unit, "SubState")
        except UnitNotFoundError:
            if default is not None:
                return default
            raise

    def get_unit_properties(
        self, unit: str, keys: Optional[Iterable[str]] = None
    ) -> Dict[str, Any]:
        default = (
            "Id",
            "Description",
            "LoadState",
            "ActiveState",
            "SubState",
            "FragmentPath",
            "UnitFileState",
            "InactiveEnterTimestamp",
            "ActiveEnterTimestamp",
        )
        wanted = list(keys) if keys else list(default)
        props = self._props_iface_for_unit(unit)
        try:
            return {k: _py(props.Get(IFACE_UNIT, k)) for k in wanted}
        except DBusException as e:
            raise _map_dbus_error(e, f"Get({unit})")

    def get_service_properties(
        self, unit: str, keys: Optional[Iterable[str]] = None
    ) -> Dict[str, Any]:
        path = self._get_unit_path(unit)
        obj = self._bus.get_object(SERVICE, path)
        props = Interface(obj, IFACE_PROPS)
        default = ("ExecMainPID", "ExecMainStatus", "MainPID", "Type", "Restart")
        wanted = list(keys) if keys else list(default)
        out: Dict[str, Any] = {}
        for k in wanted:
            try:
                out[k] = _py(props.Get(IFACE_SERVICE, k))
            except DBusException:
                pass
        return out

    # --------- Lifecycle ---------

    def start(self, unit: str, mode: str = "replace") -> str:
        try:
            return str(self._manager.StartUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"StartUnit({unit})")

    def stop(self, unit: str, mode: str = "replace") -> str:
        try:
            return str(self._manager.StopUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"StopUnit({unit})")

    def restart(self, unit: str, mode: str = "replace") -> str:
        try:
            return str(self._manager.RestartUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"RestartUnit({unit})")

    def reload(self, unit: str, mode: str = "replace") -> str:
        try:
            return str(self._manager.ReloadUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"ReloadUnit({unit})")

    def reload_or_restart(self, unit: str, mode: str = "replace") -> str:
        try:
            return str(self._manager.ReloadOrRestartUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"ReloadOrRestartUnit({unit})")

    def reset_failed(self, unit: Optional[str] = None) -> None:
        try:
            (
                self._manager.ResetFailed()
                if unit is None
                else self._manager.ResetFailedUnit(unit)
            )
        except DBusException as e:
            raise _map_dbus_error(e, f"ResetFailed({unit or ''})")

    # NEU: Polling-Variante ohne GLib
    def wait_job_poll(
        self,
        job_path: str,
        *,
        timeout_sec: Optional[float] = None,
        raise_on_fail: bool = True,
        poll_interval: float = 0.1,
    ) -> str:
        """
        Wait for completion of a systemd job by polling its state.

        Args:
            job_path: D-Bus object path of the job.
            timeout_sec: Optional timeout in seconds. If None, wait indefinitely.
            raise_on_fail: If True, raise JobFailedError on failed or timed-out jobs.
            poll_interval: Time in seconds between poll iterations.

        Returns:
            One of "done", "failed" or "timeout-wait".

        Note:
            Without GLib signals, result details like "canceled", "dependency",
            "timeout" or "skipped" cannot be distinguished precisely.
        """
        # Job-Properties einmalig lesen (const)
        job_obj = self._bus.get_object(SERVICE, job_path)
        props = Interface(job_obj, IFACE_PROPS)
        try:
            job_type = str(props.Get("org.freedesktop.systemd1.Job", "JobType"))
            unit_name, _unit_path = props.Get(
                "org.freedesktop.systemd1.Job", "Unit"
            )  # (s,o)
            unit_name = str(unit_name)
        except DBusException as e:
            raise _map_dbus_error(e, f"JobProps({job_path})")

        # Poll bis Job weg ist
        deadline = time.monotonic() + timeout_sec if timeout_sec else None
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                if raise_on_fail:
                    raise JobFailedError(f"job {job_path} result=timeout-wait")
                return "timeout-wait"
            try:
                # Solange Property 'State' abrufbar ist, existiert der Job noch
                _ = props.Get(
                    "org.freedesktop.systemd1.Job", "State"
                )  # 'waiting'|'running'
            except DBusException as e:
                name = getattr(e, "get_dbus_name", lambda: "")() or ""
                if name in (
                    "org.freedesktop.DBus.Error.UnknownObject",
                    "org.freedesktop.systemd1.NoSuchJob",
                ):
                    break  # Job entfernt -> abgeschlossen
                raise _map_dbus_error(e, f"JobPoll({job_path})")
            time.sleep(poll_interval)

        # Ergebnis heuristisch über Unit-Status bestimmen
        try:
            st = self.active_state(unit_name, default="inactive")
        except SystemdError:
            st = "failed"

        ok = False
        if job_type == "stop":
            ok = st in ("inactive", "failed")  # nach Stop sollte nicht 'active' sein
        else:
            if st == "active":
                ok = True
            else:
                # oneshot / reload: prüfe Service-Resultat soweit möglich
                sp = self.get_service_properties(
                    unit_name, keys=("Type", "ExecMainStatus")
                )
                if str(sp.get("Type", "")) == "oneshot":
                    ok = int(sp.get("ExecMainStatus", 0)) == 0
                elif st != "failed":
                    # Fallback: kein 'failed' => als Erfolg werten
                    ok = True

        if not ok:
            if raise_on_fail:
                raise JobFailedError(f"job {job_path} result=failed")
            return "failed"

        return "done"

    # --------- Lifecycle (blocking auf Job-Resultat) ---------

    # bestehende *wait()-Methoden auf Dispatch umstellen
    def start_wait(
        self,
        unit: str,
        mode: str = "replace",
        *,
        timeout_sec: Optional[float] = None,
        raise_on_fail: bool = True,
    ) -> str:
        job = self.start(unit, mode)
        return self._wait_job_dispatch(
            job, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
        )

    def stop_wait(
        self,
        unit: str,
        mode: str = "replace",
        *,
        timeout_sec: Optional[float] = None,
        raise_on_fail: bool = True,
    ) -> str:
        job = self.stop(unit, mode)
        return self._wait_job_dispatch(
            job, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
        )

    def restart_wait(
        self,
        unit: str,
        mode: str = "replace",
        *,
        timeout_sec: Optional[float] = None,
        raise_on_fail: bool = True,
    ) -> str:
        job = self.restart(unit, mode)
        return self._wait_job_dispatch(
            job, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
        )

    def reload_wait(
        self,
        unit: str,
        mode: str = "replace",
        *,
        timeout_sec: Optional[float] = None,
        raise_on_fail: bool = True,
    ) -> str:
        job = self.reload(unit, mode)
        return self._wait_job_dispatch(
            job, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
        )

    def reload_or_restart_wait(
        self,
        unit: str,
        mode: str = "replace",
        *,
        timeout_sec: Optional[float] = None,
        raise_on_fail: bool = True,
    ) -> str:
        job = self.reload_or_restart(unit, mode)
        return self._wait_job_dispatch(
            job, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
        )

    # --------- Unit files / Listings ---------

    def enable(
        self, names: Iterable[str], *, runtime: bool = False, force: bool = True
    ) -> Tuple[bool, List[InstallChange]]:
        try:
            carries, changes = self._manager.EnableUnitFiles(
                list(names), runtime, force
            )
            return bool(carries), [InstallChange(*map(str, c)) for c in changes]
        except DBusException as e:
            raise _map_dbus_error(e, f"EnableUnitFiles({','.join(names)})")

    def disable(
        self, names: Iterable[str], *, runtime: bool = False
    ) -> List[InstallChange]:
        try:
            changes = self._manager.DisableUnitFiles(list(names), runtime)
            return [InstallChange(*map(str, c)) for c in changes]
        except DBusException as e:
            raise _map_dbus_error(e, f"DisableUnitFiles({','.join(names)})")

    def mask(
        self, names: Iterable[str], *, runtime: bool = False, force: bool = True
    ) -> List[InstallChange]:
        try:
            changes = self._manager.MaskUnitFiles(list(names), runtime, force)
            return [InstallChange(*map(str, c)) for c in changes]
        except DBusException as e:
            raise _map_dbus_error(e, f"MaskUnitFiles({','.join(names)})")

    def unmask(
        self, names: Iterable[str], *, runtime: bool = False
    ) -> List[InstallChange]:
        try:
            changes = self._manager.UnmaskUnitFiles(list(names), runtime)
            return [InstallChange(*map(str, c)) for c in changes]
        except DBusException as e:
            raise _map_dbus_error(e, f"UnmaskUnitFiles({','.join(names)})")

    def get_unit_file_state(self, file: str) -> str:
        try:
            return str(self._manager.GetUnitFileState(file))
        except DBusException as e:
            raise _map_dbus_error(e, f"GetUnitFileState({file})")

    def list_units(self) -> List[Unit]:
        try:
            rows = self._manager.ListUnits()
        except DBusException as e:
            raise _map_dbus_error(e, "ListUnits")
        out: List[Unit] = []
        for r in rows:
            out.append(
                Unit(
                    str(r[0]),
                    str(r[1]),
                    str(r[2]),
                    str(r[3]),
                    str(r[4]),
                    str(r[5]),
                    str(r[6]),
                    int(r[7]),
                    str(r[8]),
                    str(r[9]),
                )
            )
        return out

    def list_unit_files(self) -> List[UnitFile]:
        """
        List all unit files known to systemd.

        Returns:
            A list of UnitFile objects containing path and state for each unit.
        """
        try:
            rows = self._manager.ListUnitFiles()
        except DBusException as e:
            raise _map_dbus_error(e, "ListUnitFiles")

        return [UnitFile(path=str(r[0]), state=str(r[1])) for r in rows]

    def daemon_reload(self) -> None:
        try:
            self._manager.Reload()
        except DBusException as e:
            raise _map_dbus_error(e, "Reload(daemon)")

    # --------- Signals ---------

    def subscribe(self) -> None:
        try:
            self._manager.Subscribe()
            self._signals_enabled = True
        except DBusException as e:
            raise _map_dbus_error(e, "Subscribe")

    def unsubscribe(self) -> None:
        try:
            self._manager.Unsubscribe()
            self._signals_enabled = False
        except DBusException as e:
            raise _map_dbus_error(e, "Unsubscribe")

    def on_unit_properties_changed(
        self,
        unit: str,
        callback: Callable[[Dict[str, Any]], None],
        *,
        only: Iterable[str] = ("ActiveState", "SubState"),
    ) -> Callable[[], None]:
        if not self._signals_enabled:
            self.subscribe()
        path = self._get_unit_path(unit)
        wanted = set(only or ())

        def _handler(
            interface: str, changed: Dict[str, Any], invalidated: List[str]
        ) -> None:
            if interface != IFACE_UNIT:
                return
            payload = {
                k: _py(v) for k, v in changed.items() if not wanted or k in wanted
            }
            if payload:
                callback(payload)

        kwargs = dict(
            signal_name="PropertiesChanged", dbus_interface=IFACE_PROPS, path=path
        )
        self._bus.add_signal_receiver(_handler, **kwargs)
        self._signal_handlers.append((_handler, kwargs))

        def _off() -> None:
            try:
                self._bus.remove_signal_receiver(_handler, **kwargs)
            except Exception:
                pass

        return _off

    # --------- Regex-Matching über mehrere Units ---------

    def match_units(
        self,
        patterns: Iterable[str],
        *,
        types: Iterable[str] = ("service", "socket", "timer"),
        flags: int = re.IGNORECASE,
        include_inactive_files: bool = True,
    ) -> List[UnitStatus]:
        """
        Find units whose names match any of the given regular expressions.

        The result merges runtime information from ListUnits() with install-time
        information from ListUnitFiles().

        Args:
            patterns: Sequence of Python regular expressions.
            types: Iterable of unit kinds to consider (e.g. {"service", "timer"}).
            flags: Regex flags passed to re.compile().
            include_inactive_files:
                If True, include unit files that are not currently loaded.

        Returns:
            A list of UnitStatus objects, sorted by unit name.
        """
        rx = [re.compile(p, flags) for p in patterns]
        type_set = set(types)

        # Live-Units
        live = {
            u.name: u
            for u in self.list_units()
            if _kind_from_name(u.name) in type_set and any(r.search(u.name) for r in rx)
        }

        # UnitFiles (Installzustand), optional
        file_rows = self.list_unit_files() if include_inactive_files else []
        file_state_by_name: Dict[str, str] = {}
        candidates_from_files: set[str] = set()
        for f in file_rows:
            name = _basename_or_name(f.path)
            if _kind_from_name(name) in type_set and any(r.search(name) for r in rx):
                candidates_from_files.add(name)
                file_state_by_name[name] = f.state

        # Union aus Live + Files
        names = sorted(set(live.keys()) | candidates_from_files)

        out: List[UnitStatus] = []
        for name in names:
            file_state = (file_state_by_name.get(name) or "").lower() or None
            is_masked = file_state in MASKED_STATES
            is_enabled = (file_state in ENABLED_STATES) and not is_masked

            if name in live:
                u = live[name]
                out.append(
                    UnitStatus(
                        name=name,
                        kind=_kind_from_name(name),
                        description=u.description,
                        active_state=u.active_state,
                        sub_state=u.sub_state,
                        unit_file_state=file_state,
                        load_state=u.load_state,
                        is_enabled=is_enabled,
                        is_masked=is_masked,
                    )
                )
            else:
                # Datei vorhanden, aber nicht geladen
                out.append(
                    UnitStatus(
                        name=name,
                        kind=_kind_from_name(name),
                        description="",
                        active_state="inactive",
                        sub_state="dead",
                        unit_file_state=file_state,
                        load_state=None,
                        is_enabled=is_enabled,
                        is_masked=is_masked,
                    )
                )
        return out

    # --------- Low-level ---------

    def _get_unit_path(self, unit: str) -> str:
        """
        Resolve the D-Bus object path for a unit.

        The method first tries GetUnit() and falls back to LoadUnit() so that
        inactive/dead units can also be resolved.

        Raises:
            SystemdError: When the unit cannot be resolved.
        """
        try:
            return str(self._manager.GetUnit(unit))
        except DBusException as e1:
            try:
                return str(self._manager.LoadUnit(unit))
            except DBusException as e2:
                # Detailierter Fehler ausgeben
                raise _map_dbus_error(e2, f"LoadUnit({unit})") from e1

    def _props_iface_for_unit(self, unit: str) -> Interface:
        path = self._get_unit_path(unit)
        if path in self._unit_props_cache:
            return self._unit_props_cache[path]
        obj = self._bus.get_object(SERVICE, path)
        props = Interface(obj, IFACE_PROPS)
        self._unit_props_cache[path] = props
        return props

    def _get_unit_prop_str(self, unit: str, prop: str) -> str:
        props = self._props_iface_for_unit(unit)
        try:
            return str(props.Get(IFACE_UNIT, prop))
        except DBusException as e:
            raise _map_dbus_error(e, f"Get({unit},{prop})")

    # HELFER: automatische Wahl je nach GLib-Verfügbarkeit
    def _wait_job_dispatch(
        self, job_path: str, *, timeout_sec: Optional[float], raise_on_fail: bool
    ) -> str:
        if self._glib_enabled and GLib is not None:
            return self.wait_job(
                job_path, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
            )

        return self.wait_job_poll(
            job_path, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
        )


"""

first = next(iter(data), None)  # None wenn leer

# 2) direkte Dict-Comprehensions über Attribute:
by_name = {u.name: u for u in data}
states  = {u.name: (u.active_state, u.sub_state) for u in data}
enabled = {u.name: u.unit_file_state == "enabled" for u in data}

# 3) generischer Adapter für {k:v for k,v in ...}
from operator import attrgetter
from typing import Iterable, Hashable, Any

def kv(data: Iterable, key: str = "name", value: str | tuple[str, ...] = "active_state") -> Iterable[tuple[Hashable, Any]]:
    gk = attrgetter(key)
    if isinstance(value, tuple):
        gv = attrgetter(*value)                # -> tuple
        return ((gk(u), gv(u)) for u in data)
    else:
        gv = attrgetter(value)                 # -> skalar
        return ((gk(u), gv(u)) for u in data)

# Nutzung:
d1 = dict(kv(data, "name", "active_state"))                 # {name: active_state}
d2 = dict(kv(data, "name", ("active_state", "sub_state")))  # {name: (active, sub)}
d3 = dict(kv(data, "name", ("kind", "unit_file_state", "load_state")))


# ---------- CLI ----------

def _cli() -> int:
    import argparse, sys
    p = argparse.ArgumentParser(prog="systemd_client_dbus")
    p.add_argument("--user", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-units");
    sub.add_parser("list-unit-files")

    for name in ("is-active","active-state","sub-state"):
        s = sub.add_parser(name);
        s.add_argument("unit")

    for cmd in ("start","stop","restart","reload","reload-or-restart"):
        s = sub.add_parser(cmd);
        s.add_argument("unit");
        s.add_argument("--mode", default="replace")

    s = sub.add_parser("enable");
    s.add_argument("names", nargs="+");
    s.add_argument("--runtime", action="store_true");
    s.add_argument("--no-force", action="store_true")

    s = sub.add_parser("disable");
    s.add_argument("names", nargs="+");
    s.add_argument("--runtime", action="store_true")

    s = sub.add_parser("mask");
    s.add_argument("names", nargs="+");
    s.add_argument("--runtime", action="store_true");
    s.add_argument("--no-force", action="store_true")

    s = sub.add_parser("unmask"); s.add_argument("names", nargs="+");
    s.add_argument("--runtime", action="store_true")

    sub.add_parser("daemon-reload")
    s = sub.add_parser("get-unit-file-state"); s.add_argument("file")

    m = sub.add_parser("match")
    m.add_argument("patterns", nargs="+", help="Regexe, z.B. 'nginx|ssh' 'cron'")
    m.add_argument("--types", nargs="+", default=["service","socket","timer"])
    m.add_argument("--no-files", action="store_true", help="nur laufende Units betrachten")
    m.add_argument("--case-sensitive", action="store_true")

    a = p.parse_args()
    sd = SystemdClient(user_manager=a.user)
    try:
        if a.cmd == "list-units":
            for u in sd.list_units(): print(f"{u.name:40} {u.active_state:10} {u.sub_state:12} {u.description}"); return 0
        if a.cmd == "list-unit-files":
            for f in sd.list_unit_files(): print(f"{f.state:10} {f.path}"); return 0
        if a.cmd == "is-active":
            ok = sd.is_active(a.unit); print("active" if ok else "inactive"); return 0 if ok else 3
        if a.cmd == "active-state":
            try: print(sd.active_state(a.unit)); return 0
            except UnitNotFoundError:
             print("unknown"); return 4
        if a.cmd == "sub-state":
            try: print(sd.sub_state(a.unit)); return 0
            except UnitNotFoundError: print("unknown"); return 4
        if a.cmd == "start":
            print(sd.start(a.unit, a.mode)); return 0
        if a.cmd == "stop":
            print(sd.stop(a.unit, a.mode)); return 0
        if a.cmd == "restart":
            print(sd.restart(a.unit, a.mode)); return 0
        if a.cmd == "reload":
             print(sd.reload(a.unit, a.mode)); return 0
        if a.cmd == "reload-or-restart":
             print(sd.reload_or_restart(a.unit, a.mode)); return 0
        if a.cmd == "enable":
            carries, changes = sd.enable(a.names, runtime=a.runtime, force=not a.no_force)
            print(f"carries_install_info={carries}");
            [print(c) for c in changes];
            return 0
        if a.cmd == "disable":
            [print(c) for c in sd.disable(a.names, runtime=a.runtime)];
            return 0
        if a.cmd == "mask":
            [print(c) for c in sd.mask(a.names, runtime=a.runtime, force=not a.no_force)]
            return 0
        if a.cmd == "unmask":
            [print(c) for c in sd.unmask(a.names, runtime=a.runtime)];
            return 0
        if a.cmd == "daemon-reload":
            sd.daemon_reload();
            return 0
        if a.cmd == "get-unit-file-state":
            print(sd.get_unit_file_state(a.file));
            return 0
        if a.cmd == "match":
            flags = 0 if a.case_sensitive else re.IGNORECASE
            results = sd.match_units(a.patterns, types=a.types, flags=flags, include_inactive_files=not a.no_files)
            for r in results:
                print(f"
                    {r.name:40} {r.kind:7} {r.active_state:10} {r.sub_state:8}
                    {(r.unit_file_state or '-'):10} {(r.load_state or '-'):10} {r.description}"
                )
            return 0
        return 1

    except UnitNotFoundError:
        print("unknown"); return 4

    except AccessDeniedError as e:
        print(f"access-denied: {e}", file=sys.stderr); return 1

    except JobFailedError as e:
        print(f"job-failed: {e}", file=sys.stderr); return 1

    except SystemdError as e:
        print(f"error: {e}", file=sys.stderr); return 1

    finally:
        sd.close()

if __name__ == "__main__":
    raise SystemExit(_cli())

"""
