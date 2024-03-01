import json
import subprocess
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import pytz
import yaml
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

RYU_CONTROLLER_API = 'http://127.0.0.1:8080'
amount_of_switches = 20
is_loading = True

time_state = "REAL"

mock_time = datetime.now(pytz.utc)
is_moving = True
acceleration_coefficient = 1
network_bandwidth_config = {}
bandwidth_rules = []


def get_switches_ids(n):
    return [f"{i:016x}" for i in range(1, n + 1)]


def load_config():
    global network_bandwidth_config, bandwidth_rules
    with open("net_param_config.yaml", 'r') as stream:
        config = yaml.safe_load(stream)
        network_bandwidth_config = config.get('networkBandwidth', {}).get('default', {})
        if not any(key in network_bandwidth_config for key in ['maxRate', 'minRate']):
            raise ValueError("One of maxRate or minRate is mandatory in default settings")
        for rule in config.get('networkBandwidth', {}).get('timeBasedRules', []):
            if all(key in rule for key in ['daysOfWeek', 'timeRange']):
                if not any(key in rule.get('bandwidth', {}) for key in ['maxRate', 'minRate']):
                    raise ValueError("One of maxRate or minRate is mandatory in each rule")
                bandwidth_rules.append(rule)
            else:
                raise ValueError("daysOfWeek and timeRange are mandatory in each rule")


def set_switches(n):
    global is_loading
    switches = get_switches_ids(n)
    for switch_id in switches:
        connect_ovsdb_with_switch(switch_id)
        set_switch_queue_with_default_bandwidth(switch_id)
    is_loading = False


def set_switch_queue_with_default_bandwidth(switch_id):
    queue = {}
    if 'minRate' in network_bandwidth_config:
        queue['min_rate'] = str(network_bandwidth_config['minRate'])
    if 'maxRate' in network_bandwidth_config:
        queue['max_rate'] = str(network_bandwidth_config['maxRate'])
    queue_list = [queue]
    set_switch_queue_bandwidth(switch_id, queue_list)


def set_switch_queue_bandwidth(switch_id, queue_list):
    post_data = {
        "type": "linux-htb",
        "queues": queue_list
    }
    post_base_url = "http://localhost:8080/qos/queue/"
    post_url = f"{post_base_url}{switch_id}"
    post_command = f"curl -X POST -d '{json.dumps(post_data)}' {post_url}"
    subprocess.run(post_command, shell=True)


def connect_ovsdb_with_switch(switch_id):
    base_url = "http://localhost:8080/v1.0/conf/switches/"
    url = f"{base_url}{switch_id}/ovsdb_addr"
    put_data = "'\"tcp:127.0.0.1:6632\"'"
    command = f"curl -X PUT -d {put_data} {url}"
    subprocess.run(command, shell=True)


with app.app_context():
    global is_loaded
    load_config()
    set_switches(amount_of_switches)


def get_applicable_rule(t):
    current_day = t.strftime('%A')
    current_hour_minute = t.strftime('%H:%M')
    for rule in bandwidth_rules:
        days_of_week = rule['daysOfWeek']
        time_range = rule['timeRange']

        if current_day in days_of_week:
            start_time = time_range['start']
            end_time = time_range['end']

            if start_time <= current_hour_minute <= end_time or (
                    start_time > end_time and (current_hour_minute >= start_time or current_hour_minute <= end_time)):
                return rule

    return None


def apply_bandwidth_rule():
    print("Job is running. Searching for rule...")
    global is_loading
    if is_loading:
        return
    current_time = calculate_time()
    rule = get_applicable_rule(current_time)
    if rule is None:
        for switch_id in get_switches_ids(amount_of_switches):
            set_switch_queue_with_default_bandwidth(switch_id)
    else:
        if 'bandwidth' in rule:
            queue = {}
            if 'minRate' in rule['bandwidth']:
                queue['min_rate'] = str(rule['bandwidth']['minRate'])
            if 'maxRate' in rule['bandwidth']:
                queue['max_rate'] = str(rule['bandwidth']['maxRate'])
            queue_list = [queue]
            for switch_id in get_switches_ids(amount_of_switches):
                set_switch_queue_bandwidth(switch_id, queue_list)


scheduler = BackgroundScheduler()
scheduler.add_job(func=apply_bandwidth_rule, trigger="interval", seconds=120)
scheduler.start()


def calculate_time():
    if time_state == "REAL":
        return datetime.now(pytz.utc)
    else:
        if is_moving:
            time_diff = (datetime.now(pytz.utc) - mock_time).total_seconds()
            adjusted_time = mock_time + timedelta(seconds=time_diff * acceleration_coefficient)
            return adjusted_time
        else:
            return mock_time


@app.route('/state', methods=['GET'])
def set_state():
    global time_state
    return jsonify({"state": time_state}), 200


@app.route('/state', methods=['PUT'])
def update_state():
    global time_state
    data = request.json
    if 'state' in data and data['state'] in ['REAL', 'MOCK']:
        time_state = data['state']
        return jsonify({"message": "Time state updated successfully.", "state": time_state}), 200
    else:
        return jsonify({"error": "Invalid state. Use 'REAL' or 'MOCK'."}), 400


@app.route('/mock-time', methods=['PUT'])
def set_mock_time():
    global mock_time, is_moving, acceleration_coefficient
    data = request.json
    try:
        if 'dateTime' in data:
            mock_time = datetime.fromisoformat(data['dateTime']).astimezone(pytz.utc)
        if 'isMoving' in data:
            is_moving = data['isMoving']
        if 'accelerationCoefficient' in data:
            acceleration_coefficient = int(data['accelerationCoefficient'])
        return jsonify({"message": "Mock time settings updated successfully."}), 200
    except ValueError:
        return jsonify({"error": "Invalid input."}), 400


@app.route('/time', methods=['GET'])
def get_time():
    return jsonify({"currentTime": calculate_time().isoformat()}), 200


if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=9000)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
