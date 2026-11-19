# ha-peak-guard

PeakPilot calculates battery power setpoints to help keep grid import within a
configurable quarter-hour peak target. It exposes measurements, controller
status, and signed setpoints in Home Assistant. **It does not send commands to
the battery**; use the setpoint sensors in your own automation if you want to
control an inverter.

## Control methodology

### Quarter-hour energy budget

Grid power is sampled every five seconds. Positive grid power means import;
negative means export. The integration accumulates only imported energy in each
15-minute interval. Samples are linearly interpolated, including when power
crosses between import and export.

The target peak in kW corresponds to an interval energy budget of
`target_peak_kW × 0.25` kWh. At each update, the remaining budget and time in
the interval give the maximum average grid power still allowed:

`allowed_grid_power_W = remaining_energy_kWh × 3,600,000 / remaining_seconds`

The controller compares measured grid power with this allowed power. This
remaining-power limit changes through the interval as energy is imported and
time runs out.

An interval is usable for control only when its measurement coverage is
sufficient and no sample gap exceeds 30 seconds. Incomplete or stale interval
data inhibits control rather than being treated as zero import. At startup, the
integration attempts to restore interval data from saved state or Home
Assistant Recorder history. Only fully covered intervals contribute to the
monthly peak.

### PI peak-shaving controller

The controller uses a proportional-integral (PI) calculation. Its error is
grid power minus allowed remaining grid power. A low-pass filter smooths the
error, but a large positive excursion uses the current raw measurement so the
filter does not delay peak protection.

The raw PI output is a non-negative discharge request. It is constrained by
the battery's configured maximum discharge power, a minimum state-of-charge
(SoC) reserve, a ramp-rate limit, and the export-safety limit below. Activation
and deactivation thresholds, minimum on/off times, and the filter help avoid
unnecessary switching and rapid setpoint changes.

The integrator uses back-calculation anti-windup:

`dI/dt = Ki × error + (limited_setpoint - raw_PI_output) / Tt`

The correction tracks the final achievable setpoint, including power and ramp
constraints. **PI Anti-windup Tracking Time** (`Tt`) defaults to 15 seconds.
A smaller value unwinds the integral more quickly when constrained; a larger
value makes the correction slower. The controller does not use measured
battery output as PI feedback: anti-windup tracks the commanded setpoint.

### Export prevention

The configured battery-power sensor is normalized to the controller's sign
convention: positive means battery discharge; negative means battery charging.
Power sensors with units W or kW are supported. The export-safe maximum
discharge is:

`max(0, grid_import_W + measured_battery_discharge_W - export_safety_margin_W)`

This estimates household consumption from grid power and measured battery
discharge, then leaves the configured safety margin. The limit is a hard
ceiling: it can reduce the discharge setpoint immediately, even when that
exceeds the normal ramp-down rate. The default margin is 150 W.

If a required sensor is missing, unavailable, invalid, or has an unsupported
unit, the integration reports unavailable data and inhibits control; it does
not assume it is safe to discharge.

### Charging modes

When discharge is not required, the mode manager can select:

- **Solar charge:** when estimated solar surplus is at least 200 W and SoC is
  below the maximum charging SoC. Charging power is limited by the battery's
  configured maximum charging power and uses a 100 W surplus reserve. The
  grid-charging limit does not restrict solar charging.
- **Grid charge:** when SoC is below the grid-charging SoC limit, at least
  500 W of peak headroom remains after the configurable grid-charge margin
  and discharge has not already started in the current quarter-hour. Charging
  is limited by both the battery's configured maximum and the separate
  **Maximum Grid Charge Power** number; the lower limit applies. The charge
  setpoint is additionally capped so projected grid import does not exceed
  the lower of the target peak and the remaining quarter-hour energy budget.
- **Idle:** when neither charging mode is eligible.

Solar surplus is estimated from grid power plus measured battery discharge.
Charging setpoints are negative; discharging setpoints are positive. Charging
power increases are ramp-limited, while a reduction in charging is applied
immediately if surplus or headroom falls. Once discharge actually starts,
grid charging remains blocked until the next quarter-hour. Solar charging can
still be selected after discharge if its conditions are met.

## Home Assistant setup

The integration setup/reconfigure flow asks for:

| Input | Meaning | Default |
| --- | --- | --- |
| Grid power sensor | Grid power in W or kW; positive is import and negative is export. | Required |
| Battery SoC sensor | Battery state of charge in percent. | Required |
| Battery power sensor | Battery power in W or kW, used for export prevention and surplus estimation. | Required |
| Battery power sign | Choose whether the source sensor reports positive power while discharging or charging. | Positive = discharging |
| Maximum discharge power | Upper limit for the peak-shaving discharge request, in W. | 2500 W |
| Battery maximum charging power | Hard upper limit for both solar and grid charging, in W. | 2500 W |
| Minimum SoC | Hard lower limit for discharging, in percent. | 20% |

Set the battery-power sign to match the source sensor. For example, if the
sensor is positive while charging, choose **Positive = charging**. Internally,
the integration always uses positive = discharging and negative = charging.

## Home Assistant entities

### Sensors

| Entity | Unit | Meaning |
| --- | --- | --- |
| Grid Power | W | Latest measured grid power; positive import, negative export. |
| Battery SOC | % | Latest battery state of charge. |
| Measured Battery Power | W | Battery power normalized to positive = discharging. |
| Export-safe Maximum Discharge | W | Current hard ceiling on battery discharge. |
| Battery Setpoint | W | Signed calculated setpoint; positive = discharge, negative = charge. |
| Battery Operating Mode | — | `discharge`, `solar_charge`, `grid_charge`, or `idle`. |
| Battery Operating Mode Reason | — | Machine-readable reason for the selected mode. |
| Available Solar Surplus | W | Estimated solar surplus available for charging. |
| Available Peak Charging Headroom | W | Remaining grid-power headroom available to grid charging. |
| Monthly Peak | kW | Highest fully covered quarter-hour average import recorded for the month. |
| Quarter-hour Imported Energy | kWh | Imported energy accumulated in the current 15-minute interval. |
| Quarter-hour Remaining Time | s | Time remaining in the current interval. |
| Quarter-hour Remaining Power | W | Maximum average grid power allowed for the rest of the interval. |
| Allowed Remaining Grid Power | W | Same remaining-power limit, exposed under an alternate name. |
| Uncontrolled Projected Quarter-hour Peak | kW | Projection if the current positive grid import continued for the remaining interval, without battery peak shaving. |
| PI Controller Error | W | Filtered grid-power error relative to the remaining-power limit, with immediate raw response to large positive excursions. |
| PI Integral Contribution | W | Integral term in the PI output. |
| PI Unconstrained Output | W | PI output before discharge, export, and ramp limits. |
| Controller Status | — | Controller status such as `discharging`, `idle`, or a limiting/waiting status. |

### Binary sensors

| Entity | Meaning |
| --- | --- |
| Control Data Valid | Whether current interval data is sufficiently complete and current for control. |
| Discharge Required | Whether the controller is requesting peak-protection discharge; this is not derived from the signed setpoint. |
| PI Controller Active | Whether the PI controller's discharge state is active. |
| Grid Charging Blocked This Quarter | Whether a discharge has started in this quarter-hour and grid charging is therefore blocked. |

Sensors can be unavailable if their required input measurements are unavailable.
The binary sensors can also be unavailable when the coordinator has no current
data.

## Virtual Anker device

PeakPilot also exposes three read-only sensors grouped as a separate
**Anker SOLIX Solarbank Max AC** virtual device. Their enum states match the
official integration's control values:

| Sensor | Values / unit | Behavior |
| --- | --- | --- |
| Operating Mode | `third_party_control` | Keeps the virtual battery under explicit setpoint control. |
| Grid Power | `charge`, `discharge` | Mirrors the direction of PeakGuard's signed setpoint when enabled; otherwise `charge` with zero power. |
| Power | W | Absolute PeakGuard setpoint, or 0 W while EVCC mode is `hold` or SoC is at/above **Maximum Charging SoC**. |

At zero power, third-party control prevents both charging and discharging.
This virtual device reports controller state only; it does not communicate
with or control an Anker battery.

## Virtual EVCC battery

PeakPilot exposes an EVCC-compatible virtual battery device with **State of
Charge** and **Power** sensors. These mirror the configured battery sensors;
power uses EVCC's convention of positive = discharging and negative =
charging. The **EVCC Battery Mode** select accepts `normal` and `hold`.

EVCC's Home Assistant battery template uses `modeNormal` and `modeHold` script
entities for battery commands. PeakPilot provides both scripts in
`custom_components/peak_guard/evcc_scripts.yaml`. Load them as a Home Assistant
package by adding this under the existing `homeassistant:` section of
`configuration.yaml`:

```yaml
homeassistant:
  packages:
    peak_guard_evcc: !include custom_components/peak_guard/evcc_scripts.yaml
```

If you already configure packages, add the `peak_guard_evcc` entry to that
existing mapping. Then reload scripts (or restart Home Assistant) and select
`script.peak_guard_evcc_normal` for EVCC's **Normal Mode Script** and
`script.peak_guard_evcc_hold` for **Hold Mode Script**. In `hold`, Peak Guard
sets battery power to zero, blocking both charging and discharging. Returning
to `normal` restores regular peak protection and charging behavior.

The scripts target `select.peak_guard_evcc_battery_mode`. If you change that
entity's ID in Home Assistant, update the target in `evcc_scripts.yaml` too.

The virtual battery does not control the inverter directly. Peak Guard
continues to expose its signed setpoint for a separate battery-control
automation or integration.

## Runtime configuration numbers

These number entities can be changed in Home Assistant. Defaults and allowed
ranges are shown below.

| Entity | Default | Range / step | Purpose |
| --- | ---: | --- | --- |
| Target Peak | 3.5 kW | 0.1–20 kW / 0.1 | Quarter-hour peak target. |
| PI Proportional Gain | 0.5 | 0–5 / 0.05 | Proportional response to peak error. |
| PI Integral Gain | 0.01 | 0–0.2 / 0.001 | Integral response to sustained peak error. |
| Battery Activation Threshold | 300 W | 0–5000 W / 50 | Error needed to activate discharge; a charging-mode interruption or immediate peak excursion can bypass the normal minimum-off delay. |
| Battery Deactivation Threshold | 100 W | 0–3000 W / 50 | Negative error threshold used when considering discharge deactivation. |
| Battery Power Ramp Rate | 200 W/s | 1–5000 W/s / 25 | Limits normal changes in discharge and charge setpoints. |
| Minimum Battery On Time | 120 s | 0–900 s / 10 | Minimum time before the controller may deactivate after starting. |
| Minimum Battery Off Time | 120 s | 0–900 s / 10 | Normal delay before starting after stopping; urgent peak protection can force activation. |
| Grid Power Filter Time | 5 s | 0–60 s / 1 | Smoothing time for grid power in the PI controller. |
| PI Anti-windup Tracking Time | 15 s | 1–120 s / 1 | Back-calculation tracking time; smaller values correct integral windup faster. |
| Export Safety Margin | 150 W | 0–1000 W / 10 | Consumption margin retained when calculating safe discharge. |
| Grid Charging Margin | 200 W | 0–1000 W / 10 | Headroom kept below the target peak while grid charging. |
| Maximum Grid Charge Power | Battery maximum charging power | 0–20000 W / 100 | Additional cap for grid charging only; the effective grid limit is the lower of this value and the battery maximum configured above. |
| Grid Charging SoC Limit | 60% | 0–100% / 1 | Grid charging is not selected at or above this SoC. |
| Maximum Charging SoC | 80% | 0–100% / 1 | Controlled charging is not selected at or above this SoC. |
| Switch SOC threshold | 20% | 0–100% / 1 | Legacy setting entity; currently not used by the active PI/mode-selection logic. |

Controller settings are persisted in the Home Assistant config entry. The
**Switch SOC threshold** is retained for compatibility but does not currently
affect the active controller; use **Minimum SoC** in the integration
configuration for the active discharge reserve.
