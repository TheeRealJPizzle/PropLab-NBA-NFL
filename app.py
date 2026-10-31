from datetime import date
import os

import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="NBA Prop Lab", page_icon="🏀", layout="wide")

# A clean, responsive dashboard theme. All calculations and API behavior remain unchanged.
st.markdown("""
<style>
    .stApp { background: #0b1220; color: #e8eef8; }
    [data-testid="stHeader"] { background: rgba(11,18,32,0.88); }
    [data-testid="stSidebar"] { background: #111c2e; border-right: 1px solid #24334a; }
    .block-container { max-width: 1280px; padding-top: 2rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: #f4f7fb !important; letter-spacing: -0.025em; }
    p, label, .stMarkdown { color: #c5d0df; }
    [data-testid="stMetric"] { background: linear-gradient(145deg, #17253a, #111c2e); border: 1px solid #2b3c55; padding: 16px 18px; border-radius: 16px; }
    [data-testid="stMetricLabel"] { color: #9fb0c6 !important; }
    [data-testid="stMetricValue"] { color: #f7fafc !important; }
    [data-testid="stMetricDelta"] { color: #9fb0c6 !important; }
    div[data-testid="stButton"] > button[kind="primary"] { background: #22c55e; color: #07130b; border: 0; border-radius: 12px; font-weight: 700; min-height: 2.8rem; }
    div[data-testid="stButton"] > button { border-radius: 10px; border-color: #344760; }
    div[data-testid="stDownloadButton"] > button { border-radius: 10px; }
    [data-testid="stExpander"] { background: #111c2e; border: 1px solid #2b3c55; border-radius: 14px; }
    [data-testid="stDataFrame"] { border: 1px solid #2b3c55; border-radius: 12px; overflow: hidden; }
    .hero { padding: 1.35rem 1.5rem; border: 1px solid #2b3c55; border-radius: 20px; background: radial-gradient(circle at 90% 0%, #1b3c43 0, #17253a 38%, #111c2e 100%); margin-bottom: 1.2rem; }
    .eyebrow { color: #55d98b; font-size: .76rem; font-weight: 800; letter-spacing: .13em; text-transform: uppercase; }
    .hero-title { font-size: 2rem; font-weight: 800; color: #f7fafc; letter-spacing: -.04em; margin: .2rem 0; }
    .muted { color: #9fb0c6; font-size: .92rem; }
    .section-kicker { color: #55d98b; font-size: .75rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; margin-bottom: -.5rem; }
    .result-panel { background: #111c2e; border: 1px solid #2b3c55; border-radius: 18px; padding: 1.1rem 1.25rem; }
    .prob-track { height: 14px; background: #26364d; border-radius: 999px; overflow: hidden; display: flex; margin: .8rem 0 .45rem; }
    .prob-over { background: #22c55e; height: 100%; }
    .prob-under { background: #64748b; height: 100%; }
    .prob-labels { display: flex; justify-content: space-between; color: #c5d0df; font-size: .9rem; }
    .small-note { color: #93a4ba; font-size: .82rem; }
    hr { border-color: #2b3c55 !important; }
    @media (max-width: 700px) { .block-container { padding: 1rem .8rem 2rem; } .hero-title { font-size: 1.55rem; } }
</style>
<div class="hero">
  <div class="eyebrow">NBA analytics workspace</div>
  <div class="hero-title">Prop Lab <span style="color:#55d98b">/</span> Player Simulator</div>
  <div class="muted">Compare a prop line with a player projection in a clean, beginner-friendly view.</div>
</div>
""", unsafe_allow_html=True)

DUNKAPI_BASE = "https://mcp.dunkapi.com/v1"
PROP_COLUMNS = {
    "Points": "pts", "Rebounds": "reb", "Assists": "ast",
    "3-Pointers Made": "tpm", "Steals": "stl", "Blocks": "blk", "Turnovers": "tov",
}
SEASON_TYPES = {
    "Regular Season": "regular",
    "Playoffs": "postseason",
    "Pre Season": "preseason",
}


def get_api_key():
    """Read the API key from Streamlit secrets or an environment variable."""
    try:
        key = st.secrets.get("DUNKAPI_API_KEY", "")
    except Exception:
        key = ""
    return str(key or os.getenv("DUNKAPI_API_KEY", "")).strip()


def api_post(endpoint: str, payload: dict):
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "DunkAPI key not found. Add DUNKAPI_API_KEY to .streamlit/secrets.toml "
            "using the setup instructions in README.txt, then restart the app."
        )
    try:
        response = requests.post(
            f"{DUNKAPI_BASE}/{endpoint}",
            json=payload,
            headers={"x-api-key": key, "Content-Type": "application/json"},
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach DunkAPI: {exc}") from exc

    if response.status_code in (401, 403):
        raise RuntimeError("DunkAPI rejected the key. Check that it is copied correctly and has not been revoked.")
    if response.status_code == 402:
        raise RuntimeError("DunkAPI reports that your available credits are exhausted. Check your account dashboard before making more requests.")
    if response.status_code == 429:
        raise RuntimeError("DunkAPI rate limit reached. Wait a little while and try again.")
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text[:300].replace("\n", " ")
        raise RuntimeError(f"DunkAPI returned HTTP {response.status_code}: {detail}") from exc
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("DunkAPI returned a response that was not valid JSON.") from exc


@st.cache_data(ttl=3600, show_spinner=False)
def search_nba_players(query: str):
    payload = api_post("search_players", {"name": query, "limit": 12})
    # DunkAPI REST responses are wrapped as {"data": {...}}.
    payload = payload.get("data", payload) if isinstance(payload, dict) else payload
    players = payload.get("players", []) if isinstance(payload, dict) else []
    if not isinstance(players, list):
        raise RuntimeError("DunkAPI player search returned an unexpected response format.")
    found = []
    for player in players:
        if not isinstance(player, dict) or not player.get("player_id") or not player.get("name"):
            continue
        found.append({
            "name": str(player["name"]),
            "id": str(player["player_id"]),
            "team": str(player.get("team") or ""),
            "position": str(player.get("position") or ""),
            "last_season": player.get("last_season"),
        })
    q = query.strip().lower()
    found.sort(key=lambda p: (p["name"].lower() != q, q not in p["name"].lower(), p["name"].lower()))
    return found


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_nba_logs(player_id: str, season: int, season_type: str):
    """Fetch a player's game log from DunkAPI and normalize it for the simulator."""
    payload = api_post("get_player_games", {
        "player_id": str(player_id),
        "season": int(season),
        "season_type": season_type,
        "limit": 100,
        "offset": 0,
    })
    # DunkAPI REST responses are wrapped as {"data": {...}}.
    payload = payload.get("data", payload) if isinstance(payload, dict) else payload
    games = payload.get("games", []) if isinstance(payload, dict) else []
    if not isinstance(games, list) or not games:
        raise RuntimeError("DunkAPI returned no game rows for that player, season, and season type.")
    df = pd.DataFrame(games)
    if "date" not in df.columns:
        raise RuntimeError("DunkAPI game-log response did not include game dates.")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    for col in PROP_COLUMNS.values():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "did_not_play" in df.columns:
        df = df[~df["did_not_play"].fillna(False).astype(bool)]
    return df.sort_values("date", ascending=False).reset_index(drop=True)




@st.cache_data(ttl=900, show_spinner=False)
def fetch_tonight_schedule():
    from zoneinfo import ZoneInfo
    today_et = date.today()
    try:
        today_et = pd.Timestamp.now(tz="America/New_York").date()
    except Exception:
        pass
    payload = api_post("get_schedule", {"days": 2})
    payload = payload.get("data", payload) if isinstance(payload, dict) else payload
    games = payload.get("games", []) if isinstance(payload, dict) else []
    rows = []
    for game in games if isinstance(games, list) else []:
        if not isinstance(game, dict):
            continue
        game_date = str(game.get("date") or "")
        if game_date != today_et.isoformat():
            continue
        home, away = game.get("home") or {}, game.get("away") or {}
        rows.append({
            "game_id": str(game.get("game_id") or ""),
            "date": game_date, "starts_at": game.get("starts_at"),
            "status": str(game.get("status") or "scheduled"),
            "home": str(home.get("abbrev") or home.get("name") or "Home"),
            "away": str(away.get("abbrev") or away.get("name") or "Away"),
        })
    return rows


@st.cache_data(ttl=900, show_spinner=False)
def fetch_game_props(game_id: str):
    payload = api_post("get_player_props", {"game_id": str(game_id)})
    payload = payload.get("data", payload) if isinstance(payload, dict) else payload
    props = payload.get("props", []) if isinstance(payload, dict) else []
    return [x for x in props if isinstance(x, dict)]


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_current_team_stats():
    payload = api_post("get_team_stats", {"season": 2027, "season_type": "regular"})
    payload = payload.get("data", payload) if isinstance(payload, dict) else payload
    teams = payload.get("teams", []) if isinstance(payload, dict) else []
    return [x for x in teams if isinstance(x, dict)]


def apply_matchup_adjustment(projection, stat, opponent_abbrev, team_rows):
    valid = [x for x in team_rows if int(x.get("games") or 0) >= 3]
    opponent = next((x for x in valid if str(x.get("abbrev", "")).upper() == str(opponent_abbrev).upper()), None)
    if not opponent or not valid:
        return projection, "Not enough 2026–27 opponent data yet"
    pace_vals = [float(x["pace"]) for x in valid if x.get("pace") is not None]
    def_vals = [float(x["def_rating"]) for x in valid if x.get("def_rating") is not None]
    factor = 0.0
    labels = []
    if opponent.get("pace") is not None and pace_vals:
        pace_factor = max(-0.025, min(0.025, ((float(opponent["pace"]) / (sum(pace_vals)/len(pace_vals))) - 1) * 0.20))
        factor += pace_factor
        labels.append("pace")
    if stat == "Points" and opponent.get("def_rating") is not None and def_vals:
        # Lower defensive rating means a tougher defense; shrink and cap the effect.
        defense_factor = max(-0.04, min(0.04, ((float(opponent["def_rating"]) - (sum(def_vals)/len(def_vals))) / (sum(def_vals)/len(def_vals))) * 0.35))
        factor += defense_factor
        labels.append("defense")
    adjusted = float(projection) * (1 + factor)
    direction = "slightly favorable" if factor > 0.008 else "slightly tough" if factor < -0.008 else "near neutral"
    return adjusted, f"{direction} matchup ({', '.join(labels)}; 2026–27 data)"


def build_stat_logs(df, player_name, stat):
    if stat == "PRA":
        needed = ["pts", "reb", "ast"]
        if not all(col in df.columns for col in needed):
            return pd.DataFrame()
        values = df[needed].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=3)
    else:
        col = PROP_COLUMNS.get(stat)
        if not col or col not in df.columns:
            return pd.DataFrame()
        values = pd.to_numeric(df[col], errors="coerce")
    result = pd.DataFrame({"player": player_name, "date": df["date"], "stat": stat, "value": values})
    return result.dropna(subset=["date", "value"]).reset_index(drop=True)


def calculate_projection(player_logs):
    ordered = player_logs.sort_values("date", ascending=False)
    values = ordered["value"].astype(float)
    if values.empty:
        raise ValueError("No game results were found for this player and prop.")
    last5, last10 = values.head(5), values.head(10)
    season_avg = float(values.mean())
    avg5 = float(last5.mean())
    avg10 = float(last10.mean())
    projection = 0.50 * avg5 + 0.30 * avg10 + 0.20 * season_avg
    std_dev = float(values.std(ddof=1)) if len(values) > 1 else max(1.0, float(values.iloc[0]) * 0.20)
    if not np.isfinite(std_dev) or std_dev < 0.1:
        std_dev = 0.1
    return avg5, avg10, season_avg, projection, std_dev, len(values)


def walk_forward_backtest(player_logs, min_history=5):
    """Predict each game using only earlier games; never use the target game's stats."""
    ordered = player_logs.sort_values("date", ascending=True).reset_index(drop=True)
    rows = []
    for target_idx in range(min_history, len(ordered)):
        history = ordered.iloc[:target_idx]
        target = ordered.iloc[target_idx]
        _, _, season_avg, projection, _, history_count = calculate_projection(history)
        actual = float(target["value"])
        rows.append({
            "date": target["date"],
            "games_before_prediction": history_count,
            "projected_value": projection,
            "season_average_baseline": season_avg,
            "actual_value": actual,
            "model_error": projection - actual,
            "baseline_error": season_avg - actual,
            "absolute_error": abs(projection - actual),
        })
    return pd.DataFrame(rows)


def compare_projection_weights(player_logs, min_history=5):
    """Compare fixed weighting choices using walk-forward history only; no API calls."""
    candidates = [
        ("Current: 50/30/20", 0.50, 0.30, 0.20),
        ("Recent-heavy: 60/25/15", 0.60, 0.25, 0.15),
        ("Balanced recent: 40/40/20", 0.40, 0.40, 0.20),
        ("Season-heavier: 40/30/30", 0.40, 0.30, 0.30),
        ("Equal blend: 33/33/34", 0.33, 0.33, 0.34),
    ]
    ordered = player_logs.sort_values("date", ascending=True).reset_index(drop=True)
    rows = []
    for label, w5, w10, ws in candidates:
        errors = []
        for target_idx in range(min_history, len(ordered)):
            history = ordered.iloc[:target_idx].sort_values("date", ascending=False)
            values = history["value"].astype(float)
            avg5 = float(values.head(5).mean())
            avg10 = float(values.head(10).mean())
            season_avg = float(values.mean())
            prediction = w5 * avg5 + w10 * avg10 + ws * season_avg
            errors.append(prediction - float(ordered.iloc[target_idx]["value"]))
        if errors:
            rows.append({
                "Weighting": label,
                "Last 5": f"{w5:.0%}",
                "Last 10": f"{w10:.0%}",
                "Season": f"{ws:.0%}",
                "MAE": float(np.mean(np.abs(errors))),
                "RMSE": float(np.sqrt(np.mean(np.square(errors)))),
                "Bias": float(np.mean(errors)),
            })
    return pd.DataFrame(rows).sort_values("MAE").reset_index(drop=True) if rows else pd.DataFrame()


slate_tab, simulator_tab, notes_tab = st.tabs(["Tonight’s Slate", "Prop Picks", "About the Model"])

with slate_tab:
    st.subheader("Tonight’s NBA games & player props")
    st.caption("Automatic slate and sportsbook lines from DunkAPI. FanDuel is shown first when available; other books remain visible when FanDuel has no line.")
    if st.button("Load tonight’s games and props", type="primary", use_container_width=True):
        try:
            with st.spinner("Loading tonight’s schedule…"):
                slate_games = fetch_tonight_schedule()
            st.session_state["nba_tonight_games"] = slate_games
            if not slate_games:
                st.info("DunkAPI did not return any games dated today. Try refreshing later.")
            else:
                all_props = []
                progress = st.progress(0)
                for idx, game in enumerate(slate_games):
                    with st.spinner(f"Loading props: {game['away']} at {game['home']}…"):
                        props = fetch_game_props(game["game_id"])
                    for prop in props:
                        prop["matchup"] = f"{game['away']} @ {game['home']}"
                        prop["game_id"] = game["game_id"]
                        prop["_home_abbrev"] = game["home"]
                        prop["_away_abbrev"] = game["away"]
                        all_props.append(prop)
                    progress.progress((idx + 1) / len(slate_games))
                st.session_state["nba_tonight_props"] = all_props
                st.success(f"Loaded {len(slate_games)} games and {len(all_props)} prop lines. Cached for 15 minutes.")
        except Exception as exc:
            st.error(f"Could not load tonight’s slate: {exc}")
    slate_games = st.session_state.get("nba_tonight_games", [])
    slate_props = st.session_state.get("nba_tonight_props", [])
    if slate_games:
        st.markdown("**Tonight’s matchups**")
        st.dataframe(pd.DataFrame([{ "Matchup": f"{g['away']} @ {g['home']}", "Tip-off (UTC)": g.get("starts_at"), "Status": g["status"]} for g in slate_games]), use_container_width=True, hide_index=True)
    if slate_props:
        book = st.selectbox("Preferred sportsbook", ["fanduel", "draftkings", "pinnacle", "all books"], format_func=lambda x: {"fanduel":"FanDuel", "draftkings":"DraftKings", "pinnacle":"Pinnacle", "all books":"All available books"}[x])
        prop_rows = []
        for item in slate_props:
            bookmaker = str(item.get("bookmaker") or "").lower()
            if book != "all books" and bookmaker != book:
                continue
            prop_rows.append({"Game": item.get("matchup", ""), "Player": item.get("player_name", ""), "Market": str(item.get("market", "")).replace("player_", "").replace("_", " ").title(), "Line": item.get("line"), "Book": bookmaker.title(), "Over": item.get("over_odds"), "Under": item.get("under_odds"), "Player ID": item.get("player_id", ""), "Player Team": item.get("team_abbrev") or item.get("team") or item.get("team_abbreviation") or "", "Home Team": item.get("_home_abbrev", ""), "Away Team": item.get("_away_abbrev", ""), "Game ID": item.get("game_id", "")})
        if prop_rows:
            frame = pd.DataFrame(prop_rows)
            st.dataframe(frame.drop(columns=["Player ID"]), use_container_width=True, hide_index=True)
            st.caption("Choose a player below to load their 2026–27 regular-season game log. Player logs cost 5 DunkAPI credits per selected player; prop retrieval costs 10 credits per game before tip-off.")
            choices = {f"{r['Player']} · {r['Market']} {r['Line']} · {r['Game']} · {r['Book']}": r for r in prop_rows if r["Player"] and r["Player ID"]}
            if choices:
                chosen_label = st.selectbox("Select a listed prop to project", list(choices))
                if st.button("Use this prop in the simulator", use_container_width=True):
                    chosen = choices[chosen_label]
                    # Resolve the player's current team from DunkAPI's player directory.
                    # The props response may omit team fields, so never infer the opponent blindly.
                    player_team = str(chosen.get("Player Team") or "").upper()
                    if not player_team:
                        try:
                            matches = search_nba_players(chosen["Player"])
                            exact = next((p for p in matches if p["id"] == str(chosen["Player ID"])), None)
                            if exact:
                                player_team = str(exact.get("team") or "").upper()
                        except Exception:
                            player_team = ""
                    game = next((g for g in st.session_state.get("nba_tonight_games", []) if str(g.get("game_id")) == str(chosen.get("Game ID", ""))), None)
                    home = str(chosen.get("Home Team") or (game or {}).get("home") or "").upper()
                    away = str(chosen.get("Away Team") or (game or {}).get("away") or "").upper()
                    opponent = away if player_team and player_team == home else home if player_team and player_team == away else ""
                    st.session_state["nba_selected_player"] = {"name": chosen["Player"], "id": str(chosen["Player ID"]), "team": player_team, "position": ""}
                    st.session_state["nba_slate_line"] = float(chosen["Line"])
                    st.session_state["nba_slate_market"] = chosen["Market"]
                    st.session_state["nba_slate_opponent"] = opponent
                    st.session_state["nba_slate_opponent_reason"] = "" if opponent else "Could not verify the player's current team from DunkAPI"
                    st.session_state.pop("nba_game_logs", None)
                    st.success("Prop selected. Player, line, and matchup have been carried into Prop Picks.")
        else:
            st.info("No lines were returned for that sportsbook. Try All available books or check again closer to tip-off.")


with simulator_tab:
    stat_options = ["Points", "Rebounds", "Assists", "3-Pointers Made", "Steals", "Blocks", "PRA", "Turnovers"]
    market_map = {"Points":"Points", "Rebounds":"Rebounds", "Assists":"Assists", "Threes":"3-Pointers Made", "Blocks":"Blocks", "Steals":"Steals", "Points Rebounds Assists":"PRA"}
    default_stat = st.session_state.get("nba_slate_market", "Points")
    stat = st.selectbox("Player prop", stat_options, index=stat_options.index(market_map.get(default_stat, "Points")))
    st.markdown('<div class="section-kicker">01 · Player & data</div>', unsafe_allow_html=True)
    st.subheader("Choose a player")
    st.write("Search the DunkAPI player directory, choose a result, and load game-by-game stats. Your API key stays on your computer in Streamlit's local secrets file.")

    current_year = date.today().year
    if date.today().month >= 10:
        current_season = f"{current_year}-{str(current_year + 1)[-2:]}"
    else:
        current_season = f"{current_year - 1}-{str(current_year)[-2:]}"
    season_options = ["2026-27"]
    season_choice = st.selectbox("NBA season", season_options, index=0, disabled=True)
    st.caption("Projections use 2026–27 regular-season games only. Earlier seasons are not mixed into the model.")
    season_type_label = st.selectbox("Season type", list(SEASON_TYPES.keys()))

    query = st.text_input("Search player name", placeholder="Start typing: Jayson Tatum", key="nba_player_query")
    match_list = []
    if len(query.strip()) >= 2:
        try:
            match_list = search_nba_players(query)
        except Exception as exc:
            st.error(f"Player search could not be completed: {exc}")

    if len(query.strip()) >= 2 and match_list:
        st.caption("Choose the correct player:")
        for i in range(0, len(match_list), 2):
            cols = st.columns(2)
            for col, match in zip(cols, match_list[i:i + 2]):
                team_label = f" · {match['team']}" if match["team"] else ""
                with col:
                    if st.button(match["name"] + team_label, key=f"nba_player_{match['id']}", use_container_width=True):
                        st.session_state["nba_selected_player"] = match
                        st.session_state.pop("nba_game_logs", None)
                        st.rerun()
    elif len(query.strip()) >= 2:
        st.caption("No matching players found. Check the spelling or try another name.")

    selected = st.session_state.get("nba_selected_player")
    if selected:
        st.write(f"**Selected player:** {selected['name']}")
        if st.button(f"Load {selected['name']}'s game logs", type="primary", use_container_width=True):
            try:
                season_end_year = int(season_choice.split("-")[0]) + 1
                with st.spinner(f"Loading {selected['name']}'s NBA game logs..."):
                    raw_logs = fetch_nba_logs(selected["id"], season_end_year, SEASON_TYPES[season_type_label])
                    fetched_logs = build_stat_logs(raw_logs, selected["name"], stat)
                if fetched_logs.empty:
                    st.warning(f"Game logs loaded, but no values were available for {stat}. Try another prop or season.")
                else:
                    st.session_state["nba_game_logs"] = fetched_logs
                    st.session_state["nba_logs_player"] = selected["name"]
                    st.session_state["nba_logs_stat"] = stat
                    st.session_state["nba_logs_season"] = season_choice
                    st.success(f"Loaded {len(fetched_logs)} {stat} game results for {selected['name']}.")
            except Exception as exc:
                st.error(f"Could not fetch NBA game logs: {exc}")

    line = st.number_input("Sportsbook prop line", min_value=0.0, value=float(st.session_state.get("nba_slate_line", 24.5)), step=0.5)
    with st.expander("Model Lab · advanced settings", expanded=False):
        simulations = st.select_slider(
            "Simulation runs",
            options=[1000, 5000, 10000, 25000, 50000, 100000],
            value=10000,
        )
        seed = st.number_input(
            "Random seed",
            min_value=0,
            max_value=999999,
            value=42,
        )
        st.caption("Technical diagnostics, backtesting, and weight comparisons are kept below for model development.")

    logs = st.session_state.get("nba_game_logs")
    if logs is not None and (st.session_state.get("nba_logs_stat") != stat or st.session_state.get("nba_logs_season") != season_choice):
        logs = None

    projection_ready = False
    player_name = selected["name"] if selected else ""
    mean = 0.0
    std_dev = 0.1
    if logs is not None and not logs.empty:
        try:
            avg5, avg10, season_avg, mean, std_dev, game_count = calculate_projection(logs)
            matchup_note = st.session_state.get("nba_slate_opponent_reason", "No opponent adjustment selected")
            opponent_code = st.session_state.get("nba_slate_opponent", "")
            if opponent_code:
                try:
                    team_rows = fetch_current_team_stats()
                    mean, matchup_note = apply_matchup_adjustment(mean, stat, opponent_code, team_rows)
                except Exception:
                    matchup_note = "Current-season matchup data unavailable; base projection shown"
            projection_ready = True
            st.markdown('<div class="section-kicker">02 · Your projection</div>', unsafe_allow_html=True)
            st.subheader(f"{player_name} · {stat}")
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("Sportsbook line", f"{line:g}")
            pc2.metric("Our projection", f"{mean:.1f}")
            pc3.metric("Difference", f"{mean - line:+.1f}", delta="Above line" if mean > line else "Below line" if mean < line else "At the line")
            st.caption(f"Matchup adjustment: {matchup_note}")
            with st.expander("Model Lab · performance details", expanded=False):
                st.caption("These technical details are for model development and are not needed to read the prop lean.")
                d1, d2, d3 = st.columns(3)
                d1.metric("Last 5 average", f"{avg5:.1f}")
                d2.metric("Last 10 average", f"{avg10:.1f}")
                d3.metric("Season average", f"{season_avg:.1f}")
                st.metric("Standard deviation", f"{std_dev:.1f}")
                st.markdown("**Game logs used for this projection**")
                st.dataframe(logs[[c for c in ["date", "stat", "value"] if c in logs.columns]], use_container_width=True, hide_index=True)
                st.markdown('<div class="section-kicker">Backtesting</div>', unsafe_allow_html=True)
                st.subheader("Walk-forward backtest")
                st.caption("Each historical game is predicted using only games played before it. The first five games are used to build the initial history and are not scored.")
                backtest = walk_forward_backtest(logs, min_history=5)
                if len(backtest) < 1:
                    st.info("At least 6 games are needed to run this backtest. Load a longer game log or choose another season.")
                else:
                    model_mae = float(backtest["absolute_error"].mean())
                    model_rmse = float(np.sqrt(np.mean(np.square(backtest["model_error"]))))
                    model_bias = float(backtest["model_error"].mean())
                    baseline_mae = float(backtest["baseline_error"].abs().mean())
                    b1, b2, b3, b4 = st.columns(4)
                    b1.metric("Games tested", f"{len(backtest)}")
                    b2.metric("Model MAE", f"{model_mae:.2f}")
                    b3.metric("Season-average MAE", f"{baseline_mae:.2f}", delta=f"{baseline_mae - model_mae:+.2f} vs. model")
                    b4.metric("Model bias", f"{model_bias:+.2f}")
                    st.caption(f"RMSE: {model_rmse:.2f}. Lower MAE/RMSE is better. Positive bias means the model tended to overpredict; negative bias means it tended to underpredict.")
                    st.markdown("**Backtest game-by-game results**")
                    shown = backtest.copy()
                    shown["date"] = pd.to_datetime(shown["date"]).dt.strftime("%Y-%m-%d")
                    st.dataframe(shown[["date", "games_before_prediction", "projected_value", "actual_value", "model_error", "season_average_baseline"]].rename(columns={"date": "Game date", "games_before_prediction": "Prior games", "projected_value": "Projection", "actual_value": "Actual", "model_error": "Error (projection - actual)", "season_average_baseline": "Season average baseline"}).round(2), use_container_width=True, hide_index=True)
                    st.download_button("Download backtest results (CSV)", backtest.to_csv(index=False).encode("utf-8"), f"{player_name.replace(' ', '_')}_{stat.replace(' ', '_')}_backtest.csv", "text/csv")
                    if model_mae < baseline_mae:
                        st.success("On this sample, the weighted projection had a lower average absolute error than the simple season-average baseline.")
                    elif model_mae > baseline_mae:
                        st.warning("On this sample, the simple season-average baseline had a lower average absolute error than the weighted projection.")
                    else:
                        st.info("On this sample, the weighted projection and season-average baseline had the same MAE.")
                    st.markdown("**Projection weight comparison (local test)**")
                    weight_results = compare_projection_weights(logs, min_history=5)
                    if not weight_results.empty:
                        st.dataframe(weight_results.round({"MAE": 2, "RMSE": 2, "Bias": 2}), use_container_width=True, hide_index=True)
                        best = weight_results.iloc[0]
                        st.info(f"Lowest MAE in this player's historical sample: {best['Weighting']} (MAE {best['MAE']:.2f}). This is exploratory, not proof of future performance.")
                    else:
                        st.info("Not enough games to compare weighting combinations.")
                    st.caption("This comparison uses already-loaded game logs and makes no DunkAPI requests. Avoid selecting weights based on one player alone.")
                    st.caption("This evaluates point-projection accuracy only. It does not measure historical betting results because past sportsbook prop lines are not included. A small sample can be misleading.")
        except Exception as exc:
            st.error(f"Could not calculate the projection: {exc}")

    if not projection_ready:
        st.info("Select a player and load that player's game logs above to calculate a projection before running a simulation.")

    if st.button(
        "Show prop outlook",
        type="primary",
        use_container_width=True,
        disabled=not projection_ready,
    ):
        rng = np.random.default_rng(int(seed))
        samples = np.rint(rng.normal(loc=mean, scale=std_dev, size=int(simulations)))
        samples = np.clip(samples, 0, None)
        over = float(np.mean(samples > line))
        under = float(np.mean(samples < line))
        push = float(np.mean(samples == line))
        fair_over, fair_under = over + push / 2, under + push / 2
        st.session_state["nba_last_simulation"] = {
            "player": player_name.strip(), "stat": stat, "line": float(line),
            "mean": float(mean), "std_dev": float(std_dev), "over": over,
            "under": under, "push": push, "fair_over": fair_over,
            "fair_under": fair_under, "samples": samples,
            "simulations": int(simulations),
        }

    result = st.session_state.get("nba_last_simulation")
    if result and (
        not projection_ready
        or result["player"] != player_name.strip()
        or result["stat"] != stat
        or result["line"] != float(line)
        or result["mean"] != float(mean)
    ):
        result = None

    if result:
        st.divider()
        st.markdown('<div class="section-kicker">Your prop outlook</div>', unsafe_allow_html=True)
        st.subheader(f'{result["player"]} · {result["stat"]}')
        over_pct = result["over"] * 100
        under_pct = result["under"] * 100
        edge = result["mean"] - result["line"]
        if edge > 0 and result["over"] > result["under"]:
            lean = "OVER LEAN"
            explanation = "The projection is above the line, and the simulation favors the over."
            lean_color = "#22c55e"
        elif edge < 0 and result["under"] > result["over"]:
            lean = "UNDER LEAN"
            explanation = "The projection is below the line, and the simulation favors the under."
            lean_color = "#60a5fa"
        else:
            lean = "NO CLEAR EDGE"
            explanation = "The projection and simulation do not show a clear direction."
            lean_color = "#c5d0df"
        st.markdown(f'''<div class="result-panel">
          <div style="font-size:.82rem;color:#9fb0c6">MODEL LEAN</div>
          <div style="font-size:2rem;font-weight:850;color:{lean_color};margin:.2rem 0">{lean}</div>
          <div style="color:#c5d0df">{explanation}</div>
        </div>''', unsafe_allow_html=True)
        r1, r2, r3 = st.columns(3)
        r1.metric("Prop line", f'{result["line"]:g}')
        r2.metric("Projection", f'{result["mean"]:.1f}')
        r3.metric("Difference", f'{edge:+.1f}')
        st.markdown('<div class="result-panel">', unsafe_allow_html=True)
        st.markdown("**Estimated chance**")
        st.markdown(f'''<div class="prob-track"><div class="prob-over" style="width:{over_pct:.4f}%"></div><div class="prob-under" style="width:{under_pct:.4f}%"></div></div>
        <div class="prob-labels"><span>🟢 OVER&nbsp; <b>{result["over"]:.1%}</b></span><span>UNDER&nbsp; <b>{result["under"]:.1%}</b> &nbsp; ⚪</span></div>''', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        with st.expander("More details", expanded=False):
            st.caption(f'{result["simulations"]:,} simulated outcomes · {season_choice} {season_type_label.lower()} data')
            d1, d2 = st.columns(2)
            d1.metric("Push chance", f'{result["push"]:.1%}')
            d2.metric("Expected variation", f'{result["std_dev"]:.1f}')
            st.bar_chart(pd.Series(result["samples"]).value_counts().sort_index())
            results = pd.DataFrame({"Simulated result": result["samples"]})
            safe_name = result["player"].replace(" ", "_")
            st.download_button("Download results (CSV)", results.to_csv(index=False).encode("utf-8"), f'{safe_name}_NBA_{result["stat"].replace(" ", "_")}_simulations.csv', "text/csv")
        st.caption("Projections and probabilities are estimates, not guarantees. Check player availability, minutes, and the latest line before making a betting decision.")

with notes_tab:
    st.subheader("Data & model notes")
    st.write("""
    - Player search and game logs are provided by DunkAPI. This app sends API requests from your computer; your key is read from the local Streamlit secrets file and is not embedded in the app source.
    - DunkAPI data is best-effort and may be incomplete, delayed, or changed. Check important records against trusted box scores.
    - The 50/30/20 projection blend is a transparent starting heuristic, not a trained or backtested model.
    - The simulation uses a rounded normal-distribution approximation. Low-count props such as steals, blocks, and turnovers may need specialized statistical distributions.
    - Opponent adjustment uses 2026–27 team pace for all supported props and defensive rating for points only. It is intentionally small and is withheld until the opponent has at least three current-season games. It is team-level, not position-specific.
    - No injury adjustments, confirmed starters, or minutes projections are included.
    - This is an independent analysis tool, not official NBA data or betting advice. Review provider terms and applicable laws before any commercial launch.
    """)

