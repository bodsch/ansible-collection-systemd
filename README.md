# Ansible Collection - bodsch.systemd

Documentation for the collection.

## Roles

| Role | | Description |
| :---- | :---- | :---- |
| [bodsch.systemd.coredump](./roles/coredump/README.md)            |       |       |
| [bodsch.systemd.homed](./roles/homed/README.md)                |       |       |
| [bodsch.systemd.journald](./roles/journald/README.md)  |       |       |
| [bodsch.systemd.oomd](./roles/oomd/README.md)                  |       |       |
| [bodsch.systemd.logind](./roles/logind/README.md)          |       |       |
| [bodsch.systemd.networkd](./roles/networkd/README.md)        |       |       |
| [bodsch.systemd.resolved](./roles/resolved/README.md)        |       |       |
| [bodsch.systemd.system](./roles/system/README.md)          |       |       |
| [bodsch.systemd.timesyncd](./roles/timesyncd/README.md)                  |       |       |
| [bodsch.systemd.user](./roles/user/README.md)                |       |       |


## Modules

### `amtool`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.amtool` | |


### `promtool`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.promtool` | |

### `alertmanager_silence`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.alertmanager_silence` | |


### `alertmanager_templates`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.alertmanager_templates` | |


### `systemd_alert_rule`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.systemd_alert_rule` | |


### `systemd_alert_rules`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.systemd_alert_rules` | |

## Filters

### `mysql_exporter`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.valid_credentials` | |
| `bodsch.systemd.has_credentials` | |

### `nginx_exporter`


| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.nginx_exporter_systemd_labels` | |

### `parse_checksum`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.parse_checksum` | |

### `systemd`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.validate_file_sd` | |
| `bodsch.systemd.validate_alertmanager_endpoints` | |
| `bodsch.systemd.remove_empty_elements` | |
| `bodsch.systemd.jinja_encode` | |

### `silencer`

| Name  | Description |
| :---- | :---- |
| `bodsch.systemd.expired` | |
| `bodsch.systemd.current_datetime` | |
