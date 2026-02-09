"""Dash callbacks for fermentation dashboard — API calls and chart updates."""

import requests
from dash import Input, Output, State, callback, no_update
import plotly.graph_objects as go

API_BASE = "http://localhost:8000/api/v1/fermentation"
MAX_HISTORY = 600  # 10 minutes at 1 Hz


def _make_trend(times, values, title, yaxis_title, color="#9ACD32"):
    """Create a simple line chart figure."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times, y=values,
        mode="lines",
        line=dict(color=color, width=2),
    ))
    fig.update_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title=yaxis_title,
        template="plotly_dark",
        margin=dict(l=50, r=20, t=40, b=40),
        height=300,
    )
    return fig


def register_callbacks(app):
    """Register all fermentation callbacks with the Dash app."""

    @app.callback(
        Output("ferm-simulation-id", "data"),
        Input("ferm-btn-start", "n_clicks"),
        prevent_initial_call=True,
    )
    def start_simulation(n_clicks):
        if not n_clicks:
            return no_update
        try:
            resp = requests.post(f"{API_BASE}/start", json={"mode": "single_7kl"}, timeout=5)
            data = resp.json()
            return str(data.get("id", ""))
        except Exception:
            return no_update

    @app.callback(
        Output("ferm-btn-stop", "disabled"),
        Input("ferm-btn-stop", "n_clicks"),
        State("ferm-simulation-id", "data"),
        prevent_initial_call=True,
    )
    def stop_simulation(n_clicks, sim_id):
        if not n_clicks or not sim_id:
            return no_update
        try:
            requests.post(f"{API_BASE}/{sim_id}/stop", timeout=5)
        except Exception:
            pass
        return False

    @app.callback(
        Output("ferm-dosing-status", "children"),
        [Input("ferm-btn-base", "n_clicks"),
         Input("ferm-btn-acid", "n_clicks")],
        State("ferm-simulation-id", "data"),
        prevent_initial_call=True,
    )
    def dose_control(base_clicks, acid_clicks, sim_id):
        if not sim_id:
            return "No simulation running"
        from dash import ctx
        triggered = ctx.triggered_id
        try:
            if triggered == "ferm-btn-base":
                requests.post(
                    f"{API_BASE}/{sim_id}/control",
                    json={"start_base_dosing": True},
                    timeout=5,
                )
                return "Dosing: alkali started"
            elif triggered == "ferm-btn-acid":
                requests.post(
                    f"{API_BASE}/{sim_id}/control",
                    json={"start_acid_dosing": True},
                    timeout=5,
                )
                return "Dosing: acid started"
        except Exception:
            return "Dosing: API error"
        return no_update

    @app.callback(
        [
            Output("ferm-ph", "children"),
            Output("ferm-do", "children"),
            Output("ferm-temp", "children"),
            Output("ferm-biomass", "children"),
            Output("ferm-substrate", "children"),
            Output("ferm-volume", "children"),
            Output("ferm-rpm", "children"),
            Output("ferm-ph-trend", "figure"),
            Output("ferm-do-trend", "figure"),
            Output("ferm-biomass-trend", "figure"),
            Output("ferm-temp-trend", "figure"),
            Output("ferm-ph-history", "data"),
            Output("ferm-do-history", "data"),
            Output("ferm-biomass-history", "data"),
            Output("ferm-temp-history", "data"),
        ],
        Input("interval-component", "n_intervals"),
        [
            State("ferm-simulation-id", "data"),
            State("ferm-ph-history", "data"),
            State("ferm-do-history", "data"),
            State("ferm-biomass-history", "data"),
            State("ferm-temp-history", "data"),
        ],
    )
    def update_state(n, sim_id, ph_hist, do_hist, bio_hist, temp_hist):
        empty_fig = go.Figure().update_layout(template="plotly_dark", height=300)
        defaults = (
            "pH: --", "DO: --", "Temp: --", "Biomass: --",
            "Substrate: --", "Volume: --", "RPM: --",
            empty_fig, empty_fig, empty_fig, empty_fig,
            ph_hist, do_hist, bio_hist, temp_hist,
        )

        if not sim_id:
            return defaults

        try:
            resp = requests.get(f"{API_BASE}/{sim_id}/state", timeout=5)
            data = resp.json()
        except Exception:
            return defaults

        fermentors = data.get("fermentors", {})
        ferm = fermentors.get("KF-7KL", {})
        if not ferm:
            return defaults

        t = data.get("simulation_time", 0)
        ph = ferm.get("pH", 0)
        do_val = ferm.get("DO", 0)
        temp = ferm.get("temperature", 0)
        biomass = ferm.get("X", 0)
        substrate = ferm.get("S", 0)
        volume = ferm.get("volume_L", 0)
        rpm = ferm.get("rpm", 0)

        # Update histories
        for hist, val in [
            (ph_hist, ph), (do_hist, do_val), (bio_hist, biomass), (temp_hist, temp)
        ]:
            hist["time"].append(t)
            hist["values"].append(val)
            if len(hist["time"]) > MAX_HISTORY:
                hist["time"] = hist["time"][-MAX_HISTORY:]
                hist["values"] = hist["values"][-MAX_HISTORY:]

        return (
            f"pH: {ph:.2f}",
            f"DO: {do_val:.2f} mg/L",
            f"Temp: {temp:.1f} °C",
            f"Biomass: {biomass:.3f} g/L",
            f"Substrate: {substrate:.2f} g/L",
            f"Volume: {volume:.0f} L",
            f"RPM: {rpm:.0f}",
            _make_trend(ph_hist["time"], ph_hist["values"], "pH", "pH", "#FF6B6B"),
            _make_trend(do_hist["time"], do_hist["values"], "Dissolved Oxygen", "mg/L", "#4169E1"),
            _make_trend(bio_hist["time"], bio_hist["values"], "Biomass", "g/L", "#9ACD32"),
            _make_trend(temp_hist["time"], temp_hist["values"], "Temperature", "°C", "#FF4444"),
            ph_hist,
            do_hist,
            bio_hist,
            temp_hist,
        )
