# Tests

Tests for the plugins/modules of this collection that do **not** require a
dedicated role or a molecule scenario.

## Layout

```
tests/
├── integration/targets/systemd_timer/   # ansible-test integration target
│   ├── aliases
│   └── tasks/main.yml                    #   present / idempotency / check mode / absent / validation
└── unit/plugins/modules/                 # ansible-test unit tests
    └── test_systemd_timer.py             #   resolve_scope() / build_calendar_spec()
```

The `systemd_timer` tests are hermetic: they render unit files into a temporary
directory with `daemon_reload: false` and without `enabled`, so they need
neither root, `python3-dbus` nor a running service manager.

## Running with `ansible-test` (official)

`ansible-test` requires the collection to live at a real path ending in
`ansible_collections/<namespace>/<name>/` (symlinks are resolved and do not
count). With the checkout located accordingly:

```sh
cd .../ansible_collections/bodsch/systemd

ansible-test units       --local --python 3.12 systemd_timer
ansible-test integration --local --python 3.12 systemd_timer
```

## Running without that layout (quick, location-independent)

Make the working tree importable under its collection namespace once:

```sh
mkdir -p /tmp/sdtest/ansible_collections/bodsch
ln -sfn "$PWD" /tmp/sdtest/ansible_collections/bodsch/systemd
export ANSIBLE_COLLECTIONS_PATH="/tmp/sdtest:$HOME/.ansible/collections"
```

### Unit tests via pytest

```sh
PYTHONPATH=/tmp/sdtest python3 -m pytest \
    tests/unit/plugins/modules/test_systemd_timer.py -v
```

### Integration target via a wrapper play

The integration target is a plain tasks file, so it can be driven by any
playbook that imports it:

```sh
cat > /tmp/wrap.yml <<'YML'
---
- hosts: localhost
  gather_facts: false
  tasks:
    - import_tasks: "{{ tasks_file }}"
YML

ansible-playbook -i localhost, -c local /tmp/wrap.yml \
    -e tasks_file="$PWD/tests/integration/targets/systemd_timer/tasks/main.yml"
```
