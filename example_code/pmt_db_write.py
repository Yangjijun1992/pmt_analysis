import sqlite3
from datetime import datetime
import pmt_database as pmt_db
# mapping_path = '/mnt/data/TPC/run5_Ar/mapping.json'
# rec = pmt_db.create_recorder(mapping_path, "/home/yjj/pmtdatabase/pmt-data-client/data/pmt_data.db")

# 获取连接（假设 rec 是 PMTDataRecorder 实例）
conn = sqlite3.connect(rec.db_path, timeout=10)
conn.execute("PRAGMA journal_mode=WAL")
cursor = conn.cursor()

# 插入一行，指定 id=100（请确保该 id 尚未被占用）
cursor.execute("""
    INSERT INTO measurements (
        pmt_id, board_id, channel_id, measurement_time,
        run_type, hv, temperature, gain, dark_count_rate, notes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,?)
""", ( 
    "LV2204",                # pmt_id
    0,                       # board_id
    0,                      # channel_id
    "2025-08-03 14:30:00",   # measurement_time
    "Room_Temp",           # run_type
    750,                   # hv
    298.15,                    # temperature
    5.417,                    # gain
    159.24,    
    "add room temp test results"
))
conn.commit()
conn.close()