"""Plant monitoring dashboard layout.

Real-time visualization of all plant subsystems:
- Digester status (temperature, pH, biogas flow)
- Engine/Boiler performance (power, efficiency)
- Steam cycle parameters
- Overall plant KPIs
"""

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_monitoring_layout():
    return dbc.Container(
        [
            dbc.Row(
                [
                    # Digester panel
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("Anaerobic Digester"),
                                dbc.CardBody(
                                    [
                                        html.Div(id="digester-temp", children="Temperature: -- C"),
                                        html.Div(id="digester-ph", children="pH: --"),
                                        html.Div(id="digester-biogas", children="Biogas Flow: -- Nm3/h"),
                                        html.Div(id="digester-ch4", children="CH4: -- %"),
                                    ]
                                ),
                            ],
                            color="dark",
                            outline=True,
                        ),
                        md=4,
                    ),

                    # Engine panel
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("Biogas Engine"),
                                dbc.CardBody(
                                    [
                                        html.Div(id="engine-power", children="Power: -- kW"),
                                        html.Div(id="engine-rpm", children="RPM: --"),
                                        html.Div(id="engine-eff", children="Efficiency: -- %"),
                                        html.Div(id="engine-exhaust", children="Exhaust: -- C"),
                                    ]
                                ),
                            ],
                            color="dark",
                            outline=True,
                        ),
                        md=4,
                    ),

                    # Plant overview panel
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("Plant Overview"),
                                dbc.CardBody(
                                    [
                                        html.Div(id="plant-power", children="Total Power: -- kW"),
                                        html.Div(id="plant-thermal", children="Thermal: -- kW"),
                                        html.Div(id="plant-eff", children="CHP Efficiency: -- %"),
                                        html.Div(id="plant-status", children="Status: OFFLINE"),
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

            # Trend charts
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Graph(id="power-trend", config={"displayModeBar": False}),
                        md=6,
                    ),
                    dbc.Col(
                        dcc.Graph(id="digester-trend", config={"displayModeBar": False}),
                        md=6,
                    ),
                ]
            ),
        ],
        fluid=True,
    )
