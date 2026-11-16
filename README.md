# ha-peak-guard

# PI anti-windup implementation

PeakPIController now uses back-calculation anti-windup.

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
