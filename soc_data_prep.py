from influxdb import DataFrameClient, InfluxDBClient
import pandas as pd

host = '10.0.1.7'
port =  8086
dbname = 'sensors'
client = InfluxDBClient(host, port, database=dbname)

metrics_list = ['esphome-jbd-bms_state_of_charge',
                'esphome-jbd-bms_capacity_remaining',
                'esphome-jbd-bms_average_cell_voltage',
                'esphome-jbd-bms_delta_cell_voltage',
                'esphome-jbd-bms_current',
                'esphome-jbd-bms_temperature_2',
                'esphome-jbd-bms_cell_voltage_1',
                'esphome-jbd-bms_cell_voltage_2',
                'esphome-jbd-bms_cell_voltage_3',
                'esphome-jbd-bms_cell_voltage_4',
                'esphome-jbd-bms_cell_voltage_5',
                'esphome-jbd-bms_cell_voltage_6',
                'esphome-jbd-bms_cell_voltage_7',
                'esphome-jbd-bms_cell_voltage_8'
               ]

for i, m in enumerate(metrics_list):
    print('Processing: ', m)
    query= '''
    select value from 
    "''' + m + '''"
    where time >= '2023-11-07T12:20:00Z';
    '''
    name = m.split('-')[2]
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

rdf = rdf.resample('10s').mean()

rdf.to_parquet('data/bms_soc_data.parquet')

rdf.info()

