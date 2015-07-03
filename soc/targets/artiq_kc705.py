from migen.fhdl.std import *
from migen.bank.description import *
from migen.bank import wbgen
from mibuild.generic_platform import *
from mibuild.xilinx.vivado import XilinxVivadoToolchain

from misoclib.com import gpio
from misoclib.soc import mem_decoder
from misoclib.mem.sdram.core.minicon import MiniconSettings
from targets.kc705 import MiniSoC

from artiq.gateware.soc import AMPSoC
from artiq.gateware import rtio, nist_qc1, nist_qc2
from artiq.gateware.rtio.phy import ttl_simple, ttl_7series, dds


class _RTIOCRG(Module, AutoCSR):
    def __init__(self, platform, rtio_internal_clk):
        self._clock_sel = CSRStorage()
        self.clock_domains.cd_rtio = ClockDomain(reset_less=True)
        self.clock_domains.cd_rtiox4 = ClockDomain(reset_less=True)

        rtio_clock_mux_output = Signal()
        rtio_clk = Signal()
        rtiox4_clk = Signal()
        pll_fb = Signal()
        rtio_phy_pll_rst = CSRStorage(reset=1)

        rtio_external_clk = Signal()
        user_sma_clock = platform.request("user_sma_clock")
        platform.add_period_constraint(user_sma_clock.p, 8.0)
        self.specials += Instance("IBUFDS",
                                  i_I=user_sma_clock.p, i_IB=user_sma_clock.n,
                                  o_O=rtio_external_clk)
        self.specials += Instance("BUFGMUX",
                                  i_I0=rtio_internal_clk,
                                  i_I1=rtio_external_clk,
                                  i_S=self._clock_sel.storage,
                                  o_O=rtio_clock_mux_output)

        self.specials += Instance("PLLE2_BASE",
                                  p_CLKIN1_PERIOD=8.0,  # 125 MHz
                                  p_CLKFBOUT_MULT=8, p_DIVCLK_DIVIDE=1,
                                  i_CLKIN1=rtio_clock_mux_output,
                                  i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb,
                                  i_RST=rtio_phy_pll_rst.storage,
                                  p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=0.0,
                                  o_CLKOUT0=rtio_clk,  # 125 MHz
                                  p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0,
                                  o_CLKOUT1=rtiox4_clk  # 500 MHz
                                  )

        self.specials += Instance("BUFG", i_I=rtiox4_clk,
                                  o_O=self.cd_rtiox4.clk)

        self.specials += Instance("BUFG", i_I=rtio_clk, o_O=self.cd_rtio.clk)


class _NIST_QCx(MiniSoC, AMPSoC):
    csr_map = {
        "rtio": None,  # mapped on Wishbone instead
        "rtio_crg": 13,
        "kernel_cpu": 14,
        "rtio_moninj": 15
    }
    csr_map.update(MiniSoC.csr_map)
    mem_map = {
        "rtio":     0x20000000, # (shadow @0xa0000000)
        "mailbox":  0x70000000  # (shadow @0xf0000000)
    }
    mem_map.update(MiniSoC.mem_map)

    def __init__(self, platform, cpu_type="or1k", **kwargs):
        MiniSoC.__init__(self, platform,
                         cpu_type=cpu_type,
                         sdram_controller_settings=MiniconSettings(l2_size=128*1024),
                         with_timer=False, **kwargs)
        AMPSoC.__init__(self)
        self.submodules.leds = gpio.GPIOOut(Cat(
            platform.request("user_led", 0),
            platform.request("user_led", 1)))

    def add_rtio(self, rtio_channels):
        self.submodules.rtio_crg = _RTIOCRG(self.platform, self.crg.pll_sys)
        self.submodules.rtio = rtio.RTIO(rtio_channels,
                                         clk_freq=125000000)
        self.add_constant("RTIO_FINE_TS_WIDTH", self.rtio.fine_ts_width)
        self.add_constant("DDS_RTIO_CLK_RATIO", 8 >> self.rtio.fine_ts_width)
        self.submodules.rtio_moninj = rtio.MonInj(rtio_channels)

        if isinstance(self.platform.toolchain, XilinxVivadoToolchain):
            self.platform.add_platform_command("""
create_clock -name rsys_clk -period 8.0 [get_nets {rsys_clk}]
create_clock -name rio_clk -period 8.0 [get_nets {rio_clk}]
create_clock -name rio_clkx4 -period 2.0 [get_nets {rio_clkx4}]
set_false_path -from [get_clocks rsys_clk] -to [get_clocks rio_clk]
set_false_path -from [get_clocks rio_clk] -to [get_clocks rsys_clk]
""",rsys_clk=self.rtio.cd_rsys.clk, rio_clk=self.rtio.cd_rio.clk,
                                          rio_clkx4=self.rtio_crg.cd_rtiox4.clk)

        rtio_csrs = self.rtio.get_csrs()
        self.submodules.rtiowb = wbgen.Bank(rtio_csrs)
        self.kernel_cpu.add_wb_slave(mem_decoder(self.mem_map["rtio"]),
                                     self.rtiowb.bus)
        self.add_csr_region("rtio", self.mem_map["rtio"] | 0x80000000, 32,
                            rtio_csrs)


class NIST_QC1(_NIST_QCx):
    def __init__(self, platform, cpu_type="or1k", **kwargs):
        _NIST_QCx.__init__(self, platform, cpu_type, **kwargs)
        platform.add_extension(nist_qc1.fmc_adapter_io)

        self.comb += [
            platform.request("ttl_l_tx_en").eq(1),
            platform.request("ttl_h_tx_en").eq(1)
        ]

        rtio_channels = []
        for i in range(2):
            phy = ttl_simple.Inout(platform.request("pmt", i))
            self.submodules += phy
            rtio_channels.append(rtio.Channel.from_phy(phy, ififo_depth=512))

        for i in range(14):
            phy = ttl_simple.Output(platform.request("ttl", i))
            self.submodules += phy
            rtio_channels.append(rtio.Channel.from_phy(phy))

        phy = ttl_7series.Output(platform.request("ttl", 14))
        self.submodules += phy
        rtio_channels.append(rtio.Channel.from_phy(phy))

        phy = ttl_7series.Output(platform.request("ttl", 15))
        self.submodules += phy
        rtio_channels.append(rtio.Channel.from_phy(phy))

        phy = ttl_simple.Output(platform.request("user_led", 2))
        self.submodules += phy
        rtio_channels.append(rtio.Channel.from_phy(phy))
        self.add_constant("RTIO_TTL_COUNT", len(rtio_channels))

        self.add_constant("RTIO_DDS_CHANNEL", len(rtio_channels))
        self.add_constant("DDS_CHANNEL_COUNT", 8)
        self.add_constant("DDS_AD9858")
        phy = dds.AD9858(platform.request("dds"), 8)
        self.submodules += phy
        rtio_channels.append(rtio.Channel.from_phy(phy,
                                                   ofifo_depth=512,
                                                   ififo_depth=4))
        self.add_rtio(rtio_channels)


class NIST_QC2(_NIST_QCx):
    def __init__(self, platform, cpu_type="or1k", **kwargs):
        _NIST_QCx.__init__(self, platform, cpu_type, **kwargs)
        platform.add_extension(nist_qc2.fmc_adapter_io)

        rtio_channels = []
        for i in range(16):
            if i % 4 == 3:
                phy = ttl_simple.Inout(platform.request("ttl", i))
                self.submodules += phy
                rtio_channels.append(rtio.Channel.from_phy(phy, ififo_depth=512))
            else:
                phy = ttl_simple.Output(platform.request("ttl", i))
                self.submodules += phy
                rtio_channels.append(rtio.Channel.from_phy(phy))

        phy = ttl_simple.Output(platform.request("user_led", 2))
        self.submodules += phy
        rtio_channels.append(rtio.Channel.from_phy(phy))
        self.add_constant("RTIO_TTL_COUNT", len(rtio_channels))

        self.add_constant("RTIO_DDS_CHANNEL", len(rtio_channels))
        self.add_constant("DDS_CHANNEL_COUNT", 11)
        self.add_constant("DDS_AD9914")
        self.add_constant("DDS_ONEHOT_SEL")
        phy = dds.AD9914(platform.request("dds"), 11)
        self.submodules += phy
        rtio_channels.append(rtio.Channel.from_phy(phy,
                                                   ofifo_depth=512,
                                                   ififo_depth=4))
        self.add_rtio(rtio_channels)


default_subtarget = NIST_QC1
