#!/usr/bin/env python3

# file: systemd.py
"""
High-level systemd D-Bus client with regex matching for services, sockets and
timers.

The module is primarily intended to be imported from Ansible modules or other
Python code, but it also exposes a small CLI for ad-hoc use.

Dependencies (Debian/Ubuntu):
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
    """Base exception type for all SystemdClient-related errors."""


class UnitNotFoundError(SystemdError):
    """Raised when a requested unit or unit file is not known to systemd."""


class AccessDeniedError(SystemdError):
    """Raised when access is denied (e.g. PolicyKit / missing root privileges)."""


class JobFailedError(SystemdError):
    """Raised when a systemd job finishes or is reported with a failure state."""


class DBusIOError(SystemdError):
    """Raised for generic D-Bus or transport-level errors."""


def _map_dbus_error(e: DBusException, ctx: str = "") -> SystemdError:
    """
    Map a raw DBusException to a more specific SystemdError subclass.

    Args:
        e: Original DBusException instance.
        ctx: Optional context string to prefix the error message with.

    Returns:
        One of UnitNotFoundError, AccessDeniedError, JobFailedError or DBusIOError.
    """
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
    """
    Convert dbus.* types into plain Python types (recursively).

    This makes it easier to work with values returned from D-Bus calls by
    normalising strings, integers, arrays and dictionaries.
    """
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
    """
    Return the basename of a path or the input string if it contains no slash.
    """
    return os.path.basename(s) if "/" in s else s


def _kind_from_name(name: str) -> str:
    """
    Extract the unit type (suffix) from a unit name, e.g. 'ssh.service' -> 'service'.
    """
    return name.split(".")[-1] if "." in name else ""


# ---------- Data ----------


@dataclass(frozen=True)
class Unit:
    """Single row returned from Manager.ListUnits()."""

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
    """Single row returned from Manager.ListUnitFiles()."""

    path: str
    state: str  # enabled, disabled, masked, ...


@dataclass(frozen=True)
class InstallChange:
    """Install-time change as reported by (Un)Mask/(Dis|En)ableUnitFiles()."""

    type: str
    file: str
    destination: str


@dataclass(frozen=True)
class UnitStatus:
    """
    Combined view of runtime unit status and install-time unit file state.

    This structure merges data from ListUnits() and ListUnitFiles() and is used
    by match_units() to represent both active and inactive units.
    """

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
    High-level wrapper around the org.freedesktop.systemd1 D-Bus API.

    The client exposes convenience methods for common lifecycle actions
    (start/stop/restart), querying unit state and matching units via regular
    expressions. It can be used against the system or per-user systemd manager.
    """

    def __init__(self, *, user_manager: bool = False, use_glib: bool = False) -> None:
        """
        Create a new SystemdClient instance and connect to the systemd manager.

        Args:
            user_manager:
                If True, connect to the per-user systemd manager on the session
                bus. If False (default), connect to the system-wide manager on
                the system bus.
            use_glib:
                If True, initialise a GLib main loop and prefer a signal-based
                waiting strategy for jobs (wait_job). If False, a pure
                polling-based approach (wait_job_poll) is used instead.
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
        """Allow use as a context manager that auto-closes the D-Bus connection."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Close the underlying D-Bus connection when leaving the context."""
        self.close()

    def close(self) -> None:
        """
        Close the underlying D-Bus connection and unregister signal handlers.

        This is safe to call multiple times.
        """
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

        Raises:
            SystemdError: If the unit cannot be loaded.
        """
        try:
            return str(self._manager.GetUnit(unit))
        except DBusException:
            try:
                return str(self._manager.LoadUnit(unit))
            except DBusException as e:
                raise _map_dbus_error(e, f"LoadUnit({unit})")

    def is_active(self, unit: str) -> bool:
        """
        Return True if the unit's ActiveState is 'active'.

        Unknown units are treated as inactive and will raise UnitNotFoundError
        unless active_state() is called with a default.
        """
        return self.active_state(unit, default="inactive") == "active"

    def active_state(self, unit: str, *, default: Optional[str] = None) -> str:
        """
        Return the unit's ActiveState.

        Args:
            unit: Unit name, e.g. 'ssh.service'.
            default: Optional value returned when the unit does not exist.

        Raises:
            UnitNotFoundError: If the unit does not exist and no default is set.
        """
        try:
            return self._get_unit_prop_str(unit, "ActiveState")
        except UnitNotFoundError:
            if default is not None:
                return default
            raise

    def sub_state(self, unit: str, *, default: Optional[str] = None) -> str:
        """
        Return the unit's SubState.

        Args:
            unit: Unit name, e.g. 'ssh.service'.
            default: Optional value returned when the unit does not exist.

        Raises:
            UnitNotFoundError: If the unit does not exist and no default is set.
        """
        try:
            return self._get_unit_prop_str(unit, "SubState")
        except UnitNotFoundError:
            if default is not None:
                return default
            raise

    def get_unit_properties(
        self, unit: str, keys: Optional[Iterable[str]] = None
    ) -> Dict[str, Any]:
        """
        Fetch selected properties of a unit object.

        Args:
            unit: Unit name, e.g. 'ssh.service'.
            keys: Iterable of property names to retrieve. If omitted, a useful
                default set of properties is returned.

        Returns:
            Mapping from property name to converted Python value.
        """
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
        """
        Fetch selected properties from the Service interface for a unit.

        Args:
            unit: Unit name, e.g. 'ssh.service'.
            keys: Iterable of property names on org.freedesktop.systemd1.Service.
                If omitted, a small default subset is requested.

        Returns:
            Mapping from property name to converted Python value. Properties that
            cannot be retrieved are silently omitted from the result.
        """
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
        """
        Start a unit using Manager.StartUnit().

        Returns:
            The D-Bus job object path.
        """
        try:
            return str(self._manager.StartUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"StartUnit({unit})")

    def stop(self, unit: str, mode: str = "replace") -> str:
        """
        Stop a unit using Manager.StopUnit().

        Returns:
            The D-Bus job object path.
        """
        try:
            return str(self._manager.StopUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"StopUnit({unit})")

    def restart(self, unit: str, mode: str = "replace") -> str:
        """
        Restart a unit using Manager.RestartUnit().

        Returns:
            The D-Bus job object path.
        """
        try:
            return str(self._manager.RestartUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"RestartUnit({unit})")

    def reload(self, unit: str, mode: str = "replace") -> str:
        """
        Reload a unit using Manager.ReloadUnit().

        Returns:
            The D-Bus job object path.
        """
        try:
            return str(self._manager.ReloadUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"ReloadUnit({unit})")

    def reload_or_restart(self, unit: str, mode: str = "replace") -> str:
        """
        Reload or restart a unit using Manager.ReloadOrRestartUnit().

        Returns:
            The D-Bus job object path.
        """
        try:
            return str(self._manager.ReloadOrRestartUnit(unit, mode))
        except DBusException as e:
            raise _map_dbus_error(e, f"ReloadOrRestartUnit({unit})")

    def reset_failed(self, unit: Optional[str] = None) -> None:
        """
        Clear failed state for one unit or for all units.

        Args:
            unit: Optional unit name. If None, ResetFailed() is called and all
                failed states are cleared.
        """
        try:
            (
                self._manager.ResetFailed()
                if unit is None
                else self._manager.ResetFailedUnit(unit)
            )
        except DBusException as e:
            raise _map_dbus_error(e, f"ResetFailed({unit or ''})")

    # Polling-based variant used when GLib is not available or disabled.
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
            raise_on_fail: If True, raise JobFailedError on failed or timed-out
                jobs. If False, return "failed" or "timeout-wait" instead.
            poll_interval: Time in seconds between poll iterations.

        Returns:
            One of "done", "failed" or "timeout-wait".

        Note:
            Without GLib signals, result details like "canceled", "dependency",
            "timeout" or "skipped" cannot be distinguished precisely. The method
            relies on unit state and, for oneshot services, ExecMainStatus.
        """
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
                # As long as property 'State' can be read, the job still exists.
                _ = props.Get(
                    "org.freedesktop.systemd1.Job", "State"
                )  # 'waiting'|'running'
            except DBusException as e:
                name = getattr(e, "get_dbus_name", lambda: "")() or ""
                if name in (
                    "org.freedesktop.DBus.Error.UnknownObject",
                    "org.freedesktop.systemd1.NoSuchJob",
                ):
                    break  # Job removed -> finished
                raise _map_dbus_error(e, f"JobPoll({job_path})")
            time.sleep(poll_interval)

        # Heuristic evaluation based on unit state.
        try:
            st = self.active_state(unit_name, default="inactive")
        except SystemdError:
            st = "failed"

        ok = False
        if job_type == "stop":
            # After a stop job the unit should definitely not be 'active'.
            ok = st in ("inactive", "failed")
        else:
            if st == "active":
                ok = True
            else:
                # oneshot / reload: inspect ExecMainStatus when available.
                sp = self.get_service_properties(
                    unit_name, keys=("Type", "ExecMainStatus")
                )
                if str(sp.get("Type", "")) == "oneshot":
                    ok = int(sp.get("ExecMainStatus", 0)) == 0
                elif st != "failed":
                    # Fallback: anything not explicitly failed counts as success.
                    ok = True

        if not ok:
            if raise_on_fail:
                raise JobFailedError(f"job {job_path} result=failed")
            return "failed"

        return "done"

    def wait_job(
        self,
        job_path: str,
        *,
        timeout_sec: Optional[float] = None,
        raise_on_fail: bool = True,
    ) -> str:
        """
        Wait for completion of a systemd job using GLib JobRemoved signals.

        This method is used when use_glib=True and GLib is available. It listens
        for the Manager.JobRemoved signal and derives the job result from the
        'result' argument.

        Args:
            job_path: D-Bus object path of the job.
            timeout_sec: Optional timeout in seconds. If None, wait indefinitely.
            raise_on_fail: If True, raise JobFailedError for all results other
                than "done" or a local timeout.

        Returns:
            "done" on success, "failed" on error or "timeout-wait" if the local
            wait timeout expires.
        """
        if GLib is None:
            # Defensive fallback; normally guarded by _wait_job_dispatch.
            return self.wait_job_poll(
                job_path, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
            )

        if not self._signals_enabled:
            # If subscription is not possible, fall back to polling.
            try:
                self.subscribe()
            except SystemdError:
                return self.wait_job_poll(
                    job_path, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
                )

        result_holder: Dict[str, Optional[str]] = {"result": None}
        loop = GLib.MainLoop()

        def _on_job_removed(job_id, job_path_signal, unit, result) -> None:
            if str(job_path_signal) != job_path:
                return
            result_holder["result"] = str(result)
            loop.quit()

        self._bus.add_signal_receiver(
            _on_job_removed,
            signal_name="JobRemoved",
            dbus_interface=IFACE_MANAGER,
            path=MANAGER_PATH,
        )

        def _on_timeout() -> bool:
            if result_holder["result"] is not None:
                return False
            result_holder["result"] = "timeout-wait"
            loop.quit()
            return False

        if timeout_sec is not None:
            GLib.timeout_add(int(timeout_sec * 1000), _on_timeout)

        try:
            loop.run()
        finally:
            try:
                self._bus.remove_signal_receiver(
                    _on_job_removed,
                    signal_name="JobRemoved",
                    dbus_interface=IFACE_MANAGER,
                    path=MANAGER_PATH,
                )
            except Exception:
                pass

        result = result_holder["result"] or "failed"
        if result == "timeout-wait":
            if raise_on_fail:
                raise JobFailedError(f"job {job_path} result=timeout-wait")
            return "timeout-wait"

        if result != "done":
            if raise_on_fail:
                raise JobFailedError(f"job {job_path} result={result}")
            return "failed"

        return "done"

    # --------- Lifecycle (blocking auf Job-Resultat) ---------

    def start_wait(
        self,
        unit: str,
        mode: str = "replace",
        *,
        timeout_sec: Optional[float] = None,
        raise_on_fail: bool = True,
    ) -> str:
        """
        Start a unit and wait for the corresponding job to finish.

        See wait_job_poll() / wait_job() for the meaning of timeout_sec and
        raise_on_fail.
        """
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
        """
        Stop a unit and wait for the corresponding job to finish.
        """
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
        """
        Restart a unit and wait for the corresponding job to finish.
        """
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
        """
        Reload a unit and wait for the corresponding job to finish.
        """
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
        """
        Reload or restart a unit and wait for the corresponding job to finish.
        """
        job = self.reload_or_restart(unit, mode)
        return self._wait_job_dispatch(
            job, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
        )

    # --------- Unit files / Listings ---------

    def enable(
        self, names: Iterable[str], *, runtime: bool = False, force: bool = True
    ) -> Tuple[bool, List[InstallChange]]:
        """
        Enable unit files via Manager.EnableUnitFiles().

        Args:
            names: Iterable of unit file names.
            runtime: If True, only enable for the current runtime.
            force: If True, overwrite existing symlinks.

        Returns:
            Tuple (carries_install_info, changes) where carries_install_info
            indicates whether enablement carries install information and changes
            is the list of InstallChange objects.
        """
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
        """
        Disable unit files via Manager.DisableUnitFiles().
        """
        try:
            changes = self._manager.DisableUnitFiles(list(names), runtime)
            return [InstallChange(*map(str, c)) for c in changes]
        except DBusException as e:
            raise _map_dbus_error(e, f"DisableUnitFiles({','.join(names)})")

    def mask(
        self, names: Iterable[str], *, runtime: bool = False, force: bool = True
    ) -> List[InstallChange]:
        """
        Mask unit files via Manager.MaskUnitFiles().
        """
        try:
            changes = self._manager.MaskUnitFiles(list(names), runtime, force)
            return [InstallChange(*map(str, c)) for c in changes]
        except DBusException as e:
            raise _map_dbus_error(e, f"MaskUnitFiles({','.join(names)})")

    def unmask(
        self, names: Iterable[str], *, runtime: bool = False
    ) -> List[InstallChange]:
        """
        Unmask unit files via Manager.UnmaskUnitFiles().
        """
        try:
            changes = self._manager.UnmaskUnitFiles(list(names), runtime)
            return [InstallChange(*map(str, c)) for c in changes]
        except DBusException as e:
            raise _map_dbus_error(e, f"UnmaskUnitFiles({','.join(names)})")

    def get_unit_file_state(self, file: str) -> str:
        """
        Return the unit file state for a given file name.

        Examples: 'enabled', 'disabled', 'masked', ...
        """
        try:
            return str(self._manager.GetUnitFileState(file))
        except DBusException as e:
            raise _map_dbus_error(e, f"GetUnitFileState({file})")

    def list_units(self) -> List[Unit]:
        """
        List all currently loaded units.

        Returns:
            List of Unit objects mirroring the fields returned by ListUnits().
        """
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
        """
        Trigger a systemd daemon reload (Manager.Reload()).
        """
        try:
            self._manager.Reload()
        except DBusException as e:
            raise _map_dbus_error(e, "Reload(daemon)")

    # --------- Signals ---------

    def subscribe(self) -> None:
        """
        Subscribe to systemd manager events.

        This is required for receiving property change and JobRemoved signals.
        """
        try:
            self._manager.Subscribe()
            self._signals_enabled = True
        except DBusException as e:
            raise _map_dbus_error(e, "Subscribe")

    def unsubscribe(self) -> None:
        """
        Unsubscribe from systemd manager events.
        """
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
        """
        Register a callback for unit property changes.

        Args:
            unit: Unit name, e.g. 'ssh.service'.
            callback: Callable receiving a dict of changed properties (already
                converted with _py()).
            only: Optional iterable of property names to filter for.

        Returns:
            A callable that, when invoked, unregisters the signal handler.
        """
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

    # --------- Regex matching across units ---------

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

        # Union of live units and matching unit files.
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

    # --------- Low-level helpers ---------

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
        """
        Return a cached Properties interface proxy for the given unit.
        """
        path = self._get_unit_path(unit)
        if path in self._unit_props_cache:
            return self._unit_props_cache[path]

        obj = self._bus.get_object(SERVICE, path)
        props = Interface(obj, IFACE_PROPS)
        self._unit_props_cache[path] = props

        return props

    def _get_unit_prop_str(self, unit: str, prop: str) -> str:
        """
        Helper to read a single unit property as string.

        Raises:
            UnitNotFoundError: If the unit does not exist.
        """
        props = self._props_iface_for_unit(unit)
        try:
            return str(props.Get(IFACE_UNIT, prop))
        except DBusException as e:
            raise _map_dbus_error(e, f"Get({unit},{prop})")

    def _wait_job_dispatch(
        self, job_path: str, *, timeout_sec: Optional[float], raise_on_fail: bool
    ) -> str:
        """
        Dispatch job waiting to either the GLib or the polling implementation.

        This is used internally by the *_wait() lifecycle helpers.
        """
        if self._glib_enabled and GLib is not None:
            return self.wait_job(
                job_path, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
            )

        return self.wait_job_poll(
            job_path, timeout_sec=timeout_sec, raise_on_fail=raise_on_fail
        )
