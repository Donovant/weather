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
import requests
from webargs.flaskparser import parser, use_kwargs
from webargs import *

# user defined modules
from common import logger
from common.error_handling import get_error

app = Flask(__name__)
cache = Cache(config={'CACHE_TYPE': 'simple'})
cache.init_app(app)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024


# Hardcode account_id's
# TODO: Implement database to store this information
users = None
f = open('users.json', 'r')
users = json.loads(f.read())


@app.errorhandler(422)
def custom_handler(error):

    content_type = 'application/json; charset=utf8'
    index_log.info(error)
    custom_errors = {}

    for arg in error.data['messages']:
        if isinstance(error.data['messages'][arg], list):
            for item in error.data['messages'][arg]:
                custom_errors[arg] = item
        if isinstance(error.data['messages'][arg], dict):
            custom_errors.update(error.data['messages'][arg])

    return json.dumps(custom_errors), 400


# Setup logging
weather_log = logger.get_logger('logger', './weather.log')

# uses lat,lon
points_url = 'https://api.weather.gov/points/{},{}'
# uses grid points obtained from points_url (gridX,gridY)
raw_forecast_url = 'https://api.weather.gov/gridpoints/TOP/{},{}'
weekly_forecast_url = 'https://forecast-v3.weather.gov/point/{},{}?view=plain&mode=min'
map_click_url = 'https://forecast.weather.gov/MapClick.php?lat={}&lon={}&unit={}&lg=english&FcstType=json'
metar_url = 'https://w1.weather.gov/data/METAR/{}.1.txt'
# This may me deprecated...
# astronomical_url = 'https://api.usno.navy.mil/rstt/oneday?date={}&coords={},{}&tz={}'


weather_args = {
    "location": fields.String(
        required=True,
        location="query",
        error_messages={
            "null": get_error('02x006'),
            "required": get_error('02x007'),
            "invalid_uuid": get_error('02x006'),
            "type": get_error('02x006')
            # Unused error messages
            # "validator_failed": get_error('02x006'),
        }
    ),
    "map_click": fields.String(
        allow_missing=True,
        location="query",
        error_messages={
            "null": error['02x016'],
            "required": error['02x016'],
            "invalid_uuid": error['02x016'],
            "type": error['02x016']
            # Unused error messages
            # "validator_failed": error['02x016'],
        }
    ),
    "metar": fields.String(
        allow_missing=True,
        location="query",
        error_messages={
            "null": error['02x015'],
            "required": error['02x015'],
            "invalid_uuid": error['02x015'],
            "type": error['02x015']
            # Unused error messages
            # "validator_failed": error['02x015'],
        }
    ),
    "unitcode": fields.String(
        missing='us-std',
        location="query",
        validate=lambda v: str(v) in ['si-std', 'us-std'],
        error_messages={
            "null": error['02x014'],
            "required": error['02x014'],
            "invalid_uuid": error['02x014'],
            "type": error['02x014']
            "validator_failed": error['02x014'],
        }
    ),
    "user_id": fields.UUID(
        required=True,
        location="query",
        error_messages={
            "null": get_error('02x004'),
            "required": get_error('02x005'),
            "invalid_uuid": get_error('02x004'),
            "type": get_error('02x004')
            # Unused error messages
            # "validator_failed": get_error('02x004'),
        }
    ),
    ## -- internal use only
    "pp": fields.String(
        allow_missing=True,
        location="query"
    )
}


@cache.cached(timeout=1800) # 30 minutes * 60 seconds/min = 1800
@app.route('/<version>/weather', methods=['GET'], strict_slashes=False)
@use_kwargs(weather_args)
def get_weather(version, **kwargs):
    curr_time = arrow.now('US/Mountain')
    offset = curr_time.format('ZZ')
    offset_hours, offset_minutes = offset.split(':')

    with open('icon_classes.json') as json_data:
        icon_classes = json.load(json_data,)

    # check for valid version
    if version != 'v1.0':
        abort(400, get_error('02x001'))

    # check for valid user_id
    try:
        assert str(kwargs['user_id']) in users, get_error('02x002')
    except AssertionError as e:
        weather_log.error(e)
        abort(400, e)
    except Exception as e:
        weather_log.error(e)
        abort(400, get_error('02x003'))

    # check for valid location
    try:
        assert type(kwargs['location']) == str, get_error('02x006')
        loc = kwargs['location'].replace(' ', '').split(',')

        assert len(loc) == 2, get_error('02x008')

        lat = loc[0]
        lon = loc[1]

        assert float(lat), get_error('02x009', arg='longitude')
        assert float(lon), get_error('02x009', arg='latitude')
        assert -90.0 <= float(lat) <= 90.0, get_error('02x010')
        assert -360 <= float(lon) <= 360.0, getget_error('02x011')
    except AssertionError as e:
        weather_log.error(e)
        abort(400, e)
    except Exception as e:
        weather_log.error(e)
        abort(400, get_error('02x012'))

    # TODO separate these so multiple can be called in a single request (all separate if statements)
    urls = {}
    # Choose url
    if 'metar' in kwargs:
        # TODO figure out how to perform a lookup to obtain this
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

                ##  -- This has been commented out due to ongoing upgrades/deprecation of
                ##     the api.usno.navy.mil endpoint.
                # astro_response = requests.get(astronomical_url.format(curr_time.format('MM/DD/YYYY'), \
                #                               lat, lon, offset_hours))
                # assert astro_response.status_code == 200
                # raw_astro = astro_response.json()
                # raw_data['moon'] = {
                #     'phase': raw_astro['closestphase']['phase'],
                #     'rise': 'n/a',
                #     'set': 'n/a'
                # }
                # raw_data['sun'] = {
                #     'rise': 'n/a',
                #     'set': 'n/a'
                # }
                # raw_data['moon_phase'] = raw_astro['closestphase']['phase']
                # for item in raw_astro['moondata']:
                #     if item['phen'] == 'R':
                #         if is_valid_time(item['time']):
                #             raw_data['moon']['rise'] = item['time']
                #     elif item['phen'] == 'S':
                #         if is_valid_time(item['time']):
                #             raw_data['moon']['set'] = item['time']
                # for item in raw_astro['sundata']:
                #     if item['phen'] == 'R':
                #         if is_valid_time(item['time']):
                #             raw_data['sun']['rise'] = item['time']
                #     elif item['phen'] == 'S':
                #         if is_valid_time(item['time']):
                #             raw_data['sun']['set'] = item['time']
            else:
                raw_data[key] = response.json()
    except AssertionError as e:
        weather_log.error(e)
        abort(400, get_error('02x013'))
    except Exception as e:
        weather_log.error(e)
        abort(400, e)

    if 'pp' in kwargs:
        return jsonify(raw_data)

    pprint(raw_data)

    return json.dumps(raw_data)


current_conditions_args = {
    "location": fields.String(
        required=True,
        location="query",
        error_messages={
            "null": get_error('02x006'),
            "required": get_error('02x007'),
            "invalid_uuid": get_error('02x006'),
            "type": get_error('02x006')
            # Unused error messages
            # "validator_failed": get_error('02x006'),
        }
    ),
    "map_click": fields.String(
        allow_missing=True,
        location="query",
        error_messages={
            "null": get_error('02x016'),
            "required": get_error('02x016'),
            "invalid_uuid": get_error('02x016'),
            "type": get_error('02x016')
            # Unused error messages
            # "validator_failed": get_error('02x016'),
        }
    ),
    "metar": fields.String(
        allow_missing=True,
        location="query",
        error_messages={
            "null": get_error('02x015'),
            "required": get_error('02x015'),
            "invalid_uuid": get_error('02x015'),
            "type": get_error('02x015')
            # Unused error messages
            # "validator_failed": get_error('02x015'),
        }
    ),
    "pp": fields.String(
        allow_missing=True,
        location="query"
    ),
    "unitcode": fields.String(
        missing='us-std',
        location="query",
        validate=lambda v: str(v) in ['si-std', 'us-std'],
        error_messages={
            "null": get_error('02x014'),
            "required": get_error('02x014'),
            "invalid_uuid": get_error('02x014'),
            "type": get_error('02x014'),
            "validator_failed": get_error('02x014'),
        }
    ),
    "user_id": fields.UUID(
        required=True,
        location="query",
        error_messages={
            "null": get_error('02x004'),
            "required": get_error('02x005'),
            "invalid_uuid": get_error('02x004'),
            "type": get_error('02x004')
            # Unused error messages
            # "validator_failed": get_error('02x004'),
        }
    )
}


@cache.cached(timeout=1800) # 30 minutes * 60 seconds/min = 1800
@app.route('/<version>/wx/current/', methods=['GET'], strict_slashes=False)
@use_kwargs(current_conditions_args)
def get_current_conditions(version, **kwargs):
    curr_time = arrow.now('US/Mountain')
    offset = curr_time.format('ZZ')
    offset_hours, offset_minutes = offset.split(':')

    with open('icon_classes.json') as json_data:
        icon_classes = json.load(json_data,)

    # check for valid version
    if version != 'v1.0':
        abort(400, get_error('02x001'))

    # check for valid user_id
    try:
        assert str(kwargs['user_id']) in users, errors['02x002']
    except AssertionError as e:
        weather_log.error(e)
        abort(400, e)
    except Exception as e:
        weather_log.error(e)
        abort(400, get_error('02x003'))

    # check for valid location
    try:
        assert type(kwargs['location']) == str, errors['02x006']
        loc = kwargs['location'].replace(' ', '').split(',')

        assert len(loc) == 2, get_error('02x008')

        lat = loc[0]
        lon = loc[1]

        assert float(lat), get_error('02x009', arg='longitude')
        assert float(lon), get_error('02x009', arg='latitude')
        assert -90.0 <= float(lat) <= 90.0, get_error('02x010')
        assert -360 <= float(lon) <= 360.0, get_error('02x011')
    except AssertionError as e:
        weather_log.error(e)
        abort(400, e)
    except Exception as e:
        weather_log.error(e)
        abort(400, get_error('02x012'))

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
        abort(400, get_error('02x013'))
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
