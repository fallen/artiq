from migen.fhdl.std import *
from artiq.gateware.rtio.phy import ttl_serdes_generic
from artiq.gateware.rtio import rtlink

class OutputPhy(Module):
    def __init__(self, pad):
        self.o = o = Signal()
        self.comb += pad.eq(o)


class InoutPhy(Module):
    def __init__(self, pad):
        self.o = o = Signal()
        self.oe = oe = Signal()
        self.i = i = Signal()

        ts = TSTriple()
        self.specials += ts.get_tristate(pad)
        self.comb += [
            ts.i.eq(i),
            ts.o.eq(o),
            ts.oe.eq(oe)
        ]


class Output(Module):
    def __init__(self, pad):
        ophy = OutputPhy(pad)
        generic_output = ttl_serdes_generic.Output(ophy)
        self.submodules += generic_output
        self.overrides = generic_output.overrides
        self.rtlink = generic_output.rtlink


class Inout(Module):
    def __init__(self, pad):
        iophy = InoutPhy(pad)
        generic_inout = ttl_serdes_generic.Inout(iophy)
        self.submodules += generic_inout
        self.overrides = generic_inout.overrides
        self.rtlink = generic_inout.rtlink

class ClockGen(Module):
    def __init__(self, pad, ftw_width=24):
        self.rtlink = rtlink.Interface(
            rtlink.OInterface(ftw_width, suppress_nop=False))

        # # #

        ftw = Signal(ftw_width)
        acc = Signal(ftw_width)
        self.sync.rio += If(self.rtlink.o.stb, ftw.eq(self.rtlink.o.data))
        self.sync.rio_phy += [
            acc.eq(acc + ftw),
            # rtlink takes precedence over regular acc increments
            If(self.rtlink.o.stb,
                If(self.rtlink.o.data != 0,
                    # known phase on frequency write: at rising edge
                    acc.eq(2**(ftw_width - 1))
                ).Else(
                    # set output to 0 on stop
                    acc.eq(0)
                )
            ),
            pad.eq(acc[-1])
        ]
