
import math
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Metro Care Hospital DSS",
    page_icon="🏥",
    layout="wide",
)

# ============================================================
# METRO CARE HOSPITAL DSS
# Beginner-friendly interactive decision-support simulation
# ============================================================

BASE = {
    "morning_arrivals": 85,
    "evening_arrivals": 120,
    "night_arrivals": 65,
    "morning_acuity": 0.22,
    "evening_acuity": 0.28,
    "night_acuity": 0.30,
    "bed_hr_m": 2.1,
    "bed_hr_e": 2.5,
    "bed_hr_n": 2.7,
    "doc_capacity": 18,
    "nurse_capacity": 12,
    "tech_capacity": 30,
    "doc_cost": 9000,
    "nurse_cost": 4500,
    "tech_cost": 3500,
    "doc_ot_cost": 13500,
    "nurse_ot_cost": 6500,
    "tech_ot_cost": 5000,
    "doctors": 16,
    "nurses": 28,
    "techs": 10,
    "current_beds": 34,
    "max_beds": 44,
    "bed_cost": 1500,
    "img_base": 52,
    "img_add": 10,
    "img_cost": 18000,
    "lab_base": 95,
    "lab_add": 20,
    "lab_cost": 12000,
    "pen_uncovered": 6000,
    "pen_diverted": 9500,
    "divert_share": 0.30,
    "shift_hours": 8,
    "ot_cap": 0.25,
}


def ceil_div(a, b):
    if b <= 0:
        return 0
    return math.ceil(a / b)


def calculate(p):
    """Calculate scenario outputs from the values selected in the sidebar."""

    incident_multiplier = (
        1 + p["incident_severity"] if p["incident_on"] else 1
    )

    arrivals = {
        "Morning": p["morning_arrivals"],
        "Evening": p["evening_arrivals"],
        "Night": p["night_arrivals"],
    }

    if p["incident_on"]:
        arrivals[p["incident_shift"]] *= incident_multiplier

    acuity = {
        "Morning": BASE["morning_acuity"],
        "Evening": BASE["evening_acuity"],
        "Night": BASE["night_acuity"],
    }

    bed_hours_per_patient = {
        "Morning": BASE["bed_hr_m"],
        "Evening": BASE["bed_hr_e"],
        "Night": BASE["bed_hr_n"],
    }

    # Effective staffing after optional absence/unavailability.
    avail_doc = (
        p["doctors"]
        * (1 - p["doc_absence"])
        * (0 if p["doc_unavailable"] else 1)
    )
    avail_nurse = (
        p["nurses"]
        * (1 - p["nurse_absence"])
        * (0 if p["nurse_unavailable"] else 1)
    )
    avail_tech = (
        p["techs"]
        * (1 - p["tech_absence"])
        * (0 if p["tech_unavailable"] else 1)
    )

    staff_rows = []
    total_labor = 0
    unmet_staff = {"Doctor": 0, "Nurse": 0, "Technician": 0}

    roles = [
        (
            "Doctor",
            avail_doc,
            BASE["doc_capacity"],
            BASE["doc_cost"],
            BASE["doc_ot_cost"],
        ),
        (
            "Nurse",
            avail_nurse,
            BASE["nurse_capacity"],
            BASE["nurse_cost"],
            BASE["nurse_ot_cost"],
        ),
        (
            "Technician",
            avail_tech,
            BASE["tech_capacity"],
            BASE["tech_cost"],
            BASE["tech_ot_cost"],
        ),
    ]

    for role, available, capacity, regular_cost, overtime_cost in roles:
        requirements = []

        for shift in ("Morning", "Evening", "Night"):
            demand = arrivals[shift]

            if role == "Doctor":
                demand = demand * (1 + 0.5 * acuity[shift])

            required = ceil_div(p["service_target"] * demand, capacity)

            if role == "Technician":
                required = max(required, 2)

            requirements.append((shift, demand, required))

        total_required = sum(item[2] for item in requirements)
        regular_available = math.floor(available)
        regular_used = min(total_required, regular_available)

        allocations = {}
        remaining = regular_used

        for index, (shift, demand, required) in enumerate(requirements):
            if index == len(requirements) - 1:
                allocation = remaining
            else:
                if total_required:
                    allocation = round(regular_used * required / total_required)
                else:
                    allocation = 0
                allocation = min(allocation, remaining)

            allocations[shift] = allocation
            remaining -= allocation

        for shift, demand, required in requirements:
            regular = allocations[shift]

            max_overtime = math.floor(p["ot_cap"] * regular)
            shortage_before_ot = max(0, required - regular)
            overtime = min(shortage_before_ot, max_overtime)
            unmet = max(0, required - regular - overtime)

            total_labor += (
                regular * regular_cost + overtime * overtime_cost
            )
            unmet_staff[role] += unmet

            staff_rows.append(
                {
                    "Shift": shift,
                    "Role": role,
                    "Required staff": required,
                    "Regular staff": regular,
                    "Overtime staff": overtime,
                    "Unmet staff": unmet,
                }
            )

    # --------------------------------------------------------
    # Beds
    # --------------------------------------------------------
    beds_total = p["current_beds"] + p["beds_added"]
    bed_rows = []
    total_bed_unmet = 0

    for shift in ("Morning", "Evening", "Night"):
        arrivals_this_shift = arrivals[shift]
        available_bed_hours = beds_total * BASE["shift_hours"]
        required_bed_hours = (
            p["service_target"]
            * arrivals_this_shift
            * bed_hours_per_patient[shift]
        )

        patient_capacity = (
            available_bed_hours / bed_hours_per_patient[shift]
        )

        unmet = max(
            0,
            p["service_target"] * arrivals_this_shift - patient_capacity,
        )
        total_bed_unmet += unmet

        bed_rows.append(
            {
                "Shift": shift,
                "Arrivals": round(arrivals_this_shift, 1),
                "Bed capacity (patients)": round(patient_capacity, 1),
                "Bed-hours available": round(available_bed_hours, 1),
                "Bed-hours needed": round(required_bed_hours, 1),
                "Unmet patients": round(unmet, 1),
            }
        )

    # --------------------------------------------------------
    # Diagnostics
    # --------------------------------------------------------
    diagnostic_rows = []
    total_imaging_shortfall = 0
    total_lab_shortfall = 0

    for shift in ("Morning", "Evening", "Night"):
        arrivals_this_shift = arrivals[shift]

        imaging_demand = (
            p["service_target"]
            * arrivals_this_shift
            * acuity[shift]
        )
        imaging_capacity = (
            BASE["img_base"]
            + (BASE["img_add"] if p["expand_imaging"] else 0)
        )

        lab_demand = p["service_target"] * arrivals_this_shift
        lab_capacity = (
            BASE["lab_base"]
            + (BASE["lab_add"] if p["expand_lab"] else 0)
        )

        imaging_shortfall = max(0, imaging_demand - imaging_capacity)
        lab_shortfall = max(0, lab_demand - lab_capacity)

        total_imaging_shortfall += imaging_shortfall
        total_lab_shortfall += lab_shortfall

        diagnostic_rows.append(
            {
                "Shift": shift,
                "Imaging demand": round(imaging_demand, 1),
                "Imaging capacity": imaging_capacity,
                "Imaging shortfall": round(imaging_shortfall, 1),
                "Lab demand": round(lab_demand, 1),
                "Lab capacity": lab_capacity,
                "Lab shortfall": round(lab_shortfall, 1),
            }
        )

    total_arrivals = sum(arrivals.values())
    total_unmet = (
        sum(unmet_staff.values())
        + total_bed_unmet
        + total_imaging_shortfall
        + total_lab_shortfall
    )

    coverage = (
        max(0, 1 - total_unmet / total_arrivals)
        if total_arrivals
        else 1
    )

    capacity_cost = (
        p["beds_added"] * BASE["bed_cost"]
        + (BASE["img_cost"] if p["expand_imaging"] else 0)
        + (BASE["lab_cost"] if p["expand_lab"] else 0)
    )

    penalty_per_unmet = (
        BASE["pen_uncovered"] * (1 - BASE["divert_share"])
        + BASE["pen_diverted"] * BASE["divert_share"]
    )

    penalty_cost = total_unmet * penalty_per_unmet
    total_cost = total_labor + capacity_cost + penalty_cost

    return {
        "total_cost": total_cost,
        "labor_cost": total_labor,
        "capacity_cost": capacity_cost,
        "penalty_cost": penalty_cost,
        "coverage": coverage,
        "unmet": total_unmet,
        "arrivals": total_arrivals,
        "beds_total": beds_total,
        "staff": pd.DataFrame(staff_rows),
        "beds": pd.DataFrame(bed_rows),
        "diagnostics": pd.DataFrame(diagnostic_rows),
        "available_staff": {
            "Doctors": avail_doc,
            "Nurses": avail_nurse,
            "Technicians": avail_tech,
        },
    }


# ============================================================
# Sidebar controls
# ============================================================

st.title("🏥 Metro Care Hospital — Decision Support System")
st.write(
    "Use the controls on the left to test hospital operating scenarios. "
    "The dashboard recalculates cost, staffing, beds and capacity."
)

with st.sidebar:
    st.header("Scenario controls")

    st.subheader("1. Patient demand")

    morning = st.slider(
        "Morning arrivals",
        min_value=40,
        max_value=160,
        value=BASE["morning_arrivals"],
        step=1,
    )

    evening = st.slider(
        "Evening arrivals",
        min_value=60,
        max_value=200,
        value=BASE["evening_arrivals"],
        step=1,
    )

    night = st.slider(
        "Night arrivals",
        min_value=30,
        max_value=120,
        value=BASE["night_arrivals"],
        step=1,
    )

    st.subheader("2. Staffing")

    doctors = st.slider(
        "Doctors available",
        min_value=4,
        max_value=24,
        value=BASE["doctors"],
        step=1,
    )

    nurses = st.slider(
        "Nurses available",
        min_value=8,
        max_value=40,
        value=BASE["nurses"],
        step=1,
    )

    technicians = st.slider(
        "Technicians available",
        min_value=3,
        max_value=16,
        value=BASE["techs"],
        step=1,
    )

    st.subheader("3. Beds and service")

    st.write("Current beds: 34")
    current_beds = BASE["current_beds"]

    beds_added = st.slider(
        "Additional beds",
        min_value=0,
        max_value=10,
        value=0,
        step=1,
    )
    st.caption(f"Total beds after expansion: {current_beds + beds_added}")

    service_target = st.slider(
        "Service target",
        min_value=0.80,
        max_value=0.99,
        value=0.95,
        step=0.01,
    )
    st.caption(f"Service target: {service_target:.0%}")

    overtime_cap = st.slider(
        "Overtime cap",
        min_value=0.00,
        max_value=0.50,
        value=BASE["ot_cap"],
        step=0.05,
    )
    st.caption(f"Overtime cap: {overtime_cap:.0%}")

    st.subheader("4. Incident")

    incident_on = st.checkbox(
        "Incident happening today?",
        value=False,
    )

    incident_shift = st.selectbox(
        "Incident shift",
        options=["Morning", "Evening", "Night"],
        index=1,
        disabled=not incident_on,
    )

    incident_severity = st.slider(
        "Incident arrival increase",
        min_value=0.00,
        max_value=1.00,
        value=0.35,
        step=0.05,
        disabled=not incident_on,
    )
    st.caption(
        f"Incident increase: {incident_severity:.0%}"
        if incident_on
        else "Incident is currently off"
    )

    st.subheader("5. Operational stress tests")

    expand_imaging = st.checkbox(
        "Expand imaging capacity",
        value=False,
    )

    expand_lab = st.checkbox(
        "Expand laboratory capacity",
        value=False,
    )

    doctor_absence = st.slider(
        "Doctor extra absence",
        min_value=0.00,
        max_value=0.30,
        value=0.00,
        step=0.01,
    )
    st.caption(f"Doctor absence: {doctor_absence:.0%}")

    nurse_absence = st.slider(
        "Nurse extra absence",
        min_value=0.00,
        max_value=0.30,
        value=0.00,
        step=0.01,
    )
    st.caption(f"Nurse absence: {nurse_absence:.0%}")

    technician_absence = st.slider(
        "Technician extra absence",
        min_value=0.00,
        max_value=0.30,
        value=0.00,
        step=0.01,
    )
    st.caption(f"Technician absence: {technician_absence:.0%}")

    doctor_unavailable = st.checkbox(
        "Doctors entirely unavailable",
        value=False,
    )

    nurse_unavailable = st.checkbox(
        "Nurses entirely unavailable",
        value=False,
    )

    technician_unavailable = st.checkbox(
        "Technicians entirely unavailable",
        value=False,
    )


params = {
    "morning_arrivals": morning,
    "evening_arrivals": evening,
    "night_arrivals": night,
    "doctors": doctors,
    "nurses": nurses,
    "techs": technicians,
    "current_beds": current_beds,
    "beds_added": beds_added,
    "service_target": service_target,
    "ot_cap": overtime_cap,
    "incident_on": incident_on,
    "incident_shift": incident_shift,
    "incident_severity": incident_severity,
    "expand_imaging": expand_imaging,
    "expand_lab": expand_lab,
    "doc_absence": doctor_absence,
    "nurse_absence": nurse_absence,
    "tech_absence": technician_absence,
    "doc_unavailable": doctor_unavailable,
    "nurse_unavailable": nurse_unavailable,
    "tech_unavailable": technician_unavailable,
}

# ============================================================
# Baseline scenario for comparison
# ============================================================

baseline_params = {
    "morning_arrivals": BASE["morning_arrivals"],
    "evening_arrivals": BASE["evening_arrivals"],
    "night_arrivals": BASE["night_arrivals"],
    "doctors": BASE["doctors"],
    "nurses": BASE["nurses"],
    "techs": BASE["techs"],
    "current_beds": BASE["current_beds"],
    "beds_added": 0,
    "service_target": 0.95,
    "ot_cap": BASE["ot_cap"],
    "incident_on": False,
    "incident_shift": "Evening",
    "incident_severity": 0.35,
    "expand_imaging": False,
    "expand_lab": False,
    "doc_absence": 0,
    "nurse_absence": 0,
    "tech_absence": 0,
    "doc_unavailable": False,
    "nurse_unavailable": False,
    "tech_unavailable": False,
}

result = calculate(params)
baseline = calculate(baseline_params)

# ============================================================
# Dashboard
# ============================================================

st.subheader("Dashboard")

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Total daily cost",
    f"₹{result['total_cost']:,.0f}",
    f"₹{result['total_cost'] - baseline['total_cost']:,.0f} vs baseline",
)

col2.metric(
    "Arrival coverage",
    f"{result['coverage']:.1%}",
    f"{result['coverage'] - baseline['coverage']:+.1%}",
)

col3.metric(
    "Beds available",
    f"{result['beds_total']}",
    f"+{beds_added} added",
)

col4.metric(
    "Estimated unmet demand",
    f"{result['unmet']:.1f}",
    f"{result['unmet'] - baseline['unmet']:+.1f} vs baseline",
)

if incident_on:
    st.warning(
        f"Incident scenario active: {incident_shift} shift, "
        f"{incident_severity:.0%} increase in arrivals."
    )
else:
    st.success("Normal operating scenario — no incident selected.")

# Cost chart
left, right = st.columns(2)

with left:
    st.markdown("### Cost breakdown")

    cost_df = pd.DataFrame(
        {
            "Component": [
                "Labor",
                "Beds / diagnostics",
                "Shortage penalty",
            ],
            "Cost": [
                result["labor_cost"],
                result["capacity_cost"],
                result["penalty_cost"],
            ],
        }
    )

    fig_cost = px.bar(
        cost_df,
        x="Component",
        y="Cost",
        title="Daily cost by component",
    )
    st.plotly_chart(fig_cost, use_container_width=True)

with right:
    st.markdown("### Capacity constraints")

    unmet_df = pd.DataFrame(
        {
            "Area": [
                "Doctors",
                "Nurses",
                "Technicians",
                "Beds",
                "Imaging",
                "Lab",
            ],
            "Unmet": [
                result["staff"].query("Role == 'Doctor'")[
                    "Unmet staff"
                ].sum(),
                result["staff"].query("Role == 'Nurse'")[
                    "Unmet staff"
                ].sum(),
                result["staff"].query("Role == 'Technician'")[
                    "Unmet staff"
                ].sum(),
                result["beds"]["Unmet patients"].sum(),
                result["diagnostics"]["Imaging shortfall"].sum(),
                result["diagnostics"]["Lab shortfall"].sum(),
            ],
        }
    )

    fig_unmet = px.bar(
        unmet_df,
        x="Area",
        y="Unmet",
        title="Estimated unmet demand by area",
    )
    st.plotly_chart(fig_unmet, use_container_width=True)

# Tables
st.markdown("### Staffing plan")
st.dataframe(
    result["staff"],
    use_container_width=True,
    hide_index=True,
)

st.markdown("### Bed capacity")
st.dataframe(
    result["beds"],
    use_container_width=True,
    hide_index=True,
)

st.markdown("### Diagnostic capacity")
st.dataframe(
    result["diagnostics"],
    use_container_width=True,
    hide_index=True,
)

st.markdown("### Scenario inputs")

inputs = pd.DataFrame(
    [
        ["Morning arrivals", morning],
        ["Evening arrivals", evening],
        ["Night arrivals", night],
        ["Doctors available", doctors],
        ["Nurses available", nurses],
        ["Technicians available", technicians],
        ["Existing beds", current_beds],
        ["Additional beds", beds_added],
        ["Service target", f"{service_target:.0%}"],
        ["Overtime cap", f"{overtime_cap:.0%}"],
        ["Incident", "Yes" if incident_on else "No"],
        ["Incident shift", incident_shift if incident_on else "—"],
        [
            "Incident severity",
            f"{incident_severity:.0%}" if incident_on else "—",
        ],
        ["Imaging expansion", "Yes" if expand_imaging else "No"],
        ["Lab expansion", "Yes" if expand_lab else "No"],
        ["Doctor absence", f"{doctor_absence:.0%}"],
        ["Nurse absence", f"{nurse_absence:.0%}"],
        ["Technician absence", f"{technician_absence:.0%}"],
    ],
    columns=["Variable", "Value"],
)

st.dataframe(
    inputs,
    use_container_width=True,
    hide_index=True,
)

st.caption(
    "Decision-support simulation based on the supplied Metro Care Hospital "
    "workbook. Validate assumptions and formulas against your project "
    "requirements before final submission."
)
