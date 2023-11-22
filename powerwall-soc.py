# PowerWall minimal version
# only tracks battery SOC
# and apply corrections from predicted SOC values

import os
import sys
import subprocess
import string
import time
import logging

import paho.mqtt.client as mqtt

logging.basicConfig(format='%(message)s', level=logging.INFO)

logging.info("PowerWall controller\n")

mqtt_host = "mqtt.local"
mqtt_port = 1883
verbosity = 2

message_cache = {}

PWS_NOOP = 0
PWS_PAUSE_CHARGE = 1
PWS_CHARGE = 2
PWS_DISCHARGE = 3
PWS_CHARGED = 4
PWS_FLOAT = 5

pw_state = PWS_CHARGE # PWS_NOOP

bms_current = 0
MAX_BATTERY_CAPACITY_AH = 510.0
AH_DIV = 1800 # we are getting updates every 2 seconds
bms_current_intergrated = 0
bms_ci_initialized = False
bms_soc = -1
soc = 0
# from jupyter notebook, correction coefficient for negative current (shunt)
n_k = 1.0881865322015205

# subscribe to BMS updates
mqtt_prefix = "pw/"
mqtt_prefix_subscribe = "pw/#"
mqtt_bms_topic_prefix = "eh/esphome-jbd-bms/sensor/+/state"

mqtt_bms_cell_max_voltage = "eh/esphome-jbd-bms/sensor/esphome-jbd-bms_max_cell_voltage/state"

mqtt_bms_current = "eh/esphome-jbd-bms/sensor/esphome-jbd-bms_current/state"
mqtt_bms_soc = "eh/esphome-jbd-bms/sensor/esphome-jbd-bms_state_of_charge/state"
mqtt_soc_predicted = "eh/esphome-jbd-bms/sensor/bms_soc_predicted/state"



def connecthandler(mqc,userdata,flags,rc):
    if rc == 0:
        mqc.initial_connection_made = True
        if verbosity>=2:
            logging.info("MQTT Broker connected succesfully: " + mqtt_host + ":" + str(mqtt_port))
        mqc.subscribe(mqtt_bms_topic_prefix)
        mqc.subscribe(mqtt_prefix_subscribe)
        if verbosity>=2:
            logging.info("Subscribed to MQTT topic: " + mqtt_prefix_subscribe)
        #mqc.publish(globaltopic + "connected", "True", qos=1, retain=True)
    elif rc == 1:
        if verbosity>=1:
            logging.info("MQTT Connection refused – incorrect protocol version")
    elif rc == 2:
        if verbosity>=1:
            logging.info("MQTT Connection refused – invalid client identifier")
    elif rc == 3:
        if verbosity>=1:
            logging.info("MQTT Connection refused – server unavailable")
    elif rc == 4:
        if verbosity>=1:
            logging.info("MQTT Connection refused – bad username or password")
    elif rc == 5:
        if verbosity>=1:
            logging.info("MQTT Connection refused – not authorised")

def disconnecthandler(mqc,userdata,rc):
    if verbosity >= 2:
        logging.info("MQTT Disconnected, RC:"+str(rc))

def loghandler(mgc, userdata, level, buf):
    if verbosity >= 4:
        logging.info("MQTT LOG:" + buf)

def messagehandler(mqc,userdata,msg):
    global pw_state, soc, bms_current, util_current_inv1, bms_current_intergrated, bms_ci_initialized
    global bms_soc
    if msg.payload.decode('ascii', 'replace') == 'nan':
        #logging.info("Skipping nan value for topic: " + msg.topic)
        return
    message_cache[msg.topic] = msg

    if msg.topic == mqtt_soc_predicted:
        soc_predicted = float(msg.payload.decode('ascii', 'replace'))
        correction = soc_predicted - soc
        # constrain corrections to a reasonable updates
        correction = min(10.0, max(-10.0, correction))
        print('> Predicted SOC = ', soc_predicted, ' Correction: ', correction)
        bms_current_intergrated = bms_current_intergrated + correction * MAX_BATTERY_CAPACITY_AH * 0.05 / 100.0 # to be adjusted

    if msg.topic == mqtt_bms_current:
        bms_current = float(msg.payload.decode('ascii', 'replace'))
        bms_current_corrected = bms_current
        if bms_current < 0:
            bms_current_corrected = bms_current * n_k
        bms_current_intergrated = bms_current_intergrated + bms_current_corrected / AH_DIV
        if bms_current_intergrated < 0:
            bms_current_intergrated = 0
        if bms_current_intergrated > MAX_BATTERY_CAPACITY_AH:
            bms_current_intergrated = MAX_BATTERY_CAPACITY_AH

        # Calculate SOC from bms_current_intergrated
        soc = bms_current_intergrated * 100.0 / MAX_BATTERY_CAPACITY_AH
        if bms_ci_initialized:
            print("   ")
            print("BMS SOC: ", bms_soc, " SOC: ", str(round(soc,3))," current integrated: ", bms_current_intergrated, " current: ", bms_current)
            mqc.publish(mqtt_prefix + "bms_current_integrated", bms_current_intergrated, retain=True)
            mqc.publish(mqtt_prefix + "soc", soc, retain=True)
            mqc.publish("eh/esphome-jbd-bms/sensor/__current_integrated/state", bms_current_intergrated)
            mqc.publish("eh/esphome-jbd-bms/sensor/__soc/state", soc)

    if msg.topic == mqtt_bms_cell_max_voltage:
        max_cell_voltage = float(msg.payload.decode('ascii', 'replace'))
        print("Max BMS cell voltage = ", max_cell_voltage)

        if max_cell_voltage >= 3.44 and bms_current < 10 and pw_state != PWS_FLOAT:
            bms_current_intergrated = MAX_BATTERY_CAPACITY_AH
            pw_state = PWS_FLOAT
            print(" **** BATTERY IS FULLY CHARGED - SWITCHING TO FLOAT MODE **** ")
            mqc.publish(mqtt_prefix + "state", "FLOAT CHARGE", retain=True)

        if max_cell_voltage <= 3.33 and pw_state == PWS_FLOAT:
            pw_state = PWS_CHARGE
            print(" **** INV2: CHARGE STATE SET **** ")
            mqc.publish(mqtt_prefix + "state", "CHARGE ENABLED", retain=True)

    if msg.topic == mqtt_bms_soc:
        bms_soc = int(msg.payload.decode('ascii', 'replace'))

    if msg.topic == "pw/bms_current_integrated/set":
        bms_current_intergrated = float(msg.payload.decode('ascii', 'replace'))
        bms_ci_initialized = True

    if msg.topic == "pw/bms_current_integrated" and msg.retain == True:
        logging.info(">>>>> Updating bms_current_intergrated with retained message")
        bms_current_intergrated = float(msg.payload.decode('ascii', 'replace'))
        bms_ci_initialized = True





################################################################################################

mqc = mqtt.Client()

mqc.on_connect = connecthandler
mqc.on_message = messagehandler
mqc.on_disconnect = disconnecthandler
mqc.on_log = loghandler
#mqc.will_set(mqtt_prefix+"connected","False",qos=2,retain=True)

mqc.connect(mqtt_host, mqtt_port, 60)
mqc.initial_connection_attempted = True # Once we have connected the mqc loop will take care of reconnections
mqc.loop_start()


while True:
    # main controller loop

    #logging.info("State: " + str(pw_state))
    time.sleep(2)
