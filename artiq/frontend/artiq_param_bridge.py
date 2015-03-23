#!/usr/bin/env python3

import asyncio
import atexit
import argparse

from artiq.protocols.influxdb import Influxdb
from artiq.protocols.sync_struct import Subscriber


def get_argparser():
    parser = argparse.ArgumentParser(description="ARTIQ parameters influxdb"
                                                 " bridge")
    group = parser.add_argument_group("network")
    group.add_argument(
        "--hostname", default="localhost",
        help="hostname or IP address hosting the Influxdb server")
    group = parser.add_argument_group("credentials")
    group.add_argument(
        "--user", "-u", default="root",
        help="user credential for Influxdb connexion")
    group.add_argument(
        "--password", "-p", default="root",
        help="password credential for Influxdb connection")
    group = parser.add_argument_group("database information")
    group.add_argument(
        "--database", "-d", default="db0",
        help="database name to use"
    )
    group.add_argument(
        "--table", "-t", default="exp0",
        help="table name to use"
    )
    return parser


@asyncio.coroutine
def write_points(infdb, table, columns, points):
    try:
        response = yield from infdb.write_points(table, columns, points)
        yield from response.release()
        del response
    except:
        pass


def make_param_changed(infdb, table):
    def param_changed(mod):
        if mod["action"] == "setitem":
            param = mod["key"]
            value = mod["value"]
            columns = "parameter", "value"
            points = [[param, value]]
            asyncio.async(write_points(infdb, table, columns, points))
        elif mod["action"] == "init":
            paramdict = mod["struct"]
            for param, value in paramdict.items():
                columns = "parameter", "value"
                points = [[param, value]]
                asyncio.async(write_points(infdb, table, columns, points))
    return param_changed


def main():
    args = get_argparser().parse_args()

    loop = asyncio.get_event_loop()

    atexit.register(lambda: loop.close())

    infdb = Influxdb(args.hostname, args.user, args.password, args.database)
    sub = Subscriber("parameters",
                     lambda x: x,
                     notify_cb=make_param_changed(infdb, args.table))

    loop.run_until_complete(sub.connect("::1", 3250))
    atexit.register(lambda: loop.run_until_complete(sub.close()))

    loop.run_forever()

if __name__ == "__main__":
    main()
