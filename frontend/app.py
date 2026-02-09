"""BIO - Plotly Dash Frontend Application.

Main dashboard for biomass/biogas power plant monitoring and training.
"""

import dash
from dash import html, dcc
import dash_bootstrap_components as dbc

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
    title="BIO - Biomass/Biogas Plant Simulator",
)

app.layout = dbc.Container(
    [
        # Header
        dbc.Navbar(
            dbc.Container(
                [
                    dbc.NavbarBrand("BIO Plant Simulator", className="ms-2"),
                    dbc.Nav(
                        [
                            dbc.NavItem(dbc.NavLink("Monitoring", href="/", active="exact")),
                            dbc.NavItem(dbc.NavLink("Fermentation", href="/fermentation")),
                            dbc.NavItem(dbc.NavLink("Training", href="/training")),
                            dbc.NavItem(dbc.NavLink("Maintenance", href="/maintenance")),
                        ],
                        navbar=True,
                    ),
                ],
            ),
            color="primary",
            dark=True,
        ),

        # Page content
        dcc.Location(id="url", refresh=False),
        html.Div(id="page-content", className="mt-3"),

        # Real-time update interval
        dcc.Interval(id="interval-component", interval=1000, n_intervals=0),
    ],
    fluid=True,
)

server = app.server

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
