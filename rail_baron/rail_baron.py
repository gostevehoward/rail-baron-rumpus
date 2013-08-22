#!/usr/bin/env python

import collections
import csv
import json
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

class DestinationDataSource(object):
    def __init__(self, data_maps):
        self._data_maps = data_maps

    @classmethod
    def from_csv(cls, stream):
        data_maps = collections.defaultdict(lambda: {})
        reader = csv.DictReader(stream)
        for row in reader:
            region_map = data_maps[row['region'].strip()]
            region_map[DiceRoll(row['odd/even'].strip(), int(row['number']))] = row['name'].strip()
        return cls(data_maps)

    def _roll_dice(self):
        return DiceRoll(
            random.choice(['odd', 'even']),
            random.randrange(1, 7) + random.randrange(1, 7),
        )

    def pick_region(self):
        return self._data_maps['area'][self._roll_dice()]

    def pick_city(self, region):
        return self._data_maps[region][self._roll_dice()]

class PayoffDataSource(object):
    def __init__(self, payoff_dict):
        self._payoff_dict = payoff_dict

    @classmethod
    def from_json(cls, stream):
        return cls(json.load(stream))

    def get_cities(self):
        return sorted(self._payoff_dict.iterkeys())

    def get_payoff(self, source_city, destination_city):
        return self._payoff_dict[source_city][destination_city]

class RequestHandler(object):
    def __init__(self, request, urls, jinja_wrapper, destination_data_source, payoff_data_source):
        self._request = request
        self._urls = urls
        self._jinja_wrapper = jinja_wrapper
        self._destination_data_source = destination_data_source
        self._payoff_data_source = payoff_data_source

    def index(self):
        return self._jinja_wrapper.render_template('index.html')

    def get_region(self):
        region = self._destination_data_source.pick_region()
        logging.info('Picked region {}'.format(region))
        return self._jinja_wrapper.render_template('show_region.html', {'region': region})

    def get_city(self, region):
        city = self._destination_data_source.pick_city(region)
        logging.info('Picked city {} for region {}'.format(city, region))
        return self._jinja_wrapper.render_template(
            'show_city.html',
            {'region': region, 'city': city},
        )

    def lookup_payoff(self):
        source_city = self._request.args['source_city']
        destination_city = self._request.args['destination_city']
        payoff = self._payoff_data_source.get_payoff(source_city, destination_city)
        return self._jinja_wrapper.render_template(
            'show_payoff.html',
            {
                'source_city': source_city,
                'destination_city': destination_city,
                'payoff': payoff,
            }
        )

class RailBaronApp(object):
    def __init__(self, jinja_environment, destination_data_source, payoff_data_source):
        self._jinja_environment = jinja_environment
        self._destination_data_source = destination_data_source
        self._payoff_data_source = payoff_data_source

        self._url_map = routing.Map(
            [
                routing.Rule('/', endpoint='index', methods=['GET']),
                routing.Rule('/get_region', endpoint='get region', methods=['GET']),
                routing.Rule('/<region>/get_city', endpoint='get city', methods=['GET']),
                routing.Rule('/payoff', endpoint='lookup payoff',
                             methods=['GET']),
            ]
        )
        self._endpoints = {
            'index': RequestHandler.index,
            'get region': RequestHandler.get_region,
            'get city': RequestHandler.get_city,
            'lookup payoff': RequestHandler.lookup_payoff,
        }

    @wrappers.Request.application
    def __call__(self, request):
        adapter = self._url_map.bind_to_environ(request.environ)
        jinja_wrapper = JinjaWrapper(
            self._jinja_environment,
            dict(urls=adapter, all_cities=self._payoff_data_source.get_cities()),
        )
        request_handler = RequestHandler(
            request,
            adapter,
            jinja_wrapper,
            self._destination_data_source,
            self._payoff_data_source,
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
    logging.basicConfig(level=logging.DEBUG)

    with open('regions_and_cities.csv') as stream:
        destination_data_source = DestinationDataSource.from_csv(stream)
    with open('payoffs.json') as stream:
        payoff_data_source = PayoffDataSource.from_json(stream)

    jinja = jinja2.Environment(loader=jinja2.PackageLoader('rail_baron', 'templates'))
    app = RailBaronApp(jinja, destination_data_source, payoff_data_source)
    werkzeug.serving.run_simple(
        '0.0.0.0',
        8080,
        app,
        use_reloader=True,
        static_files={'/static': os.path.join(os.path.dirname(__file__), 'static')},
    )
