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
| [journalctl](./plugins/modules/journalctl.py)   | Query the systemd journal with a very limited number of possible parameters |
| [unit_file](./plugins/modules/unit_file.py)     | This can be used to create a systemd unit file. The `service`, `timer` and `socket` types are supported. |


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


You can either call modules by their Fully Qualified Collection Name (FQCN), such as `bodsch.systemd.remove_ansible_backups`, 
or you can call modules by their short name if you list the `bodsch.systemd` collection in the playbook's `collections` keyword:

```yaml
---
- name: remove older ansible backup files
  bodsch.systemd.remove_ansible_backups:
    path: /etc
    holds: 4
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
