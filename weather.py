'''
    This script serves as the backend to a to-do list app.
    The purpose of this script is to pull data (tasks) from a file.
    If a task has is to be performed on the current date, it is added
    to an active tasks list.  This script will also have the ability to
    accept requests/POST to acknowledge that a task has been completed.
    Author: Donovan Torgerson
    Email: Donovan@Torgersonlabs.com
'''
# built-in imports
import json
from pprint import pprint # for debugging only
import sys
import time

# external imports
import arrow
from flask import Flask, abort, jsonify
from flask_caching import Cache
from flask_cors import CORS, cross_origin
import requests
from webargs.flaskparser import FlaskParser, use_kwargs
from webargs import *

# user defined modules
# sys.path.insert(0, '/home/dusr/common')
import common.logger


app = Flask(__name__)
cache = Cache(config={'CACHE_TYPE': 'simple'})
cache.init_app(app)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
CORS(app)
parser = FlaskParser()

# Dictionary of all errors for easier reuse.
errors = {
    # common
    1: 'Invalid version.',
    2: 'User not found.',
    3: 'Error validating user_id.',
    4: 'Invalid Request: user_id must be a valid UUID.',
    5: 'Invalid Request: user_id is required.',
    # weather specific
    6: 'Invalid Request: location must be in the format <latitude>,<longitude>.',
    7: 'Invalid Request: location is required and cannot be empty.',
    8: 'Invalid Request: location cannot contain more than one latitude, longitude pair.',
    9: 'Invalid Request: non-numeric {} provided',
    10: 'Invalid Request: Latitude must be between -90 and 90.',
    11: 'Invalid Request: Longitude must be between -360 and 360.',
    12: 'Error validating location.',
    13: 'Error retrieving weather data.'
}

# Hardcode account_id's
# TODO: Implement database to store this information
users = None
f = open('users.json', 'r')
users = f.read()
users = json.loads(users)

print(users)
print(type(users))

@app.errorhandler(422)
def custom_handler(error):
    errs = []
    if 'user_id' in error.data['messages']:
        if 'Not a valid UUID.' in error.data['messages']['user_id']:
            errs.append('Invalid Request: user_id must be a valid UUID.')
        if 'Missing data for required field.' in error.data['messages']['user_id']:
            errs.append('Invalid Request: user_id is required.')
    if 'location' in error.data['messages']:
        if 'Missing data for required field.' in error.data['messages']['location']:
            errs.append('Invalid Request: location is required.')
    if 'unitcode' in error.data['messages']:
        if 'Missing data for required field.' in error.data['messages']['unitcode']:
            errs.append('Invalid Request: unitcode is required.')
    return str(errs), 400


# Setup logging
# weather_log = logger.get_logger('logger', './weather.log')

# uses lat,lon
points_url = 'https://api.weather.gov/points/{},{}'
# uses grid points obtained from points_url (gridX,gridY)
raw_forecast_url = 'https://api.weather.gov/gridpoints/TOP/{},{}'
weekly_forecast_url = 'https://forecast-v3.weather.gov/point/{},{}?view=plain&mode=min'
map_click_url = 'https://forecast.weather.gov/MapClick.php?lat={}&lon={}&unit={}&lg=english&FcstType=json'
metar_url = 'https://w1.weather.gov/data/METAR/{}.1.txt'
astronomical_url = 'https://api.usno.navy.mil/rstt/oneday?date={}&coords={},{}&tz={}'


weather_args = {
    "location": fields.String(required=True, location="query"),
    "map_click": fields.String(allow_missing=True, location="query"),
    "metar": fields.String(allow_missing=True, location="query"),
    "pp": fields.String(allow_missing=True, location="query"),
    "unitcode": fields.String(missing='us-std', location="query", \
                              validate=lambda v: str(v) in ['si-std', 'us-std']),
    "user_id": fields.UUID(required=True, location="query")
}


@cache.cached(timeout=1800) # 30 minutes * 60 seconds/min = 1800
@app.route('/<version>/weather', methods=['GET'], strict_slashes=False)
@cross_origin(origins='*')
@use_kwargs(weather_args)
def get_weather(version, **kwargs):
    curr_time = arrow.now('US/Mountain')
    offset = curr_time.format('ZZ')
    offset_hours, offset_minutes = offset.split(':')

    with open('icon_classes.json') as json_data:
        icon_classes = json.load(json_data,)

    # check for valid version
    if version != 'v1.0':
        abort(400, errors[1])

    # check for valid user_id
    try:
        assert str(kwargs['user_id']) in users, errors[2]
    except AssertionError as e:
        weather_log.error(e)
        abort(400, e)
    except Exception as e:
        weather_log.error(e)
        abort(400, errors[3])

    # check for valid location
    try:
        assert type(kwargs['location']) == str, errors[6]
        loc = kwargs['location'].replace(' ', '').split(',')

        assert len(loc) == 2, errors[8]

        lat = loc[0]
        lon = loc[1]

        assert float(lat), errors[9].format('longitude')
        assert float(lon), errors[9].format('latitude')
        assert -90.0 <= float(lat) <= 90.0, errors[10]
        assert -360 <= float(lon) <= 360.0, errors[11]
    except AssertionError as e:
        weather_log.error(e)
        abort(400, e)
    except Exception as e:
        weather_log.error(e)
        abort(400, errors[12])

    # TODO separate these so multiple can be called in a single request (all separate if statements)
    urls = {}
    # Choose url
    if 'metar' in kwargs:
        # TODO fingure out how to perform a lookup to obtain this
        # hard coded for now
        urls['metar'] = metar_url.format('KRAP')
    elif 'raw_forecast' in kwargs:
        urls['points'] = points_url
        # uses grid points obtained from points_url (gridX,gridY)
        raw_forecast_url = 'https://api.weather.gov/gridpoints/TOP/{},{}'
    elif 'weekly_forecast' in kwargs:
        urls['weekly_forecast'] = weekly_forecast_url
    elif 'map_click':
        urls['map_click'] = map_click_url.format(lat, lon, kwargs['unitcode'])
    else:
        urls['map_click'] = map_click_url.format(lat, lon, kwargs['unitcode'])

    # retrieve data from url
    try:
        raw_data = {}
        for key, val in urls.items():
            response = requests.get(val)
            assert response.status_code == 200
            if key == 'metar':
                raw_data[key] = response.text
            elif key == 'map_click':
                response_json = response.json()
                raw_data = {
                    'created': response_json['creationDateLocal'],
                    'observation': response_json['currentobservation'],
                    'icon_type': 'n/a'
                }

                for wx_condition in icon_classes:
                    if raw_data['observation']['Weather'] in icon_classes[wx_condition]:
                        raw_data['icon_type'] = wx_condition
                        break

                astro_response = requests.get(astronomical_url.format(curr_time.format('MM/DD/YYYY'), \
                                              lat, lon, offset_hours))
                assert astro_response.status_code == 200
                raw_astro = astro_response.json()
                raw_data['moon'] = {
                    'phase': raw_astro['closestphase']['phase'],
                    'rise': 'n/a',
                    'set': 'n/a'
                }
                raw_data['sun'] = {
                    'rise': 'n/a',
                    'set': 'n/a'
                }
                raw_data['moon_phase'] = raw_astro['closestphase']['phase']
                for item in raw_astro['moondata']:
                    if item['phen'] == 'R':
                        if is_valid_time(item['time']):
                            raw_data['moon']['rise'] = item['time']
                    elif item['phen'] == 'S':
                        if is_valid_time(item['time']):
                            raw_data['moon']['set'] = item['time']
                for item in raw_astro['sundata']:
                    if item['phen'] == 'R':
                        if is_valid_time(item['time']):
                            raw_data['sun']['rise'] = item['time']
                    elif item['phen'] == 'S':
                        if is_valid_time(item['time']):
                            raw_data['sun']['set'] = item['time']
            else:
                raw_data[key] = response.json()
    except AssertionError as e:
        weather_log.error(e)
        abort(400, errors[13])
    except Exception as e:
        print(e)
        weather_log.error(e)
        abort(400, e)

    if 'pp' in kwargs:
        return jsonify(raw_data)

    pprint(raw_data)

    return json.dumps(raw_data)


current_conditions_args = {
    "location": fields.String(required=True, location="query"),
    "map_click": fields.String(allow_missing=True, location="query"),
    "metar": fields.String(allow_missing=True, location="query"),
    "pp": fields.String(allow_missing=True, location="query"),
    "unitcode": fields.String(missing='us-std', location="query", \
                              validate=lambda v: str(v) in ['si-std', 'us-std']),
    "user_id": fields.UUID(required=True, location="query")
}


@cache.cached(timeout=1800) # 30 minutes * 60 seconds/min = 1800
@app.route('/<version>/wx/current/', methods=['GET'], strict_slashes=False)
@cross_origin(origins='*')
@use_kwargs(current_conditions_args)
def get_current_conditions(version, **kwargs):
    curr_time = arrow.now('US/Mountain')
    offset = curr_time.format('ZZ')
    offset_hours, offset_minutes = offset.split(':')

    with open('icon_classes.json') as json_data:
        icon_classes = json.load(json_data,)

    # check for valid version
    if version != 'v1.0':
        abort(400, errors[1])

    # check for valid user_id
    try:
        assert str(kwargs['user_id']) in users, errors[2]
    except AssertionError as e:
        weather_log.error(e)
        abort(400, e)
    except Exception as e:
        weather_log.error(e)
        abort(400, errors[3])

    # check for valid location
    try:
        assert type(kwargs['location']) == str, errors[6]
        loc = kwargs['location'].replace(' ', '').split(',')

        assert len(loc) == 2, errors[8]

        lat = loc[0]
        lon = loc[1]

        assert float(lat), errors[9].format('longitude')
        assert float(lon), errors[9].format('latitude')
        assert -90.0 <= float(lat) <= 90.0, errors[10]
        assert -360 <= float(lon) <= 360.0, errors[11]
    except AssertionError as e:
        weather_log.error(e)
        abort(400, e)
    except Exception as e:
        weather_log.error(e)
        abort(400, errors[12])

    # retrieve data from url
    try:
        raw_data = {}
        url = map_click_url.format(lat, lon, kwargs['unitcode'])
        response = requests.get(url)
        assert response.status_code == 200
        response_json = response.json()
        raw_data = {
            'created': response_json['creationDateLocal'],
            'observation': response_json['currentobservation'],
            'icon_type': 'n/a',
            'unitcode': kwargs['unitcode']
        }

        for wx_condition in icon_classes:
            if raw_data['observation']['Weather'] in icon_classes[wx_condition]:
                raw_data['icon_type'] = wx_condition
                break

        # TODO make this a separate function (may be used elsewhere)
        astro_response = requests.get(astronomical_url.format(curr_time.format('MM/DD/YYYY'), \
                                      lat, lon, offset_hours))
        assert astro_response.status_code == 200
        raw_astro = astro_response.json()
        raw_data['moon'] = {
            'phase': raw_astro['closestphase']['phase'],
            'rise': 'n/a',
            'set': 'n/a'
        }
        raw_data['sun'] = {
            'rise': 'n/a',
            'set': 'n/a'
        }
        raw_data['moon_phase'] = raw_astro['closestphase']['phase']
        for item in raw_astro['moondata']:
            if item['phen'] == 'R':
                if is_valid_time(item['time']):
                    raw_data['moon']['rise'] = item['time']
            elif item['phen'] == 'S':
                if is_valid_time(item['time']):
                    raw_data['moon']['set'] = item['time']
        for item in raw_astro['sundata']:
            if item['phen'] == 'R':
                if is_valid_time(item['time']):
                    raw_data['sun']['rise'] = item['time']
            elif item['phen'] == 'S':
                if is_valid_time(item['time']):
                    raw_data['sun']['set'] = item['time']
    except AssertionError as e:
        weather_log.error(e)
        abort(400, errors[13])
    except Exception as e:
        weather_log.error(e)
        abort(400, e)

    if 'pp' in kwargs:
        return jsonify(raw_data)

    return json.dumps(raw_data)


# Helper functions
def is_valid_time(item):
    try:
        time.strptime(item, '%H:%M')
        return True
    except:
        return False
