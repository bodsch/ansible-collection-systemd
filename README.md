# Ansible Collection - bodsch.systemd

Documentation for the collection.

## Roles

| Role | | Description |
| :---- | :---- | :---- |
| [bodsch.systemd.coredump](./roles/coredump/README.md)   |       |       |
| [bodsch.systemd.homed](./roles/homed/README.md)         |       |       |
| [bodsch.systemd.journald](./roles/journald/README.md)   |       |       |
| [bodsch.systemd.oomd](./roles/oomd/README.md)           |       |       |
| [bodsch.systemd.logind](./roles/logind/README.md)       |       |       |
| [bodsch.systemd.networkd](./roles/networkd/README.md)   |       |       |
| [bodsch.systemd.resolved](./roles/resolved/README.md)   |       |       |
| [bodsch.systemd.system](./roles/system/README.md)       |       |       |
| [bodsch.systemd.timesyncd](./roles/timesyncd/README.md) |       |       |
| [bodsch.systemd.user](./roles/user/README.md)           |       |       |


## Included content

### Modules

| Name                      | Description |
|:--------------------------|:----|
| [journalctl](./plugins/modules/journalctl.py)   | Query the systemd journal with a very limited number of possible parameters |


## Installing this collection

You can install the memsource collection with the Ansible Galaxy CLI:

```sh
#> ansible-galaxy collection install bodsch.systemd
```

To install directly from GitHub:

```sh
#> ansible-galaxy collection install git@github.com:bodsch/ansible-collection-core.git
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

If you want to use something stable, please use a [Tagged Version](https://github.com/bodsch/ansible-collection-core/tags)!


## Author

- Bodo Schulz

## License

[Apache](LICENSE)

**FREE SOFTWARE, HELL YEAH!**
