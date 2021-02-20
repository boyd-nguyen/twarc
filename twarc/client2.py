# -*- coding: utf-8 -*-
"""
This is the client for the Twitter V2 API.

"""
import os
import re
import ssl
import sys
import json
import types
import logging
import datetime
import requests

from twarc import expansions
from twarc.decorators import *
from requests.exceptions import ConnectionError
from requests.packages.urllib3.exceptions import ProtocolError

log = logging.getLogger("twarc")


class Twarc2:
    def __init__(
        self,
        bearer_token,
        connection_errors=0,
        http_errors=0,
    ):
        """
        Instantiate a Twarc2 instance to talk to the Twitter V2+ API.

        Currently only bearer_token authentication is supported (ie, only Oauth2.0 app
        authentication). You can retrieve your bearer_token from the Twitter developer
        dashboard for your project.

        Unlike the original Twarc client, this object does not perform any configuration
        directly.

        TODO: Figure out how to handle the combinations of:

        - bearer_token
        - api_key and api_secret (which can be used to retrieve a bearer token)
        - access_token and access_token_secret (used with the api_key/secret for user
          authentication/OAuth 1.0a)

        Arguments:

        - bearer_token: the Twitter API bearer_token for autghe

        """
        self.bearer_token = bearer_token
        self.connection_errors = connection_errors
        self.http_errors = http_errors

        self.client = None
        self.last_response = None

        self.connect()

    def search(self):
        pass

    def hydrate(self, tweet_ids):
        pass

    def user_lookup(self, user_ids):
        pass

    def sample(self, event=None, record_keepalive=False, flatten=False):
        """
        Returns a sample of all publically posted tweets.

        The sample is based on slices of each second, not truely randomised. The
        same tweets are returned for all users of this endpoint.

        If a threading.Event is provided for event and the event is set, the
        sample will be interrupted. This can be used for coordination with other
        programs.
        """
        url = "https://api.twitter.com/2/tweets/sample/stream"
        errors = 0

        while True:
            try:
                log.info("Connecting to V2 sample stream")
                resp = self.get(url, params=expansions.EVERYTHING, stream=True)
                errors = 0
                for line in resp.iter_lines(chunk_size=512):
                    if event and event.is_set():
                        log.info("stopping sample")
                        # Explicitly close response
                        resp.close()
                        return
                    if not line:
                        log.info("keep-alive")
                        if record_keepalive:
                            yield "keep-alive"
                        continue
                    else:
                        if flatten:
                            yield expansions.flatten(json.loads(line.decode()))
                        else:
                            yield json.loads(line.decode())
            except requests.exceptions.HTTPError as e:
                errors += 1
                log.error("caught http error %s on %s try", e, errors)
                if self.http_errors and errors == self.http_errors:
                    log.warning("too many errors")
                    raise e
                if e.response.status_code == 420:
                    if interruptible_sleep(errors * 60, event):
                        log.info("stopping filter")
                        return
                else:
                    if interruptible_sleep(errors * 5, event):
                        log.info("stopping filter")
                        return

    @rate_limit
    @catch_conn_reset
    @catch_timeout
    @catch_gzip_errors
    def get(self, *args, **kwargs):
        # Pass allow 404 to not retry on 404
        allow_404 = kwargs.pop("allow_404", False)
        connection_error_count = kwargs.pop("connection_error_count", 0)
        try:
            log.info("getting %s %s", args, kwargs)
            r = self.last_response = self.client.get(
                *args, timeout=(3.05, 31), **kwargs
            )
            # this has been noticed, believe it or not
            # https://github.com/edsu/twarc/issues/75
            if r.status_code == 404 and not allow_404:
                log.warning("404 from Twitter API! trying again")
                time.sleep(1)
                r = self.get(*args, **kwargs)
            return r
        except (ssl.SSLError, ConnectionError, ProtocolError) as e:
            connection_error_count += 1
            log.error("caught connection error %s on %s try", e, connection_error_count)
            if (
                self.connection_errors
                and connection_error_count == self.connection_errors
            ):
                log.error("received too many connection errors")
                raise e
            else:
                self.connect()
                kwargs["connection_error_count"] = connection_error_count
                kwargs["allow_404"] = allow_404
                return self.get(*args, **kwargs)

    def connect(self):
        """
        Sets up the HTTP session to talk to Twitter. If one is active it is
        closed and another one is opened.
        """

        if self.client:
            log.info("closing existing http session")
            self.client.close()

        if self.last_response:
            log.info("closing last response")
            self.last_response.close()

        log.info("creating http session")

        client = requests.Session()

        # For bearer token authentication we only need to setup this header - no OAuth
        # 1.0a dance required. This will likely become more complex when we consider
        # user auth rather than just application authentication.
        client.headers.update({"Authorization": f"Bearer {self.bearer_token}"})

        self.client = client


if __name__ == "__main__":
    import sys
    bearer_token = sys.argv[1]

    tw = Twarc2(bearer_token)

    # print(tw.client.headers)
    for response in tw.sample():
        print(response)
