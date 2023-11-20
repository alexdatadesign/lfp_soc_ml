# stripped down version for model training
import pandas as pd
import xgboost as xgb
import numpy as np
from sklearn.model_selection import train_test_split 
from sklearn.metrics import mean_squared_error as MSE 

# time series data with 10 sec interval

df = pd.read_parquet('data/bms_soc_data.parquet')

# Attempt to calculate SOC as accurate as we can
# the internal current sensor is not accurate and has different error on charge and discharge
# we need to detect voltage peaks and reset SOC to 100%  
# it's a moment when we have average voltage at 3.43 and then drop below 3.37 (reset condition)

df2 = df.copy()

df2['reset_cond'] = df2.bms_average_cell_voltage > 3.43
df2['reset_cond2'] = df2.bms_average_cell_voltage.rolling(5).mean() < 3.37
df2['reset_cond'] = df2.reset_cond.shift(100) & df2.reset_cond2
df2['reset_cond2'] = (df2.reset_cond.shift(1) == 1) & (df2.reset_cond == 0)
df2['cycle'] = df2.reset_cond2.cumsum().astype('int32')
df2['cycle_row'] = df2.groupby(['cycle']).cumcount()
df2['reset_cond'] = df2['reset_cond'].astype('float16') * 10

# drop non complete cycles
max_cycle = df2.cycle.max()
df2 = df2.loc[ (df2.cycle > 0) & (df2.cycle < max_cycle)]

# coulombic efficiency of a lfp battery is about 0.99
coulombic_efficiency = 0.99

discharge_sum = df2[df2.bms_current < 0].bms_current.sum()
charge_sum = df2[df2.bms_current > 0].bms_current.sum()
corr_k = charge_sum * coulombic_efficiency / -discharge_sum

print("Corr k: ", corr_k)


def correct(x):
    if x < 0:
        return x * corr_k
    return x

df2.loc[:,'bms_current_corrected'] = df2['bms_current'].apply(correct).copy()

# calculated SOC
max_capacity = 510.0
df2.loc[:,'calculated_soc'] = (( ( df2.groupby(['cycle'])['bms_current_corrected'].cumsum()/360) + max_capacity) / max_capacity) * 100.0
df2.loc[:,'calculated_soc'] = df2.calculated_soc.clip(0, 100.0)

df2 = df2.drop(columns=['reset_cond', 'reset_cond2'])


# Select only trusted data (24h after SOC reset)
cycles_row_max = 24 * 60 * 60 / 10 
df2 = df2.loc[df2.cycle_row < cycles_row_max]


# # Training

df2['soc_d'] = df2.calculated_soc.shift(90)

df2['roll_v_10'] = df2.bms_average_cell_voltage.rolling(10).mean()
df2['roll_c_10'] = df2.bms_current.rolling(10).mean()
df2['roll_cs_90'] = df2.bms_current.rolling(90).sum()
df2['roll_v_90'] = df2.bms_average_cell_voltage.rolling(90).mean()
df2['roll_c_90'] = df2.bms_current.rolling(90).mean()
df2['temp_roll_90'] = df2.bms_temperature_2.rolling(90).mean()


df2 = df2.dropna()

model = xgb.XGBRegressor(n_estimators=250, max_depth=10, eta=0.3, subsample=0.7, colsample_bytree=0.8)

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

y = df2['calculated_soc']

train_X, test_X, train_y, test_y = train_test_split(X, y, test_size = 0.3, random_state = 42) 

model.fit(train_X, train_y)


# Predict on test data
pred = model.predict(test_X) 
pred = pred.clip(0, 100.0)

model.save_model('soc_model.json')

# RMSE Computation 
rmse = np.sqrt(MSE(test_y, pred)) 
print("RMSE : % f" %(rmse)) 

