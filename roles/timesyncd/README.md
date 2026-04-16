# Ansible Role:  `bodsch.systemd.timesyncd`

Configure systemd timesyncd.


## Role Variables

```yaml
systemd_timesyncd: {}
  # ntp: []
  # fallback_ntp: []                    # 0.arch.pool.ntp.org 1.arch.pool.ntp.org 2.arch.pool.ntp.org 3.arch.pool.ntp.org
  # root_distance_max_sec: ""           # 5
  # poll_interval_min_sec: ""           # 32
  # poll_interval_max_sec: ""           # 2048
  # connection_retry_sec: ""            # 30
  # save_interval_sec: ""               # 60
```

## freedesktop

[systemd timesyncd](https://www.freedesktop.org/software/systemd/man/timesyncd.conf.html)

---

## Author

- Bodo Schulz
