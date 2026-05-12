import secrets
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from api.endpoints.scoring import ScoringLatestSetInfo, screener_info
from api.endpoints.validator import get_connected_validators_info
from models.evaluation_set import EvaluationSetGroup
from queries.agent import get_agents_in_queue
from queries.evaluation_set import get_latest_set_id, get_set_created_at
from api.utils.limiter import limiter

router = APIRouter()

# /dashboard
@router.get("/")
@limiter.limit("30/minute")
async def dashboard(request: Request):
    
    screener1_queue = await get_agents_in_queue(EvaluationSetGroup("screener_1"))
    screener2_queue = await get_agents_in_queue(EvaluationSetGroup("screener_2"))
    validator_queue = await get_agents_in_queue(EvaluationSetGroup("validator"))
    latest_set_id=await get_latest_set_id()
    latest_set_created_at = await get_set_created_at(latest_set_id)
    set_info =  ScoringLatestSetInfo(
        latest_set_id=latest_set_id,
        latest_set_created_at=latest_set_created_at
    )
    
    validators = get_connected_validators_info()
    screener = await screener_info(request)
    total_validators = validators["connected_validators"]

    # Clean up data before HTML rendering
    s1_wait = f"{screener.screener_1_average_wait_time:.1f}s" if screener.screener_1_average_wait_time is not None else "N/A"
    s2_wait = f"{screener.screener_2_average_wait_time:.1f}s" if screener.screener_2_average_wait_time is not None else "N/A"
    val_wait = f"{screener.validator_average_wait_time:.1f}s" if screener.validator_average_wait_time is not None else "N/A"
    
    s1_score = screener.screener_1_average_score if screener.screener_1_average_score is not None else 0.0
    s2_score = screener.screener_2_average_score if screener.screener_2_average_score is not None else 0.0
    val_score = screener.validator_average_score if screener.validator_average_score is not None else 0.0
    
    s1_score_display = f"{s1_score:.2f}" if screener.screener_1_average_score is not None else "N/A"
    s2_score_display = f"{s2_score:.2f}" if screener.screener_2_average_score is not None else "N/A"
    val_score_display = f"{val_score:.2f}" if screener.validator_average_score is not None else "N/A"
    
    set_date = str(set_info.latest_set_created_at)[:10]

    schemes = {
        "modern": {
            "bg": "#1e1e2e",
            "text": "#cdd6f4",
            "queue": "#89b4fa",
            "validators": "#a6e3a1",
            "set": "#f9e2af",
            "bars": ["#89b4fa", "#f38ba8", "#fab387"]
        },
        "ocean": {
            "bg": "#0d1b2a",
            "text": "#e0e1dd",
            "queue": "#415a77",
            "validators": "#778da9",
            "set": "#1b263b",
            "bars": ["#415a77", "#778da9", "#e0e1dd"]
        },
        "sunset": {
            "bg": "#2d1b2e",
            "text": "#f4e4c1",
            "queue": "#ff6b6b",
            "validators": "#f9a825",
            "set": "#f4a261",
            "bars": ["#e76f51", "#f4a261", "#e9c46a"]
        },
        "forest": {
            "bg": "#1a1f16",
            "text": "#d4e09b",
            "queue": "#6a994e",
            "validators": "#a7c957",
            "set": "#bc4749",
            "bars": ["#6a994e", "#a7c957", "#f2cc8f"]
        }
    }    
    
    scheme = secrets.choice(list(schemes.keys()))
    colors = schemes[scheme]
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Bitrecs V2 Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{
            background-color: {colors['bg']};
            color: {colors['text']};
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
        }}
        h1 {{
            text-align: center;
            font-size: 32px;
            margin-bottom: 30px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            max-width: 1400px;
            margin: 0 auto;
        }}
        .card {{
            padding: 30px;
            border-radius: 10px;
            text-align: center;
        }}
        .card h2 {{
            margin: 0 0 10px 0;
            font-size: 24px;
        }}
        .card .value {{
            font-size: 48px;
            font-weight: bold;
            margin: 10px 0;
        }}
        .card .label {{
            font-size: 18px;
            opacity: 0.8;
        }}
        .card .sub-value {{
            font-size: 20px;
            margin: 5px 0;
            opacity: 0.9;
        }}
        .queue {{ background-color: {colors['queue']}33; border: 2px solid {colors['queue']}; }}
        .validators {{ background-color: {colors['validators']}33; border: 2px solid {colors['validators']}; }}
        .set {{ background-color: {colors['set']}33; border: 2px solid {colors['set']}; }}
        .scores {{
            background-color: {colors['bg']};
            border: 2px solid {colors['text']}33;
            grid-column: span 3;
        }}
        .thresholds {{
            background-color: {colors['bg']};
            border: 2px solid {colors['text']}33;
            grid-column: span 3;
            padding: 20px;
        }}
        .threshold-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-top: 15px;
        }}
        .threshold-item {{
            text-align: center;
            padding: 15px;
            border-radius: 8px;
            background-color: {colors['text']}11;
        }}
        .threshold-item .label {{
            font-size: 14px;
            opacity: 0.7;
            margin-bottom: 5px;
        }}
        .threshold-item .value {{
            font-size: 28px;
            font-weight: bold;
        }}
        .score-bar {{
            display: flex;
            justify-content: space-around;
            margin-top: 20px;
            flex-wrap: wrap;
            gap: 20px;
        }}
        .score-item {{
            text-align: center;
        }}
        .score-item .bar {{
            width: 60px;
            height: 150px;
            border-radius: 5px;
            margin: 0 auto 10px;
            position: relative;
        }}
        .score-item .fill {{
            position: absolute;
            bottom: 0;
            width: 100%;
            border-radius: 5px;
        }}
        .score-item .metric {{
            font-size: 14px;
            margin-top: 5px;
            opacity: 0.8;
        }}
        
        /* Mobile responsive */
        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}
            h1 {{
                font-size: 24px;
                margin-bottom: 20px;
            }}
            .grid {{
                grid-template-columns: 1fr;
                gap: 15px;
            }}
            .card {{
                padding: 20px;
            }}
            .card h2 {{
                font-size: 20px;
            }}
            .card .value {{
                font-size: 36px;
            }}
            .card .label {{
                font-size: 16px;
            }}
            .scores {{
                grid-column: span 1;
            }}
            .thresholds {{
                grid-column: span 1;
            }}
            .threshold-grid {{
                grid-template-columns: 1fr;
            }}
            .score-bar {{
                justify-content: center;
            }}
        }}
        
        /* Tablet responsive */
        @media (min-width: 769px) and (max-width: 1024px) {{
            .grid {{
                grid-template-columns: 1fr 1fr;
            }}
            .scores {{
                grid-column: span 2;
            }}
            .thresholds {{
                grid-column: span 2;
            }}
        }}
    </style>
</head>
<body>
    <h1>🚀 Bitrecs V2 Dashboard</h1>
    <div class="grid">
        <div class="card set">
            <h2>Eval Set</h2>
            <div class="value">#{set_info.latest_set_id}</div>
            <div class="label">{set_date}</div>
        </div>
        <div class="card validators">
            <h2>Validators</h2>
            <div class="value">{total_validators}</div>
            <div class="label">Connected</div>
        </div>
        <div class="card queue">
            <h2>Screener 1</h2>
            <div class="value">{len(screener1_queue)}</div>
            <div class="label">In Queue</div>
            <div class="sub-value">{s1_wait} avg wait</div>
        </div>
        <div class="card queue">
            <h2>Screener 2</h2>
            <div class="value">{len(screener2_queue)}</div>
            <div class="label">In Queue</div>
            <div class="sub-value">{s2_wait} avg wait</div>
        </div>
        <div class="card queue">
            <h2>Validator</h2>
            <div class="value">{len(validator_queue)}</div>
            <div class="label">In Queue</div>
            <div class="sub-value">{val_wait} avg wait</div>
        </div>
        
        <div class="card thresholds">
            <h2>Scoring Thresholds</h2>
            <div class="threshold-grid">
                <div class="threshold-item">
                    <div class="label">Screener 1</div>
                    <div class="value">{screener.screener_1_threshold:.2f}</div>
                </div>
                <div class="threshold-item">
                    <div class="label">Screener 2</div>
                    <div class="value">{screener.screener_2_threshold:.2f}</div>
                </div>
                <div class="threshold-item">
                    <div class="label">Prune</div>
                    <div class="value">{screener.prune_threshold:.2f}</div>
                </div>
            </div>
        </div>
      
        <div class="card scores">
            <h2>Average Scores</h2>
            <div class="score-bar">
                <div class="score-item">
                    <div class="bar" style="background-color: {colors['bars'][0]}22;">
                        <div class="fill" style="background-color: {colors['bars'][0]}; height: {s1_score*100}%;"></div>
                    </div>
                    <div>{s1_score_display}</div>
                    <div class="label">Screener 1</div>
                </div>
                <div class="score-item">
                    <div class="bar" style="background-color: {colors['bars'][1]}22;">
                        <div class="fill" style="background-color: {colors['bars'][1]}; height: {s2_score*100}%;"></div>
                    </div>
                    <div>{s2_score_display}</div>
                    <div class="label">Screener 2</div>
                </div>
                <div class="score-item">
                    <div class="bar" style="background-color: {colors['bars'][2]}22;">
                        <div class="fill" style="background-color: {colors['bars'][2]}; height: {val_score*100}%;"></div>
                    </div>
                    <div>{val_score_display}</div>
                    <div class="label">Validator</div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""    
    return HTMLResponse(content=html)

