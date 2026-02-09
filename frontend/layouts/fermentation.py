"""Fermentation dashboard layout — 7 KL fermentor monitoring and control."""

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_fermentation_layout():
    return dbc.Container(
        [
            # Title row
            dbc.Row(
                dbc.Col(
                    html.H3("Fermentation Digital Twin — 7 KL", className="text-center mb-3"),
                ),
            ),

            # KPI Cards Row
            dbc.Row(
                [
                    # Fermentor State
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("KF-7KL Fermentor"),
                                dbc.CardBody(
                                    [
                                        html.Div(id="ferm-ph", children="pH: --"),
                                        html.Div(id="ferm-do", children="DO: -- mg/L"),
                                        html.Div(id="ferm-temp", children="Temp: -- °C"),
                                        html.Div(id="ferm-biomass", children="Biomass: -- g/L"),
                                        html.Div(id="ferm-substrate", children="Substrate: -- g/L"),
                                        html.Div(id="ferm-volume", children="Volume: -- L"),
                                        html.Div(id="ferm-rpm", children="RPM: --"),
                                    ]
                                ),
                            ],
                            color="dark",
                            outline=True,
                        ),
                        md=4,
                    ),

                    # Anomaly Detection Panel
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("Anomaly Detection"),
                                dbc.CardBody(
                                    [
                                        html.Div(
                                            id="ferm-alert-status",
                                            children="Status: NORMAL",
                                            className="text-success fw-bold",
                                        ),
                                        html.Div(id="ferm-alert-detail", children="No alerts"),
                                        html.Hr(),
                                        html.Div(id="ferm-scenario-phase", children="Scenario: --"),
                                        html.Div(id="ferm-scenario-event", children="Last event: --"),
                                    ]
                                ),
                            ],
                            color="dark",
                            outline=True,
                        ),
                        md=4,
                    ),

                    # Control Panel
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("Manual Controls"),
                                dbc.CardBody(
                                    [
                                        dbc.Button(
                                            "Start Simulation",
                                            id="ferm-btn-start",
                                            color="success",
                                            className="me-2 mb-2",
                                            size="sm",
                                        ),
                                        dbc.Button(
                                            "Stop",
                                            id="ferm-btn-stop",
                                            color="danger",
                                            className="me-2 mb-2",
                                            size="sm",
                                        ),
                                        html.Hr(),
                                        dbc.Button(
                                            "Dose Alkali (NaOH)",
                                            id="ferm-btn-base",
                                            color="warning",
                                            className="me-2 mb-2",
                                            size="sm",
                                        ),
                                        dbc.Button(
                                            "Dose Acid (HCl)",
                                            id="ferm-btn-acid",
                                            color="info",
                                            className="me-2 mb-2",
                                            size="sm",
                                        ),
                                        html.Hr(),
                                        html.Div(id="ferm-dosing-status", children="Dosing: idle"),
                                    ]
                                ),
                            ],
                            color="dark",
                            outline=True,
                        ),
                        md=4,
                    ),
                ],
                className="mb-3",
            ),

            # Trend Charts Row
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Graph(
                            id="ferm-ph-trend",
                            config={"displayModeBar": False},
                            style={"height": "300px"},
                        ),
                        md=6,
                    ),
                    dbc.Col(
                        dcc.Graph(
                            id="ferm-do-trend",
                            config={"displayModeBar": False},
                            style={"height": "300px"},
                        ),
                        md=6,
                    ),
                ],
                className="mb-3",
            ),

            dbc.Row(
                [
                    dbc.Col(
                        dcc.Graph(
                            id="ferm-biomass-trend",
                            config={"displayModeBar": False},
                            style={"height": "300px"},
                        ),
                        md=6,
                    ),
                    dbc.Col(
                        dcc.Graph(
                            id="ferm-temp-trend",
                            config={"displayModeBar": False},
                            style={"height": "300px"},
                        ),
                        md=6,
                    ),
                ],
            ),

            # Hidden stores for state
            dcc.Store(id="ferm-simulation-id"),
            dcc.Store(id="ferm-ph-history", data={"time": [], "values": []}),
            dcc.Store(id="ferm-do-history", data={"time": [], "values": []}),
            dcc.Store(id="ferm-biomass-history", data={"time": [], "values": []}),
            dcc.Store(id="ferm-temp-history", data={"time": [], "values": []}),
        ],
        fluid=True,
    )
