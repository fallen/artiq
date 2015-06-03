from migen.fhdl.std import *

from artiq.gateware.rtio import rtlink

class OSerdese2(Module):
    def __init__(self, pad, o, oe):

        q = TSTriple()
        self.submodules += q.get_tristate(pad)
        t = Signal()
        self.comb += q.oe.eq(~t)

        self.specials += Instance("OSERDESE2", p_DATA_RATE_OQ="SDR",
                                  p_DATA_RATE_TQ="SDR", p_DATA_WIDTH=8,
                                  p_TRISTATE_WIDTH=1, o_OQ=q.o, o_TQ=t,
                                  i_CLK=ClockSignal("sys8"),
                                  i_CLKDIV=ClockSignal("sys"),
                                  i_D1=o[0], i_D2=o[1], i_D3=o[2], i_D4=o[3],
                                  i_D5=o[4], i_D6=o[5], i_D7=o[6], i_D8=o[7],
                                  i_TCE=1, i_OCE=1, i_RST=ResetSignal(),
                                  i_T1=oe[0], i_T2=oe[1], i_T3=oe[2],
                                  i_T4=oe[3], i_T5=oe[4], i_T6=oe[5],
                                  i_T7=oe[6], i_T8=oe[7])

class Output(Module):
    def __init__(self, pad):
        self.rtlink = rtlink.Interface(rtlink.OInterface(1, fine_ts_width=3))
        self.probes = [pad]

        o = Signal()
        o0 = Signal()
        oe = Signal()

        self.submodules.oserdese2 = OSerdese2(pad, o, oe)

        # dout
        edges = Array([0xff^((1<<i) - 1) for i in range(8)])
        edge_out = Signal(8)
        edge_out_n = Signal(8)
        rise_out = Signal()
        fall_out = Signal()
        self.comb += [
                edge_out.eq(edges[self.rtlink.o.fine_ts]),
                edge_out_n.eq(~edge_out),
                rise_out.eq(~o0 & o),
                fall_out.eq(o0 & ~o),
                ]
        self.sync += [
                If(self.rtlink.o.stb,
                    o.eq(self.rtlink.o.data),
                ),
                o0.eq(o),
                ]
