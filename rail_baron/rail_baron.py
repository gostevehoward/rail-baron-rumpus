#!/usr/bin/env python

import collections
import csv
import logging
import os
import random

import jinja2
import werkzeug.exceptions
from werkzeug import routing
import werkzeug.serving
from werkzeug import wrappers
import werkzeug.utils

class JinjaWrapper(object):
    def __init__(self, jinja_environment, base_context=None):
        self._jinja_environment = jinja_environment
        self._base_context = base_context or {}

    def render_template(self, template_name, environment=None, mime_type='text/html'):
        if environment is None:
            environment = {}
        template = self._jinja_environment.get_template(template_name)
        context = dict(self._base_context, **environment)
        return wrappers.Response(template.render(**context), mimetype=mime_type)

DiceRoll = collections.namedtuple('DiceRoll', ['odd_or_even', 'number'])

class DataSource(object):
    def __init__(self, data_maps):
        self._data_maps = data_maps

    @classmethod
    def from_csv(cls, stream):
        data_maps = collection.defaultdict(lambda: {})
        reader = csv.DictReader(stream)
        for row in reader:
            region_map = data_maps[row['region']]
            region_map[DiceRoll(row['odd/even'], row['number'])] = row['name']
        return cls(data_maps)

    def _roll_dice(self):
        return DiceRoll(
            random.choice('odd', 'even'),
            random.randrange(1, 7) + random.randrange(1, 7),
        )

    def pick_region(self):
        return self._data_maps['area'][self._roll_dice()]

    def pick_city(self, region):
        return self._data_maps[region][self._roll_dice()]

class RequestHandler(object):
    def __init__(self, request, urls, jinja_wrapper, data_source):
        self._request = request
        self._urls = urls
        self._jinja_wrapper = jinja_wrapper
        self._data_source = data_source

    def index(self):
        return self._jinja_wrapper.render_template('index.html')

    def get_region(self):
        region = self._data_source.pick_region()
        logging.info('Picked region {}'.format(region))
        return self._jinja_wrapper.render_template('show_region.html', {'region': region})

    def get_city(self, region):
        city = self._data_source.pick_city(region)
        logging.info('Picked city {} for region {}'.format(city, region))
        return self._jinja_wrapper.render_template(
            'show_city.html',
            {'region': region, 'city': city},
        )

class RailBaronApp(object):
    def __init__(self, jinja_environment, data_source):
        self._jinja_environment = jinja_environment
        self._data_source = data_source

        self._url_map = routing.Map(
            [
                routing.Rule('/', endpoint='index', methods=['GET']),
                routing.Rule('/get_region', endpoint='get region', methods=['GET']),
                routing.Rule('/<region>/get_city', endpoint='get city', methods=['GET']),
            ]
        )
        self._endpoints = {
            'index': RequestHandler.index,
            'get region': RequestHandler.get_region,
            'get city': RequestHandler.get_city,
        }

    @wrappers.Request.application
    def __call__(self, request):
        adapter = self._url_map.bind_to_environ(request.environ)
        jinja_wrapper = JinjaWrapper(
            self._jinja_environment,
            dict(urls=adapter),
        )
        request_handler = RequestHandler(
            request,
            adapter,
            jinja_wrapper,
            self._data_source,
        )

        try:
            endpoint, kwargs = adapter.match()
            handler_fn = self._endpoints[endpoint]
            response = handler_fn(request_handler, **kwargs)
            return response
        except werkzeug.exceptions.HTTPException, exc:
            return exc
        except Exception:
            logging.exception('Exception during request:')
            raise

if __name__ == '__main__':
    with open('regions_and_cities.csv') as stream:
        data_source = DataSource.from_csv(stream)
    jinja = jinja2.Environment(loader=jinja2.PackageLoader('rail_baron', 'templates'))
    app = RailBaronApp(jinja, data_source)
    werkzeug.serving.run_simple(
        '0.0.0.0',
        8080,
        app,
        use_reloader=True,
        static_files={'/static': os.path.join(os.path.dirname(__file__), 'static')},
    )
