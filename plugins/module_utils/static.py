# Whitelists für Strict-Mode (nicht vollständig, aber praxisnahe Basis)
VALID_UNIT_KEYS = {
    "Description",
    "Documentation",
    "Requires",
    "Wants",
    "BindsTo",
    "PartOf",
    "Conflicts",
    "Before",
    "After",
    "OnFailure",
    "PropagatesReloadTo",
    "RequiresMountsFor",
    "ConditionPathExists",
    "ConditionPathExistsGlob",
    "ConditionPathIsDirectory",
    "ConditionPathIsSymbolicLink",
    "ConditionPathIsMountPoint",
    "ConditionArchitecture",
    "ConditionVirtualization",
    "ConditionHost",
    "ConditionKernelCommandLine",
    "ConditionSecurity",
    "ConditionFirstBoot",
    "ConditionNeedsUpdate",
    "ConditionACPower",
    "AssertPathExists",
    "AssertPathExistsGlob",
    "AssertPathIsDirectory",
    "AssertPathIsSymbolicLink",
    "AssertPathIsMountPoint",
    "AssertArchitecture",
    "AssertVirtualization",
    "AssertHost",
    "AssertKernelCommandLine",
    "AssertSecurity",
    "AssertFirstBoot",
    "AssertNeedsUpdate",
    "AssertACPower",
}

VALID_TIMER_KEYS = {
    "OnActiveSec",
    "OnBootSec",
    "OnStartupSec",
    "OnUnitActiveSec",
    "OnUnitInactiveSec",
    "OnCalendar",
    "AccuracySec",
    "RandomizedDelaySec",
    "Unit",
    "Persistent",
    "WakeSystem",
    "RemainAfterElapse",
    "TimerSlackNSec",
    "TimeZone",
    "FixedRandomDelay",
}

VALID_INSTALL_KEYS = {
    "WantedBy",
    "RequiredBy",
    "Also",
    "Alias",
    "DefaultInstance",
}

# Timer-Optionen, die Timespans sind
TIMER_TIMESPAN_KEYS = {
    "RandomizedDelaySec",
    "AccuracySec",
    "OnActiveSec",
    "OnBootSec",
    "OnUnitActiveSec",
    "OnUnitInactiveSec",
}

TIMER_TIMESPAN_PARAM_KEYS = {
    "randomized_delay_sec",
    "accuracy_sec",
    "on_active_sec",
    "on_boot_sec",
    "on_unit_active_sec",
    "on_unit_inactive_sec",
}

# Timer-Optionen, die boolsche Werte sind
TIMER_BOOL_KEYS = {
    "Persistent",
    "WakeSystem",
    "RemainAfterElapse",
}

TIMER_BOOL_PARAM_KEYS = {
    "persistent",
    "wake_system",
    "remain_after_elapse",
}

VALID_WEEKDAY_TOKENS = {
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
}

# optionale Aliase
WEEKDAY_ALIASES = {
    # Englisch
    "mon": "Mon",
    "monday": "Mon",
    "tue": "Tue",
    "tues": "Tue",
    "tuesday": "Tue",
    "wed": "Wed",
    "wednesday": "Wed",
    "thu": "Thu",
    "thur": "Thu",
    "thurs": "Thu",
    "thursday": "Thu",
    "fri": "Fri",
    "friday": "Fri",
    "sat": "Sat",
    "saturday": "Sat",
    "sun": "Sun",
    "sunday": "Sun",
}
