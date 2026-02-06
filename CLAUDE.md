# BIO Project - Claude Code Instructions

## Development Environment

### Conda Environment
- **Environment Name:** `bio_env`
- **Python Version:** 3.10

### How to Run Python Scripts
```bash
# Activate conda environment first
conda activate bio_env

# Or use full path
python <script.py>

# Examples:
python -m pytest tests/ -v
python -m uvicorn backend.main:app --reload
```

### Backend Server
- **URL:** http://localhost:8000
- **API Prefix:** /api/v1
- **Docs:** http://localhost:8000/docs

### Frontend Dashboard
- **URL:** http://localhost:8050
- **Framework:** Plotly Dash

### Unity Project
- **Path:** bio-Unity/
- **Unity Version:** Unity 6 LTS

## Project Structure
```
bio/
├── backend/           # FastAPI backend
├── simulation/        # Physics simulation (Biogas/Biomass)
├── frontend/          # Plotly Dash dashboard
├── database/          # SQLAlchemy models (PostgreSQL + TimescaleDB)
├── ai/                # AI/ML modules
├── tests/             # Test files
├── scripts/           # Utility scripts
├── data/              # Datasets
├── config/            # Configuration
├── docs/              # Documentation
└── bio-Unity/         # Unity 3D visualization
```

## Key Commands

### Start Backend Server
```bash
./BE.sh
# or
python -m uvicorn backend.main:app --reload
```

### Start Frontend
```bash
./FE.sh
# or
python frontend/app.py
```

### Run Tests
```bash
python -m pytest tests/ -v
```

### Docker
```bash
docker-compose up -d                    # Start DB + Backend
docker-compose --profile full up -d     # Start all services
```

## Domain: Biomass/Biogas Power Plant

### Plant Configurations
1. **Biogas Engine**: Anaerobic Digester -> Biogas Engine (CHP)
2. **Biomass Boiler**: Biomass Combustion -> Steam Turbine
3. **Combined**: Both systems integrated

### Physics Modules
- `anaerobic_digester.py` - ADM1-based biogas production model
- `biogas_engine.py` - Otto cycle gas engine (Jenbacher/CAT class)
- `biomass_boiler.py` - Grate-fired biomass combustion + steam
- `steam_cycle.py` - Rankine cycle steam turbine
- `feedstock.py` - Biomass/waste feedstock property database

### Color Coding (Unity/Dashboard)
| Flow Type | Color |
|-----------|-------|
| Biogas | Yellow-Green (#9ACD32) |
| Biomass Feed | Brown (#8B4513) |
| Steam | White (#F0F0F0) |
| Hot Water | Red (#FF4444) |
| Cooling Water | Blue (#4169E1) |
| Flue Gas | Gray (#808080) |
| Digestate | Dark Green (#006400) |
