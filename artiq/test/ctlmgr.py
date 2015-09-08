import asyncio
import os
import sys
import unittest

from artiq.protocols.pc_rpc import Server
from artiq.frontend.artiq_ctlmgr import ControllerManager
from artiq.protocols.file_db import FlatFileDB
import artiq.frontend as frontend

frontend_path = os.path.dirname(frontend.__file__)
examples = os.path.join(frontend_path, "..", "..", "examples", "master")
examples_present = os.path.exists(examples)

if not examples_present:
    artiq_examples = os.getenv("ARTIQ_EXAMPLES")
    if artiq_examples:
        examples = artiq_examples
        examples_present = os.path.exists(artiq_examples)


@unittest.skipIf(not examples_present, "examples directory is not present")
class CtlMgrCase(unittest.TestCase):
    @asyncio.coroutine
    def start_master(self):
        self.master = yield from asyncio.gather(
            asyncio.create_subprocess_exec(
                sys.executable,
                os.path.join(frontend_path, "artiq_master.py"), "-r",
                os.path.join(examples, "repository"), "-d",
                os.path.join(examples, "ddb.pyon"), "-p",
                os.path.join(examples, "pdb.pyon")
            )
        )
        self.master = self.master[0]

    def setUp(self):
        if os.name == "nt":
            self.loop = asyncio.ProactorEventLoop()
        else:
            self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        import artiq
        self.ddb = FlatFileDB(os.path.join(artiq.__path__[0], "..", "examples",
                                           "master", "ddb.pyon")).data.read

        self.controllers = []
        for cont in self.ddb:
            if isinstance(self.ddb[cont], dict)\
             and self.ddb[cont]["type"] == "controller":
                self.controllers.append(cont)

        self.ctlmgr = ControllerManager("::1", 3250, 1.0)
        self.ctlmgr.start()

        class CtlMgrRPC:
            retry_now = self.ctlmgr.retry_now

        rpc_target = CtlMgrRPC()
        self.rpc_server = Server({"ctlmgr": rpc_target}, builtin_terminate=True)
        self.loop.run_until_complete(self.rpc_server.start("::1", 3249))
        self.loop.run_until_complete(self.start_master())

    @asyncio.coroutine
    def _controller_connected(self):
        while True:
            if hasattr(self.ctlmgr.subscriber, "writer"):
                break
            else:
                yield from asyncio.sleep(0.3)

    @asyncio.coroutine
    def _test_controller_list(self):
        yield from asyncio.wait_for(self._controller_connected(),
                                    10, loop=self.loop)
        while True:
            if self.ctlmgr.controller_db.current_controllers is not None:
                break
            yield from asyncio.sleep(0.3)
        self.assertCountEqual(
            list(
                self.ctlmgr.controller_db.current_controllers.active_or_queued
            ),
            self.controllers)

    def test_controller_list(self):
        self.loop.run_until_complete(self._test_controller_list())

    @asyncio.coroutine
    def _test_master_crash(self):
        yield from asyncio.wait_for(self._controller_connected(),
                                    10, loop=self.loop)
        self.master.kill()
        yield from self.master.wait()
        yield from self.start_master()
        yield from self._test_controller_list()

    def test_master_crash(self):
        self.loop.run_until_complete(self._test_master_crash())

    def tearDown(self):
        self.master.kill()
        self.loop.run_until_complete(self.master.wait())
        self.loop.run_until_complete(self.ctlmgr.stop())
        self.loop.run_until_complete(self.rpc_server.stop())
        self.loop.close()
