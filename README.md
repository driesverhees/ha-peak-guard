# ha-peak-guard

# PI anti-windup implementation

PeakPIController uses back-calculation anti-windup.

The unconstrained PI output is calculated first. The output is then
constrained by the battery discharge limit and the ramp-rate limiter.
The integrator is updated using:

    dI/dt = Ki * error + (limited_setpoint - raw_PI_output) / Tt

`limited_setpoint` includes both the power saturation and ramp limit.
`Tt` is configurable in Home Assistant as **PI Anti-windup Tracking Time**.
The default is 15 seconds.

A smaller tracking time unwinds the integral more aggressively; a larger
value makes the correction slower. Start at 15 seconds and tune only after
observing `pi_raw_output_w`, `pi_integral_w`, and `battery_setpoint_w`.

Note: the limited output here is the achievable commanded setpoint, not
measured physical battery power. The controller does not currently receive
battery discharge power feedback.

# Export prevention

PeakPilot requires a configurable battery-power sensor in the integration setup.
The sign convention is configurable too:

- **Positive = discharging** (default)
- **Positive = charging**

Power sensors with units W or kW are converted to watts.

The export-safe maximum discharge is calculated as:

`max(0, grid_import_w + measured_battery_discharge_w - export_safety_margin_w)`

Grid import and battery discharge are positive. The configurable export safety
margin defaults to 150 W and is available as a Home Assistant number entity.
The limit is applied after the normal ramp limiter, so it can force an immediate
setpoint reduction when the safe discharge ceiling drops. Back-calculation uses
that final constrained setpoint.

If the battery-power sensor is missing, unavailable, or has an unsupported unit,
PeakPilot inhibits the controller rather than assuming additional discharge is safe.
