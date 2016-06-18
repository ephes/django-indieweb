#!/usr/bin/env python

import os
import sys
import requests

from urllib.parse import unquote
from urllib.parse import urljoin
from urllib.parse import parse_qs
from urllib.parse import urlparse
from django.utils.http import urlencode


class Client:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = requests.Session()

    @property
    def csrftoken(self):
        if not hasattr(self, '_csrftoken'):
            login_url = urljoin(self.base_url, 'accounts/login/')
            r = self.session.get(login_url)
            self._csrftoken = r.cookies['csrftoken']
        return self._csrftoken

    def login(self):
        login_url = urljoin(self.base_url, 'accounts/login/')
        payload = {
            'login': self.username, 'password': self.password,
            'csrfmiddlewaretoken': self.csrftoken,
        }
        r = self.session.post(login_url, payload)
        open('/tmp/blubber.html', 'w').write(r.content.decode('utf-8'))
        print(r.cookies)

    def get_auth(self):
        url_params = {
            'me': '{}/users/jochen/'.format(self.base_url),
            'client_id': 'testclient',
            'redirect_uri': 'http://localhost:8000/',
            'state': 1234567890,
            'scope': 'post',
        }
        auth_url = '{}?{}'.format(
            urljoin(self.base_url, 'indieweb/auth/'), urlencode(url_params))
        r = self.session.get(auth_url, allow_redirects=True)
        data = parse_qs(urlparse(r.url).query)
        return data['code'][0]

    def get_token(self, auth_code):
        token_url = urljoin(self.base_url, 'indieweb/token/')
        payload = {
            'me': '{}/users/jochen/'.format(self.base_url),
            'client_id': 'testclient',
            'redirect_uri': 'http://localhost:8000/',
            'state': 1234567890,
            'scope': 'post',
            'code': auth_code,
        }
        r = self.session.post(token_url, payload)
        data = parse_qs(unquote(r.content.decode('utf-8')))
        return data['access_token'][0]


def main(args):
    username = os.environ['USERNAME']
    password = os.environ['PASSWORD']
    base_url = os.environ['BASE_URL']
    client = Client(base_url, username, password)
    client.login()
    auth_code = client.get_auth()
    print(auth_code)
    token = client.get_token(auth_code)
    print(token)


if __name__ == '__main__':
    main(sys.argv)
