import socket
import json
import logging
import aiohttp
import asyncio

logger = logging.getLogger(__name__)


class InfluxdbError(Exception):
    def __str__(self):
        response = self.args[0]
        return "{}: {}".format(response.status_code,
                               response.content.decode("utf8"))


class InfluxdbWriter:
    @asyncio.coroutine
    def write_points(self, name, columns, points, **kwargs):
        return (yield from self.write({
            "name": name,
            "columns": columns,
            "points": points,
        }, **kwargs))

    def write_columns(self, name, **fields):
        columns = list(fields)
        points = list(zip(*(fields[k] for k in columns)))
        return (yield from self.write_points(name, columns, points))

    @asyncio.coroutine
    def write_row(self, name, **fields):
        columns = list(fields)
        points = [[fields[k] for k in columns]]
        return (yield from self.write_points(name, columns, points))


class InfluxdbUDP(InfluxdbWriter):
    def __init__(self, host, port=8085):
        info = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM)
        family, type, proto, addrlen, addr_port = info[0]
        logger.debug("%s", (family, type, addr_port))
        self.socket = socket.socket(family, type, proto)
        self.addr_port = addr_port

    def write(self, *data):
        data = json.dumps(data).encode("utf8")
        self.socket.sendto(data, self.addr_port)


class Influxdb(InfluxdbWriter):
    verify_ssl = True
    chunk_size = 4096

    def __init__(self, host, user, password, database, port=8086, ssl=False):
        self.config(host, port, ssl, user, password, database)

    def config(self, host, port, ssl, user, password, database):
        scheme = "https" if ssl else "http"
        self._baseurl = "{}://{}:{}/".format(scheme, host, port)
        self._auth = {"u": user, "p": password}
        self.database = database

    @asyncio.coroutine
    def request(self, url, data=None, method=None, status=200, **params):
        if method is None:
            if data is None:
                method = "GET"
            else:
                method = "POST"
        _params = self._auth.copy()
        _params.update(params)
        headers = {"Content-type": "application/json", "Accept": "text/plain"}
        response = (yield from aiohttp.request(
            method, self._baseurl + url, params=_params, data=data, headers=headers))
        json_answer = (yield from response.read())
        if response.status != status:
            raise InfluxdbError(response)
        return response

    @asyncio.coroutine
    def write(self, *data, **kwargs):
        return (yield from self.request(
            "db/{}/series".format(self.database),
            data=json.dumps(data), **kwargs))

    def query(self, q, chunked=False, **kwargs):
        response = self.request(
            "db/{}/series".format(self.database),
            stream=chunked, q=q, chunked="true" if chunked else "false",
            **kwargs)
        if chunked:
            return (yield from self.read_chunks(response))
        else:
            return response.json()

    def read_chunks(self, response):
        d = json.JSONDecoder()
        s = ""
        for chunk in (yield from response.read()).iter_content(chunk_size=self.chunk_size):
            s += chunk.decode()
            while True:
                try:
                    obj, pos = d.raw_decode(s)
                    s = s[pos:]
                    yield obj
                except:
                    break
        assert not s.strip()

    def list_series(self):
        return [_[1] for _ in self.query("list series")[0]["points"]]

    def delete_series(self, series):
        return self.request(
            "db/{}/series/{}".format(self.database, series),
            method="DELETE", status=204)