# predict soc from last 15 minutes of BMS data

import xgboost as xgb
import numpy as np

from influxdb import DataFrameClient, InfluxDBClient
import pandas as pd

host = '10.0.1.7'
port =  8086
dbname = 'sensors'
client = InfluxDBClient(host, port, database=dbname)

metrics_list = ['esphome-jbd-bms_state_of_charge',
                'esphome-jbd-bms_average_cell_voltage',
                'soc',
#                'esphome-jbd-bms_delta_cell_voltage',
                'esphome-jbd-bms_current',
                'esphome-jbd-bms_temperature_2',
#                'esphome-jbd-bms_cell_voltage_1',
#                'esphome-jbd-bms_cell_voltage_2',
#                'esphome-jbd-bms_cell_voltage_3',
#                'esphome-jbd-bms_cell_voltage_4',
#                'esphome-jbd-bms_cell_voltage_5',
#                'esphome-jbd-bms_cell_voltage_6',
#                'esphome-jbd-bms_cell_voltage_7',
#                'esphome-jbd-bms_cell_voltage_8'
               ]

for i, m in enumerate(metrics_list):
    query= '''
    select value from 
    "''' + m + '''"
    where time > now() - 16m;
    '''
    try:
        name = m.split('-')[2]
    except:
        name = m
    result = client.query(query)
    dat = result.raw['series'][0]['values']
    col = result.raw['series'][0]['columns']
    df = pd.DataFrame(dat, columns=col)
    df = df.rename(columns={'value': name})
    df.time = pd.to_datetime(df.time, format='ISO8601')
    if i == 0:
        rdf = df
    else:
        rdf = pd.merge_asof(rdf, df, on='time', direction='nearest')

rdf = rdf.set_index('time')

df2 = rdf.resample('10s').mean()

# # Predict

model = xgb.XGBRegressor()
model.load_model('soc_model.json')

df2['soc_d'] = df2.soc.shift(90)

df2['roll_v_10'] = df2.bms_average_cell_voltage.rolling(10).mean()
df2['roll_c_10'] = df2.bms_current.rolling(10).mean()
df2['roll_cs_90'] = df2.bms_current.rolling(90).sum()
df2['roll_vs_90'] = df2.bms_average_cell_voltage.rolling(90).sum()
df2['roll_v_90'] = df2.bms_average_cell_voltage.rolling(90).mean()
df2['roll_c_90'] = df2.bms_current.rolling(90).mean()
df2['temp_roll_90'] = df2.bms_temperature_2.rolling(90).mean()

df2 = df2.tail(1) # recent sample


X = df2[[
         'bms_current',
         'bms_average_cell_voltage',
         'soc_d',
         'roll_c_10', 
         'roll_c_90', 
         'roll_v_10', 
         'roll_v_90', 
         'roll_cs_90',
         'bms_temperature_2',
         'temp_roll_90'
]]

# Predict SOC value
pred = model.predict(X)
pred = pred.clip(0, 100.0)

print(pred[0])
