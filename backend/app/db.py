import sqlite3, os, threading
PATH = os.environ.get("AQUA_DB", "aqua.db")
LOCK = threading.RLock()
_c = None
def conn():
    global _c
    if _c is None:
        _c = sqlite3.connect(PATH, check_same_thread=False); _c.row_factory = sqlite3.Row
        _c.executescript("""CREATE TABLE IF NOT EXISTS rainfall_forecasts(city_id TEXT,date TEXT,precip_mm REAL,fetched_at TEXT,source TEXT,PRIMARY KEY(city_id,date));
        CREATE TABLE IF NOT EXISTS rainfall_observations(city_id TEXT,date TEXT,precip_mm REAL,fetched_at TEXT,source TEXT,PRIMARY KEY(city_id,date));
        CREATE TABLE IF NOT EXISTS data_ingestion_logs(id INTEGER PRIMARY KEY,source TEXT,dataset TEXT,city_id TEXT,ts TEXT,records_received INT,records_valid INT,records_rejected INT,ok INT,error TEXT);
        CREATE TABLE IF NOT EXISTS simulation_runs(id INTEGER PRIMARY KEY,ts TEXT,city_id TEXT,request TEXT,result TEXT);
        CREATE TABLE IF NOT EXISTS reservoir_observations(city_id TEXT,reservoir TEXT,date TEXT,storage_pct REAL,uploaded_at TEXT,PRIMARY KEY(city_id,reservoir,date));
        CREATE INDEX IF NOT EXISTS i_obs ON rainfall_observations(city_id,date); CREATE INDEX IF NOT EXISTS i_log ON data_ingestion_logs(dataset,city_id,ts);""")
    return _c
