# Protocol source

Upstream: https://github.com/xiasi0/ha-huawei-smarthome

Snapshot: `87ccc37b61080a88b32c4fc1ada72c0712b49093`.

The selected Python modules come from the locally verified standalone lamp tool
(`20261024-hw-light/tools/lamp_control/vendor`). They preserve its login and SMS
flow, including its CAS cookie handling. The Home Assistant entry point is
replaced with a package marker. No MQTT or device-control module is included.

These modules and this helper are distributed under GPL-3.0-only. The complete
license is in `huawei_smarthome/LICENSE`. The helper's corresponding source,
requirements and build script are included alongside the download on this site
and in the LazyStick-Remote repository.
