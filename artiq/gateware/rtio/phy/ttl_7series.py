from migen.fhdl.std import *
from migen.genlib.coding import PriorityEncoder

from artiq.gateware.rtio import rtlink

class OSerdese2(Module):
    def __init__(self, pad):

        ts = TSTriple()
        self.o = o = Signal(8)
        self.oe = oe = Signal()
        self.specials += ts.get_tristate(pad)
        t = Signal()
        self.comb += ts.oe.eq(~t)

        self.specials += Instance("OSERDESE2", p_DATA_RATE_OQ="DDR",
                                  p_DATA_RATE_TQ="DDR", p_DATA_WIDTH=8,
                                  p_TRISTATE_WIDTH=1, o_OQ=ts.o, o_TQ=t,
                                  i_CLK=ClockSignal("rtiox4"),
                                  i_CLKDIV=ClockSignal("rio_phy"),
                                  i_D1=o[0], i_D2=o[1], i_D3=o[2], i_D4=o[3],
                                  i_D5=o[4], i_D6=o[5], i_D7=o[6], i_D8=o[7],
                                  i_TCE=1, i_OCE=1, i_RST=ResetSignal(),
                                  i_T1=oe)

class IOSerdese2(Module):
    def __init__(self, pad):

        ts = TSTriple()
        self.o = o = Signal(8)
        self.oe = oe = Signal()
        self.i = i = Signal(8)
        self.specials += ts.get_tristate(pad)
        t = Signal()
        self.comb += ts.oe.eq(~t)

        self.specials += Instance("ISERDESE2", p_DATA_RATE="DDR",
                                  p_DATA_WIDTH=8,
                                  p_INTERFACE_TYPE="NETWORKING", p_NUM_CE=1,
                                  o_Q1=i[7], o_Q2=i[6], o_Q3=i[5], o_Q4=i[4],
                                  o_Q5=i[3], o_Q6=i[2], o_Q7=i[1], o_Q8=i[0],
                                  i_D=ts.i, i_CLK=ClockSignal("rtiox4"),
                                  i_CE1=1, i_RST=ResetSignal(),
                                  i_CLKDIV=ClockSignal("rio_phy"))

        self.specials += Instance("OSERDESE2", p_DATA_RATE_OQ="DDR",
                                  p_DATA_RATE_TQ="DDR", p_DATA_WIDTH=8,
                                  p_TRISTATE_WIDTH=1, o_OQ=ts.o, o_TQ=t,
                                  i_CLK=ClockSignal("rtiox4"),
                                  i_CLKDIV=ClockSignal("rio_phy"),
                                  i_D1=o[0], i_D2=o[1], i_D3=o[2], i_D4=o[3],
                                  i_D5=o[4], i_D6=o[5], i_D7=o[6], i_D8=o[7],
                                  i_TCE=1, i_OCE=1, i_RST=ResetSignal(),
                                  i_T1=oe)


class Output(Module):
    def __init__(self, pad, sim=False):
        self.rtlink = rtlink.Interface(rtlink.OInterface(1, fine_ts_width=3))
        self.probes = [pad]

        o = Signal()
        previous_o = Signal()
        oe = Signal()
        timestamp = Signal(3)

        if sim:
            io = FakeSerdes()
        else:
            io = OSerdese2(pad)
        self.submodules += io

        # dout
        edges = Array([0xff ^ ((1 << i) - 1) for i in range(8)])
        edge_out = Signal(8)
        edge_out_n = Signal(8)
        rise_out = Signal()
        fall_out = Signal()
        self.comb += [
            edge_out.eq(edges[timestamp]),
            edge_out_n.eq(~edge_out),
            rise_out.eq(~previous_o & o),
            fall_out.eq(previous_o & ~o),
            io.oe.eq(oe),
            If(rise_out,
                io.o.eq(edge_out),
            ).Elif(fall_out,
                io.o.eq(edge_out_n),
            ).Else(
                io.o.eq(Replicate(o, 8)),
            )
        ]

        self.sync.rio_phy += [
            If(self.rtlink.o.stb,
                timestamp.eq(self.rtlink.o.fine_ts),
                o.eq(self.rtlink.o.data),
            ),
            previous_o.eq(o),
        ]

class Inout(Module):
    def __init__(self, pad, sim=False):
        self.rtlink = rtlink.Interface(
            rtlink.OInterface(2, 2, fine_ts_width=3),
            rtlink.IInterface(1, fine_ts_width=3))
        self.probes = []

        if sim:
            self.io = io = FakeIOSerdes()
        else:
            self.io = io = IOSerdese2(pad)
        self.submodules += io

        # input
        i = Signal(8)
        i0 = Signal()
        rising = Signal()
        falling = Signal()
        self.sensitivity = Signal(2)

        self.submodules.pe = pe = PriorityEncoder(8)

        self.sync.rio_phy += [
            i0.eq(i[-1]),
            If(self.rtlink.o.stb & (self.rtlink.o.address == 2),
                self.sensitivity.eq(self.rtlink.o.data)
            ),
        ]

        self.comb += [
            i.eq(io.i),
            rising.eq(~i0 & i[-1]),
            falling.eq(i0 & ~i[-1]),
            pe.i.eq(i ^ Replicate(falling, 8)),
            self.rtlink.i.data.eq(i[-1]),
            self.rtlink.i.fine_ts.eq(pe.o),
            self.rtlink.i.stb.eq(
                (self.sensitivity[0] & rising) |
                (self.sensitivity[1] & falling)
            ),
        ]

        # Output management
        o = Signal()
        oe = Signal()
        previous_o = Signal()
        timestamp = Signal(3)
        edges = Array([0xff ^ ((1 << i) - 1) for i in range(8)])
        edge_out = Signal(8)
        edge_out_n = Signal(8)
        rise_out = Signal()
        fall_out = Signal()

        self.comb += [
            edge_out.eq(edges[timestamp]),
            edge_out_n.eq(~edge_out),
            rise_out.eq(~previous_o & o),
            fall_out.eq(previous_o & ~o),
            io.oe.eq(oe),
            If(rise_out,
                io.o.eq(edge_out),
            ).Elif(fall_out,
                io.o.eq(edge_out_n),
            ).Else(
                io.o.eq(Replicate(o, 8)),
            )
        ]

        self.sync.rio_phy += [
            If(self.rtlink.o.stb,
                If(self.rtlink.o.address == 0, o.eq(self.rtlink.o.data[0])),
                If(self.rtlink.o.address == 1, oe.eq(self.rtlink.o.data[0])),
            ),
            If(self.rtlink.o.stb,
                timestamp.eq(self.rtlink.o.fine_ts),
                o.eq(self.rtlink.o.data),
            ),
            previous_o.eq(o),
        ]


class FakeSerdes(Module):
    def __init__(self):
        self.o = o = Signal(8)
        self.oe = oe = Signal(8)

class FakeIOSerdes(Module):
    def __init__(self):
        self.o = o = Signal(8)
        self.oe = oe = Signal(8)
        self.i = i = Signal(8)


class OutputTB(Module):
    def __init__(self):
        pad = Signal()
        self.o = RenameClockDomains(Output(pad, sim=True),
                                    {"rio_phy": "sys"})
        self.submodules += self.o

    def gen_simulation(self, selfp):

        yield
        selfp.o.rtlink.o.data = 1
        selfp.o.rtlink.o.fine_ts = 1
        selfp.o.rtlink.o.stb = 1
        yield
        selfp.o.rtlink.o.stb = 0
        yield

        selfp.o.rtlink.o.data = 0
        selfp.o.rtlink.o.fine_ts = 2
        selfp.o.rtlink.o.stb = 1
        yield
        selfp.o.rtlink.o.data = 1
        selfp.o.rtlink.o.fine_ts = 7
        yield

        while True:
            yield

class InoutTB(Module):
    def __init__(self):
        pad = Signal()
        self.io = RenameClockDomains(Inout(pad, sim=True),
                                     {"rio_phy": "sys"})
        self.submodules += self.io

    def check_input(self, selfp, stb, fine_ts=None):
        if stb != selfp.io.rtlink.i.stb:
            print("KO rtlink.i.stb should be {} but is {}"
                  .format(stb, selfp.io.rtlink.i.stb))
        elif fine_ts is not None and fine_ts != selfp.io.rtlink.i.fine_ts:
            print("KO rtlink.i.fine_ts should be {} but is {}"
                  .format(fine_ts, selfp.io.rtlink.i.fine_ts))
        else:
            print("OK")

    def check_output(self, selfp, data):
        if selfp.io.io.o != data:
            print("KO io.o should be {} but is {}".format(data, selfp.io.io.o))
        else:
            print("OK")

    def check_output_enable(self, selfp, oe):
        if selfp.io.io.oe != oe:
            print("KO io.oe should be {} but is {}".format(oe, selfp.io.io.oe))
        else:
            print("OK")

    def gen_simulation(self, selfp):

        selfp.io.sensitivity = 0b11  # rising + falling

        yield
        selfp.io.io.i = 0b11111110  # rising edge at fine_ts = 1
        yield
        self.check_input(selfp, stb=1, fine_ts=1)
        selfp.io.io.i = 0b01111111  # falling edge at fine_ts = 7
        yield
        self.check_input(selfp, stb=1, fine_ts=7)
        selfp.io.io.i = 0b11000000  # rising edge at fine_ts = 6
        yield
        self.check_input(selfp, stb=1, fine_ts=6)
        selfp.io.sensitivity = 0b01  # rising
        selfp.io.io.i = 0b00001111  # falling edge at fine_ts = 4
        yield
        self.check_input(selfp, stb=0)  # no strobe, sensitivity is rising edge
        selfp.io.io.i = 0b11110000  # rising edge at fine_ts = 4
        yield
        self.check_input(selfp, stb=1, fine_ts=4)

        while True:
            yield


if __name__ == "__main__":
    import sys
    from migen.sim.generic import Simulator, TopLevel
    from migen.sim import icarus

    if len(sys.argv) <= 1:
        print("You should run this script with either InoutTB() or OutputTB() "
              "arg")
        sys.exit(1)

    with Simulator(eval(sys.argv[1]), TopLevel("top.vcd", clk_period=int(1/0.125)),
                   icarus.Runner(keep_files=False,)) as s:
        s.run(20000)
