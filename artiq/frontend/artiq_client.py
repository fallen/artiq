#!/usr/bin/env python3

import argparse
import time
import asyncio
import sys
from operator import itemgetter
from dateutil.parser import parse as parse_date

from prettytable import PrettyTable

from artiq.protocols.pc_rpc import Client
from artiq.protocols.sync_struct import Subscriber
from artiq.protocols import pyon
from artiq.tools import format_arguments


def clear_screen():
    sys.stdout.write("\x1b[2J\x1b[H")


def get_argparser():
    parser = argparse.ArgumentParser(description="ARTIQ CLI client")
    parser.add_argument(
        "-s", "--server", default="::1",
        help="hostname or IP of the master to connect to")
    parser.add_argument(
        "--port", default=None, type=int,
        help="TCP port to use to connect to the master")

    subparsers = parser.add_subparsers(dest="action")
    subparsers.required = True

    parser_add = subparsers.add_parser("submit", help="submit an experiment")
    parser_add.add_argument(
        "-T", "--timed", default=None, type=str,
        help="run the experiment in timed mode. "
             "argument specifies the time of the first run, "
             "use 'now' to run immediately")
    parser_add.add_argument("-e", "--experiment", default=None,
                            help="experiment to run")
    parser_add.add_argument("--rtr-group", default=None, type=str,
                            help="real-time result group "
                                 "(defaults to filename)")
    parser_add.add_argument("file",
                            help="file containing the experiment to run")
    parser_add.add_argument("arguments", nargs="*",
                            help="run arguments")

    parser_cancel = subparsers.add_parser("cancel",
                                          help="cancel an experiment")
    parser_cancel.add_argument("-T", "--timed", default=False,
                               action="store_true",
                               help="cancel a timed experiment")
    parser_cancel.add_argument("rid", type=int,
                               help="run identifier (RID/TRID)")

    parser_set_device = subparsers.add_parser(
        "set-device", help="add or modify a device")
    parser_set_device.add_argument("name", help="name of the device")
    parser_set_device.add_argument("description",
                                   help="description in PYON format")

    parser_del_device = subparsers.add_parser(
        "del-device", help="delete a device")
    parser_del_device.add_argument("name", help="name of the device")

    parser_set_parameter = subparsers.add_parser(
        "set-parameter", help="add or modify a parameter")
    parser_set_parameter.add_argument("name", help="name of the parameter")
    parser_set_parameter.add_argument("value",
                                      help="value in PYON format")

    parser_del_parameter = subparsers.add_parser(
        "del-parameter", help="delete a parameter")
    parser_del_parameter.add_argument("name", help="name of the parameter")

    parser_show = subparsers.add_parser(
        "show", help="show schedule, devices or parameters")
    parser_show.add_argument(
        "what",
        help="select object to show: queue/timed/devices/parameters")

    return parser


def _parse_arguments(arguments):
    d = {}
    for argument in arguments:
        name, value = argument.split("=")
        d[name] = pyon.decode(value)
    return d


def _action_submit(remote, args):
    try:
        arguments = _parse_arguments(args.arguments)
    except:
        print("Failed to parse run arguments")
        sys.exit(1)

    run_params = {
        "file": args.file,
        "experiment": args.experiment,
        "arguments": arguments,
        "rtr_group": args.rtr_group if args.rtr_group is not None \
                        else args.file
    }
    if args.timed is None:
        rid = remote.run_queued(run_params)
        print("RID: {}".format(rid))
    else:
        if args.timed == "now":
            next_time = None
        else:
            next_time = time.mktime(parse_date(args.timed).timetuple())
        trid = remote.run_timed(run_params, next_time)
        print("TRID: {}".format(trid))


def _action_cancel(remote, args):
    if args.timed:
        remote.cancel_timed(args.rid)
    else:
        remote.cancel_queued(args.rid)


def _action_set_device(remote, args):
    remote.set(args.name, pyon.decode(args.description))


def _action_del_device(remote, args):
    remote.delete(args.name)


def _action_set_parameter(remote, args):
    remote.set(args.name, pyon.decode(args.value))


def _action_del_parameter(remote, args):
    remote.delete(args.name)


def _show_queue(queue):
    clear_screen()
    if queue:
        table = PrettyTable(["RID", "File", "Experiment", "Arguments"])
        for rid, run_params in queue:
            row = [rid, run_params["file"]]
            if run_params["experiment"] is None:
                row.append("")
            else:
                row.append(run_params["experiment"])
            row.append(format_arguments(run_params["arguments"]))
            table.add_row(row)
        print(table)
    else:
        print("Queue is empty")


def _show_timed(timed):
    clear_screen()
    if timed:
        table = PrettyTable(["Next run", "TRID", "File", "Experiment",
                             "Arguments"])
        sp = sorted(timed.items(), key=lambda x: (x[1][0], x[0]))
        for trid, (next_run, run_params) in sp:
            row = [time.strftime("%m/%d %H:%M:%S", time.localtime(next_run)),
                   trid, run_params["file"]]
            if run_params["experiment"] is None:
                row.append("")
            else:
                row.append(run_params["experiment"])
            row.append(format_arguments(run_params["arguments"]))
            table.add_row(row)
        print(table)
    else:
        print("No timed schedule")


def _show_devices(devices):
    clear_screen()
    table = PrettyTable(["Name", "Description"])
    table.align["Description"] = "l"
    for k, v in sorted(devices.items(), key=itemgetter(0)):
        table.add_row([k, pyon.encode(v, True)])
    print(table)


def _show_parameters(parameters):
    clear_screen()
    table = PrettyTable(["Parameter", "Value"])
    for k, v in sorted(parameters.items(), key=itemgetter(0)):
        table.add_row([k, str(v)])
    print(table)


def _run_subscriber(host, port, subscriber):
    if port is None:
        port = 3250
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(subscriber.connect(host, port))
        try:
            loop.run_until_complete(asyncio.wait_for(subscriber.receive_task,
                                                     None))
            print("Connection to master lost")
        finally:
            loop.run_until_complete(subscriber.close())
    finally:
        loop.close()


def _show_list(args, notifier_name, display_fun):
    l = []
    def init_l(x):
        l[:] = x
        return l
    subscriber = Subscriber(notifier_name, init_l,
                            lambda mod: display_fun(l))
    _run_subscriber(args.server, args.port, subscriber)


def _show_dict(args, notifier_name, display_fun):
    d = dict()
    def init_d(x):
        d.clear()
        d.update(x)
        return d
    subscriber = Subscriber(notifier_name, init_d,
                            lambda mod: display_fun(d))
    _run_subscriber(args.server, args.port, subscriber)


def main():
    args = get_argparser().parse_args()
    action = args.action.replace("-", "_")
    if action == "show":
        if args.what == "queue":
            _show_list(args, "queue", _show_queue)
        elif args.what == "timed":
            _show_dict(args, "timed", _show_timed)
        elif args.what == "devices":
            _show_dict(args, "devices", _show_devices)
        elif args.what == "parameters":
            _show_dict(args, "parameters", _show_parameters)
        else:
            print("Unknown object to show, use -h to list valid names.")
            sys.exit(1)
    else:
        port = 3251 if args.port is None else args.port
        target_name = {
            "submit": "master_schedule",
            "cancel": "master_schedule",
            "set_device": "master_ddb",
            "del_device": "master_ddb",
            "set_parameter": "master_pdb",
            "del_parameter": "master_pdb",
        }[action]
        remote = Client(args.server, port, target_name)
        try:
            globals()["_action_" + action](remote, args)
        finally:
            remote.close_rpc()

if __name__ == "__main__":
    main()
