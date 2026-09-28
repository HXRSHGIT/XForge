"""Circuit formulas, each carrying its provenance.

These are the calculations behind the safety rules: what a precharge resistor
must be, how much energy a contactor coil dumps into its driver, what bias
resistor makes a thermistor readable, how long an ADC front end takes to
settle.

Most are physics identities rather than anything a standards body owns, so
they are tier B: reproducible from first principles, checkable by hand. The
ones that are convention dressed as engineering - "3RC is enough precharge",
"bias the NTC at its 25 C resistance" - are tier D and say so, because a rule
must not fail a build on a rule of thumb.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from xforge.physics.formula import Formula, Tier, Variable, decorate, register

# Copper at 20 C. Verified against multiple independent sources.
RHO_CU_20C = 1.68e-8  # ohm-metre
ALPHA_CU = 0.00393  # per degC
KELVIN_0C = 273.15


class ElectricalError(ValueError):
    """The inputs cannot produce a meaningful answer."""


# ── conductor resistance ──────────────────────────────────────────────

RESISTANCE = register(
    Formula(
        id="conductor.resistance",
        name="Resistance of a conductor",
        equation="R = rho * L / A",
        variables=(
            Variable("R", "resistance", "ohm"),
            Variable("rho", "resistivity", "ohm.m"),
            Variable("L", "length", "m"),
            Variable("A", "cross-section", "m^2"),
        ),
        constants={"rho_Cu at 20 C": "1.68e-8 ohm.m"},
        source="Physics identity; copper resistivity is a measured constant",
        tier=Tier.PUBLIC_FORM,
        validity="DC or low frequency. Ignores skin effect and proximity effect.",
    )
)

RESISTANCE_TEMPCO = register(
    Formula(
        id="conductor.resistance_at_temp",
        name="Conductor resistance at temperature",
        equation="R(T) = R20 * (1 + alpha * (T - 20))",
        variables=(
            Variable("R(T)", "resistance at T", "ohm"),
            Variable("R20", "resistance at 20 C", "ohm"),
            Variable("T", "conductor temperature", "degC"),
        ),
        constants={"alpha_Cu": "0.00393 per degC"},
        source="Linear temperature-coefficient model for copper",
        tier=Tier.PUBLIC_FORM,
        validity="Linear approximation, good to a few hundred degrees C.",
        notes=(
            "Copper gains about 0.4% resistance per degree. On a 100 A path "
            "self-heating raises resistance, which raises heating - size for "
            "the hot resistance, not the 20 C one."
        ),
    )
)

JOULE = register(
    Formula(
        id="conductor.joule_heating",
        name="Power dissipated in a resistance",
        equation="P = I^2 * R",
        variables=(
            Variable("P", "power", "W"),
            Variable("I", "current", "A"),
            Variable("R", "resistance", "ohm"),
        ),
        source="Joule's first law",
        tier=Tier.PUBLIC_FORM,
    )
)


@decorate(RESISTANCE)
def conductor_resistance_ohm(
    length_mm: float, width_mm: float, copper_oz: float, temp_c: float = 20.0
) -> float:
    """Resistance of a rectangular trace, at temperature."""
    if min(length_mm, width_mm, copper_oz) <= 0:
        raise ElectricalError("length, width and copper weight must be positive")
    thickness_m = copper_oz * 34.8e-6  # 1 oz = 34.8 um
    area_m2 = (width_mm / 1000.0) * thickness_m
    r20 = RHO_CU_20C * (length_mm / 1000.0) / area_m2
    return r20 * (1 + ALPHA_CU * (temp_c - 20.0))


# ── precharge ─────────────────────────────────────────────────────────

PRECHARGE_TIME = register(
    Formula(
        id="precharge.time",
        name="Time for a precharge network to reach a bus-voltage fraction",
        equation="t = -R * C * ln(1 - Vf/Vpack)",
        variables=(
            Variable("t", "time to reach Vf", "s"),
            Variable("R", "precharge resistance", "ohm"),
            Variable("C", "downstream bulk capacitance", "F"),
            Variable("Vf", "target bus voltage", "V"),
            Variable("Vpack", "pack voltage", "V"),
        ),
        source="RC charging identity, V(t) = Vpack * (1 - exp(-t/RC))",
        tier=Tier.PUBLIC_FORM,
        validity=(
            "Constant pack voltage, linear capacitance, resistance constant "
            "over the event. Real precharge resistors heat and rise in value."
        ),
        notes=(
            "The common '3RC' rule reaches 95.0% and '5RC' reaches 99.3%. "
            "Those are conventions, not requirements - the requirement is "
            "whatever contactor-closing differential the design tolerates."
        ),
    )
)

PRECHARGE_ENERGY = register(
    Formula(
        id="precharge.energy",
        name="Energy dissipated per precharge event",
        equation="E = 0.5 * C * V^2",
        variables=(
            Variable("E", "energy into the resistor", "J"),
            Variable("C", "bulk capacitance", "F"),
            Variable("V", "pack voltage", "V"),
        ),
        source="Capacitor energy identity",
        tier=Tier.PUBLIC_FORM,
        validity=(
            "Independent of R: the resistor always absorbs one capacitor's "
            "worth of energy, however slowly. R is chosen for peak current "
            "and for the resistor's pulse rating, not to reduce this energy."
        ),
    )
)

PRECHARGE_PEAK = register(
    Formula(
        id="precharge.peak_current",
        name="Peak precharge inrush current",
        equation="I_peak = Vpack / R",
        variables=(
            Variable("I_peak", "initial current", "A"),
            Variable("Vpack", "pack voltage", "V"),
            Variable("R", "precharge resistance", "ohm"),
        ),
        source="Ohm's law at t=0, with the bus at zero volts",
        tier=Tier.PUBLIC_FORM,
    )
)


@dataclass(frozen=True)
class PrechargeSizing:
    resistance_ohm: float
    capacitance_f: float
    pack_v: float
    time_to_95pct_s: float
    energy_j: float
    peak_current_a: float

    def explain(self) -> str:
        return "\n".join(
            [
                PRECHARGE_TIME.explain(
                    R=f"{self.resistance_ohm} ohm",
                    C=f"{self.capacitance_f * 1e6:.0f} uF",
                    Vpack=f"{self.pack_v} V",
                ),
                "",
                PRECHARGE_ENERGY.explain(
                    C=f"{self.capacitance_f * 1e6:.0f} uF", V=f"{self.pack_v} V"
                ),
            ]
        )


def precharge_sizing(
    resistance_ohm: float, capacitance_f: float, pack_v: float
) -> PrechargeSizing:
    """Everything a review needs about a precharge network."""
    if min(resistance_ohm, capacitance_f, pack_v) <= 0:
        raise ElectricalError("R, C and pack voltage must be positive")
    tau = resistance_ohm * capacitance_f
    return PrechargeSizing(
        resistance_ohm=resistance_ohm,
        capacitance_f=capacitance_f,
        pack_v=pack_v,
        time_to_95pct_s=-tau * math.log(1 - 0.95),
        energy_j=0.5 * capacitance_f * pack_v**2,
        peak_current_a=pack_v / resistance_ohm,
    )


def precharge_resistance_for_time(
    target_s: float, capacitance_f: float, fraction: float = 0.95
) -> float:
    """The resistance that reaches *fraction* of pack voltage in *target_s*."""
    if not 0 < fraction < 1:
        raise ElectricalError("fraction must be between 0 and 1")
    if min(target_s, capacitance_f) <= 0:
        raise ElectricalError("time and capacitance must be positive")
    return target_s / (-math.log(1 - fraction) * capacitance_f)


# ── inductive loads ───────────────────────────────────────────────────

COIL_ENERGY = register(
    Formula(
        id="coil.energy",
        name="Energy stored in a coil",
        equation="E = 0.5 * L * I^2",
        variables=(
            Variable("E", "stored energy", "J"),
            Variable("L", "coil inductance", "H"),
            Variable("I", "coil current", "A"),
        ),
        source="Inductor energy identity",
        tier=Tier.PUBLIC_FORM,
        notes=(
            "This energy has to go somewhere when the driver opens. Without a "
            "clamp it goes into the driver's avalanche energy rating, or into "
            "an arc."
        ),
    )
)

FLYBACK_VOLTAGE = register(
    Formula(
        id="coil.flyback_voltage",
        name="Voltage across an opening inductive load",
        equation="V = L * dI/dt",
        variables=(
            Variable("V", "voltage across the coil", "V"),
            Variable("L", "coil inductance", "H"),
            Variable("dI/dt", "rate of current change", "A/s"),
        ),
        source="Faraday's law of induction",
        tier=Tier.PUBLIC_FORM,
        validity=(
            "Unbounded in the ideal case: a fast switch gives an arbitrarily "
            "large voltage. In practice it is limited by the driver's "
            "breakdown or by whatever clamps first, which is the point."
        ),
    )
)


def coil_energy_j(inductance_h: float, current_a: float) -> float:
    if inductance_h <= 0 or current_a <= 0:
        raise ElectricalError("inductance and current must be positive")
    return 0.5 * inductance_h * current_a**2


# ── thermistors ───────────────────────────────────────────────────────

NTC_BETA = register(
    Formula(
        id="ntc.beta",
        name="NTC resistance from the Beta equation",
        equation="R(T) = R0 * exp(B * (1/T - 1/T0))",
        variables=(
            Variable("R(T)", "resistance at T", "ohm"),
            Variable("R0", "resistance at reference temperature", "ohm"),
            Variable("B", "material constant", "K"),
            Variable("T", "temperature", "K"),
            Variable("T0", "reference temperature, usually 298.15", "K"),
        ),
        source="Beta-parameter NTC model, given on every NTC datasheet",
        tier=Tier.PUBLIC_FORM,
        validity=(
            "Accurate to roughly +/-1 C over a 50 C span around the reference. "
            "Over a wide range use Steinhart-Hart with three coefficients."
        ),
    )
)

NTC_BIAS = register(
    Formula(
        id="ntc.bias_resistor",
        name="Bias resistor for maximum divider sensitivity",
        equation="R_bias = R_ntc(T_mid)",
        variables=(
            Variable("R_bias", "divider resistor", "ohm"),
            Variable("R_ntc(T_mid)", "NTC resistance at the temperature of "
                     "most interest", "ohm"),
        ),
        source=(
            "Maximising d(Vout)/d(R_ntc) for a two-resistor divider; the "
            "derivative peaks where the two resistances are equal"
        ),
        tier=Tier.CONVENTION,
        validity=(
            "Maximises sensitivity at one temperature. If accuracy matters "
            "across a wide span, bias for the middle of that span instead, "
            "and check self-heating at the hot end."
        ),
    )
)


def ntc_resistance(
    beta_k: float, r0_ohm: float, temp_c: float, t0_c: float = 25.0
) -> float:
    """NTC resistance at a temperature, from the Beta model."""
    if beta_k <= 0 or r0_ohm <= 0:
        raise ElectricalError("beta and reference resistance must be positive")
    t_k = temp_c + KELVIN_0C
    t0_k = t0_c + KELVIN_0C
    if t_k <= 0:
        raise ElectricalError("temperature below absolute zero")
    return r0_ohm * math.exp(beta_k * (1 / t_k - 1 / t0_k))


def ntc_divider_voltage(
    supply_v: float, r_bias_ohm: float, r_ntc_ohm: float, ntc_low_side: bool = True
) -> float:
    """Divider output with the NTC on the low or high side."""
    total = r_bias_ohm + r_ntc_ohm
    if total <= 0:
        raise ElectricalError("resistances must be positive")
    return supply_v * (r_ntc_ohm if ntc_low_side else r_bias_ohm) / total


# ── analogue front end ────────────────────────────────────────────────

RC_CUTOFF = register(
    Formula(
        id="rc.cutoff",
        name="RC low-pass corner frequency",
        equation="f_c = 1 / (2 * pi * R * C)",
        variables=(
            Variable("f_c", "-3 dB corner", "Hz"),
            Variable("R", "series resistance", "ohm"),
            Variable("C", "shunt capacitance", "F"),
        ),
        source="Single-pole RC response",
        tier=Tier.PUBLIC_FORM,
    )
)

ADC_SETTLING = register(
    Formula(
        id="adc.settling",
        name="Settling time of an RC front end to N-bit accuracy",
        equation="t = R * C * N * ln(2)",
        variables=(
            Variable("t", "settling time", "s"),
            Variable("R", "series resistance", "ohm"),
            Variable("C", "capacitance", "F"),
            Variable("N", "resolution", "bits"),
        ),
        source="Solving exp(-t/RC) = 2^-N for t",
        tier=Tier.PUBLIC_FORM,
        validity=(
            "Applies to the sampling window of a SAR ADC. If the filter is "
            "slower than the acquisition time, the conversion reads the "
            "filter, not the signal."
        ),
    )
)

CLAMP_FAULT_CURRENT = register(
    Formula(
        id="adc.clamp_current",
        name="Fault current into an input clamp through a series resistor",
        equation="I = (V_fault - V_clamp) / R_series",
        variables=(
            Variable("I", "current into the clamp", "A"),
            Variable("V_fault", "worst-case applied voltage", "V"),
            Variable("V_clamp", "clamp voltage", "V"),
            Variable("R_series", "series protection resistance", "ohm"),
        ),
        source="Ohm's law across the series element under fault",
        tier=Tier.PUBLIC_FORM,
        notes=(
            "An MCU's internal ESD diodes are typically rated for only a few "
            "milliamps continuous. Size R_series so this current stays inside "
            "that, not just inside the external clamp's rating."
        ),
    )
)


def rc_cutoff_hz(r_ohm: float, c_f: float) -> float:
    if r_ohm <= 0 or c_f <= 0:
        raise ElectricalError("R and C must be positive")
    return 1.0 / (2 * math.pi * r_ohm * c_f)


def adc_settling_s(r_ohm: float, c_f: float, bits: int) -> float:
    if r_ohm <= 0 or c_f <= 0 or bits <= 0:
        raise ElectricalError("R, C and bit count must be positive")
    return r_ohm * c_f * bits * math.log(2)


def clamp_fault_current_a(
    fault_v: float, clamp_v: float, series_r_ohm: float
) -> float:
    if series_r_ohm <= 0:
        raise ElectricalError("series resistance must be positive")
    return max(0.0, (fault_v - clamp_v) / series_r_ohm)


# ── shunts and dividers ───────────────────────────────────────────────

SHUNT_POWER = register(
    Formula(
        id="shunt.power",
        name="Power dissipated in a current shunt",
        equation="P = I^2 * R_shunt",
        variables=(
            Variable("P", "dissipation", "W"),
            Variable("I", "measured current", "A"),
            Variable("R_shunt", "shunt resistance", "ohm"),
        ),
        source="Joule's first law",
        tier=Tier.PUBLIC_FORM,
        notes=(
            "Self-heating shifts the shunt's own resistance by its tempco, "
            "which is a gain error on the measurement. A 100 uohm shunt at "
            "200 A dissipates 4 W."
        ),
    )
)

DIVIDER_POWER = register(
    Formula(
        id="divider.power",
        name="Power in a high-voltage divider element",
        equation="P = V_element^2 / R_element",
        variables=(
            Variable("P", "dissipation per resistor", "W"),
            Variable("V_element", "voltage across that resistor", "V"),
            Variable("R_element", "its resistance", "ohm"),
        ),
        source="Joule's first law",
        tier=Tier.PUBLIC_FORM,
        notes=(
            "The reason an 800 V divider is a chain: a single chip resistor's "
            "working-voltage rating, typically 200-400 V for 0805, is "
            "exceeded long before its power rating is."
        ),
    )
)


def shunt_power_w(current_a: float, shunt_ohm: float) -> float:
    if shunt_ohm <= 0:
        raise ElectricalError("shunt resistance must be positive")
    return current_a**2 * shunt_ohm
