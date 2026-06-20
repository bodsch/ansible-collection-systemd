# Ansible Role:  `bodsch.systemd.networkd`

Configure systemd networkd.


## Role Variables

```yaml
systemd_networkd: {}
  # speed_meter: false
  # speed_meter_interval_sec: 10sec
  # manage_foreign_routing_policy_rules: true
  # manage_foreign_routes: true
  # route_table: ""
  # ipv6_privacy_extensions: false
  # dhcp4:
  #   duid_type: vendor
  #   duid_raw_data: ""
  # dhcp6:
  #   duid_type: vendor
  #   duid_raw_data: ""

systemd_networkd_profiles:
  link: {}
  netdev: {}
  network: {}
  purge: false
  validate: true
  validate_strict: false
  validate_timeout: 30
```

### `systemd_networkd_profiles`

```yaml
systemd_networkd_profiles:
  link: {}
  netdev:
    br0:
      state: absent
      config:
        NetDev:
          Name: br0
          Kind: bridge

  network:
    etx0:
      state: absent
      description: device etx0 for special stuff
      config:
        Match:
          Name: "etx0"
        Network:
          DHCP: false
          IPv6AcceptRouterAdvertisements: false
          Domains: "your.tld"
          DNS:
            - 1.1.1.1
            - 141.1.1.1
          Address:
            - "192.0.2.176/24"
            - "2001:db8::302/64"
            - "fc00:0:0:103::302/64"
          Gateway:
            - "192.0.2.1"
            - "2001:db8::1"
    uplink:
      config:
        Match:
          Name: etx0
        Network:
          Bridge: br0

    etX1:
      state: present
      config:
        Match:
          Name: etX1
        Network:
          DHCP: false
          DNS:
            - 1.1.1.1
            - 141.1.1.1
        Address:
          - Address: 10.10.0.1/24
            Label: primary
          - Address: 10.10.0.2/24
        Route:
          - Gateway: 10.10.0.254
            Destination: 10.20.0.0/16
          - Gateway: 10.10.0.253
            Destination: 10.30.0.0/16
```



### `bodsch.systemd.networkd_profiles`

The renderer is generic and makes no assumptions about permitted section names or keys.  
As long as systemd adheres to the following scheme – and it does so for `.link`/`.netdev`/`.network` – 
you can pass through any section and any key:

```bash
[SectionName]
Key=Value
Key=Value
```

This covers all the sections documented in systemd.link(5), systemd.netdev(5) and systemd.network(5).  
For reference – these are the most important ones:

| File      | Section |
| :----     | :----     |
| `.link`   | `Match`, `Link`, `SR-IOV`, `CAN`, `IPoIB`, `Wakeup` |
| `.netdev` | `Match`, `NetDev`, <br>plus one of their own per child: `Bridge`, `Bond`, `VLAN`, `MACVLAN`, `IPVLAN`, `VXLAN`, `GENEVE`, `Tunnel`, `WireGuard`, `WireGuardPeer` (several times!), `Tun`, `Tap`, `L2TP`, `L2TPSession` (several times!), `MACsec`, `MACsecReceiveChannel` (several times!), `MACsecTransmitAssociation` (several times!), `MACsecReceiveAssociation` (several times!), `VRF`, `Xfrm`, `BareUDP`, `BatmanAdvanced`, `IPVTap`, `FooOverUDP` |
| `.network`| `Match`, `Link`, `SR-IOV`, `Network`, `Address` (several times!), `Neighbor` (several times!), `IPv6AddressLabel`, `RoutingPolicyRule` (several times!), `NextHop` (several times!), `Route` (several times!), `DHCPv4`, `DHCPv6`, `DHCPPrefixDelegation`, `IPv6AcceptRA`, `IPv6SendRA`, `IPv6Prefix`, `IPv6RoutePrefix`, `IPv6PREF64Prefix`, `Bridge`, `BridgeFDB` (several times!), `BridgeMDB` (several times!), `BridgeVLAN`, `LLDP`, `CAN`, `IPoIB`, `QDisc`, <br>and the entire family of traffic control sections (`HierarchyTokenBucket`, `HierarchyTokenBucketClass`, `NetworkEmulator`, `FairQueueing`, `FairQueueingControlledDelay`, `ControlledDelay`, `StochasticFairnessQueueing`, `StochasticFairBlue`, `BFIFO`, `PFIFO`, `PFIFOHeadDrop`, `PFIFOFast`, `CAKE`, `DeficitRoundRobinScheduler`, `DeficitRoundRobinSchedulerClass`, `EnhancedTransmissionSelection`, `GenericRandomEarlyDetection`, `FlowQueuePIE`, `HeavyHitterFilter`, `QuickFairQueueing`, `QuickFairQueueingClass`, `TrivialLinkEqualizer`, `PIE`) |

### `systemd_networkd_profile`

**no-not-use**

```yaml
#     - name: manage .link profiles
#       bodsch.systemd.networkd_profile:
#         name: "{{ item.key }}"
#         profile_type: link
#         state: "{{ item.value.state | default('present') }}"
#         description: "{{ item.value.description | default(omit) }}"
#         config: "{{ item.value.config | default({}) }}"
#       loop: "{{ (systemd_networkd_profiles.link | default({})) | dict2items }}"
#       loop_control:
#         label: "{{ item.key }}.link"
#       notify: reload systemd-networkd

```



## freedesktop

[systemd networkd](https://www.freedesktop.org/software/systemd/man/networkd.conf.html)

---

## Author

- Bodo Schulz
