# Ansible Collection - bodsch.systemd

Documentation for the collection.

## Roles

| Role | | Description |
| :---- | :---- | :---- |
| [bodsch.systemd.coredump](./roles/coredump/README.md)   | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/coredump.yml?branch=main)][coredump] | configure systemd-coredump  |
| [bodsch.systemd.homed](./roles/homed/README.md)         | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/homed.yml?branch=main)][homed] | configure systemd-homed     |
| [bodsch.systemd.journald](./roles/journald/README.md)   | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/journald.yml?branch=main)][journald] | configure systemd-journald  |
| [bodsch.systemd.oomd](./roles/oomd/README.md)           | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/oomd.yml?branch=main)][oomd] | configure systemd-oomd      |
| [bodsch.systemd.logind](./roles/logind/README.md)       | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/logind.yml?branch=main)][logind] | configure systemd-logind    |
| [bodsch.systemd.networkd](./roles/networkd/README.md)   | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/networkd.yml?branch=main)][networkd] | configure systemd-networkd  |
| [bodsch.systemd.resolved](./roles/resolved/README.md)   | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/resolved.yml?branch=main)][resolved] | configure systemd-resolved  |
| [bodsch.systemd.system](./roles/system/README.md)       | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/system.yml?branch=main)][system] | configure systemd-system    |
| [bodsch.systemd.timesyncd](./roles/timesyncd/README.md) | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/timesyncd.yml?branch=main)][timesyncd] | configure systemd-timesyncd |
| [bodsch.systemd.user](./roles/user/README.md)           | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-systemd/user.yml?branch=main)][user] | configure systemd-user      |

[coredump]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/coredump.vml
[homed]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/homed.vml
[journald]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/journald.vml
[oomd]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/oomd.vml
[logind]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/logind.vml
[networkd]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/networkd.vml
[resolved]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/resolved.vml
[system]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/system.vml
[timesyncd]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/timesyncd.vml
[user]: https://github.com/bodsch/ansible-collection-systemd/actions/workflows/user.vml


## Included content

### Modules

| Name                      | Description |
|:--------------------------|:----|
| [bodsch.systemd.journalctl](./plugins/modules/journalctl.py)       | Query the systemd journal with a very limited number of possible parameters |
| [bodsch.systemd.unit_file](./plugins/modules/unit_file.py)         | This can be used to create a systemd unit file. The `service`, `timer` and `socket` types are supported. |
| [bodsch.systemd.systemd_timer](./plugins/modules/systemd_timer.py) | This can be used to create a systemd timer file. |


## Installing this collection

You can install the memsource collection with the Ansible Galaxy CLI:

```sh
#> ansible-galaxy collection install bodsch.systemd
```

To install directly from GitHub:

```sh
#> ansible-galaxy collection install git@github.com:bodsch/ansible-collection-systemd.git
```


You can also include it in a `requirements.yml` file and install it with `ansible-galaxy collection install -r requirements.yml`, using the format:

```yaml
---
collections:
  - name: bodsch.systemd
```

The python module dependencies are not installed by `ansible-galaxy`.  They can
be manually installed using pip:

```sh
#> pip install -r requirements.txt
```

## Using this collection


You can either call modules by their Fully Qualified Collection Name (FQCN), such as `bodsch.systemd.coredump`, 
or you can call modules by their short name if you list the `bodsch.systemd` collection in the playbook's `collections` keyword:

```yaml
---
- name: configure systemd coredump
  bodsch.systemd.coredump:
    process_size_max: 32G
    external_size_max: 32G
```


## Examples

### `bodsch.systemd.journalctl`

```yaml

- name: query the systemd journal
  bodsch.systemd.journalctl:
    identifier: chrony
    lines: 150
  register: journalctl
  when:
    - restarted is defined
    - restarted.failed
    - chrony_query_journald
    - ansible_service_mgr == 'systemd'
  notify:
    - journalctl output

- name: journalctl output
  ansible.builtin.debug:
    msg: "{{ journalctl.stdout }}"
  when:
    journalctl.stdout is defined
```

### `bodsch.systemd.systemd_timer`

```yaml
name: create systemd timer file
bodsch.systemd.systemd_timer:
  name: certbot-renew
  unit:
    Description: Run Certbot on specific weekdays
  timer:
    persistent: true
    randomized_delay_sec: "43200"
  schedule:
    weekday: "{{ certbot_cron.weekday | default(['Sat']) }}"
    hour: "{{ certbot_cron.hour | default('2') }}"
    minute: "{{ certbot_cron.minute | default('58') }}"
  install:
    wanted_by: timers.target
  path: "{{ systemd_lib_directory }}"
notify:
  - daemon reload
```



### `bodsch.systemd.unit_file`

```yaml
- name: create getty drop-ins
  bodsch.systemd.unit_file:
    name: "getty@tty1"
    state: "present"
    unit_type: "service"
    drop_ins:
      - name: autologin
        state: present
        service:
          ExecStart:
            - ""
            - "{% raw %}-/sbin/agetty -o '-p -f -- \\\\u' --noclear --autologin username %I $TERM{% endraw %}"
          Type: simple

      - name: noclear
        state: absent
        service:
          TTYVTDisallocate: false
  when:
    - ansible_facts.service_mgr == 'systemd'

- name: create nextcloud-cron systemd service
  bodsch.systemd.unit_file:
    name: "nextcloud-cron"
    state: "present"
    unit_type: "service"
    unit_file:
      unit:
        Description: Nextcloud cron.php job
      service:
        User: www-data
        ExecCondition: php -f /var/www/nextcloud/server/occ status --exit-code
        ExecStart: /usr/bin/php -f /var/www/nextcloud/server/cron.php
        KillMode: process
  when:
    - ansible_facts.service_mgr == 'systemd'

- name: create nextcloud-cron systemd timer
  bodsch.systemd.unit_file:
    name: "nextcloud-cron"
    state: "present"
    unit_type: "timer"
    unit_file:
      unit:
        Description: Run Nextcloud cron.php every 5 minutes
      timer:
        OnBootSec: 5min
        OnUnitActiveSec: 5min
        Unit: nextcloud-cron.service
      install:
        WantedBy: timers.target
  when:
    - ansible_facts.service_mgr == 'systemd'

- name: create systemd unit files
  bodsch.systemd.unit_file:
    name: "{{ item.name }}"
    state: "{{ item.state }}"
    unit_type: "{{ item.unit_type }}"
    overwrite: "{{ item.overwrite | default(omit) }}"
    drop_ins: "{{ item.drop_ins | default(omit) }}"
    unit_file: "{{ item.unit_file | default(omit) }}"
  loop:
    "{{ systemd_unit }}"
  loop_control:
    label: "{{ item.name }}"
  register: systemd_unit_file
  ignore_errors: true
  when:
    - systemd_unit | count > 0
```

## Contribution

Please read [Contribution](CONTRIBUTING.md)

## Development,  Branches (Git Tags)

The `master` Branch is my *Working Horse* includes the "latest, hot shit" and can be complete broken!

If you want to use something stable, please use a [Tagged Version](https://github.com/bodsch/ansible-collection-systemd/tags)!


## Author

- Bodo Schulz

## License

[Apache](LICENSE)

**FREE SOFTWARE, HELL YEAH!**
