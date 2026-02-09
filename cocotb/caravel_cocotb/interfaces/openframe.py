"""
OpenFrame Environment for cocotb verification.

OpenFrame is a simplified version of Caravel without:
- Management SoC (CPU, SRAM)
- Housekeeping SPI
- Logic analyzer

It has:
- 44 GPIOs (directly accessible)
- Direct user project control
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, ClockCycles
import cocotb.log
from cocotb.handle import SimHandleBase
from cocotb.binary import BinaryValue
from collections import namedtuple
import caravel_cocotb.interfaces.common as common


class OpenFrame_env:
    """
    Verification environment for OpenFrame.
    
    Provides APIs for monitoring and driving OpenFrame GPIOs, power pins, clock and reset pins.
    
    :param SimHandle dut: dut handle
    """

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.clk = dut.clock_tb
        self.user_hdl = dut.uut  # Direct access to caravel_openframe
        self.get_macros()
        self.active_gpios_num = 44  # OpenFrame has 44 GPIOs
        if "OPENFRAME_IO_PADS" in self.design_macros._asdict():
            self.active_gpios_num = int(self.design_macros.OPENFRAME_IO_PADS)

    def get_macros(self):
        """Get design macros from plusargs."""
        valid_macros = {
            k: v
            for k, v in cocotb.plusargs.items()
            if not k.startswith("_") and "+" not in k
        }
        Macros = namedtuple("Macros", valid_macros.keys())
        self.design_macros = Macros(**valid_macros)

    async def start_up(self):
        """Start OpenFrame by inserting power then reset."""
        await self.power_up()
        await self.reset()
        await self.disable_gpio_drivers()

    async def disable_gpio_drivers(self):
        """Disable all GPIO testbench drivers."""
        for i in range(self.active_gpios_num):
            common.drive_hdl(self.dut._id(f"gpio{i}_en", False), (0, 0), 0)
        await ClockCycles(self.clk, 1)

    async def power_up(self):
        """Setup the vdd and vcc power pins."""
        cocotb.log.info(" [openframe] start powering up")
        self.set_vdd(0)
        await ClockCycles(self.clk, 10)
        cocotb.log.info(" [openframe] power up -> connect vdd")
        self.set_vdd(1)
        await ClockCycles(self.clk, 10)

    async def reset(self):
        """Reset OpenFrame."""
        cocotb.log.info(" [openframe] start resetting")
        self.dut.resetb_tb.value = 0
        await ClockCycles(self.clk, 20)
        self.dut.resetb_tb.value = 1
        await ClockCycles(self.clk, 1)
        cocotb.log.info(" [openframe] finish resetting")

    def set_vdd(self, value: bool):
        """Set power supply values."""
        self.dut.vddio_tb.value = value
        self.dut.vssio_tb.value = 0
        self.dut.vdda_tb.value = value
        self.dut.vssa_tb.value = 0
        self.dut.vccd_tb.value = value
        self.dut.vssd_tb.value = 0
        self.dut.vdda1_tb.value = value
        self.dut.vdda2_tb.value = value
        self.dut.vssa1_tb.value = 0
        self.dut.vssa2_tb.value = 0
        self.dut.vccd1_tb.value = value
        self.dut.vccd2_tb.value = value
        self.dut.vssd1_tb.value = 0
        self.dut.vssd2_tb.value = 0

    def setup_clock(self, period_ns: int):
        """Setup the clock with the given period in nanoseconds."""
        cocotb.log.info(f" [openframe] setting up clock with period {period_ns}ns")
        cocotb.start_soon(Clock(self.clk, period_ns, units="ns").start())

    def drive_gpio(self, gpio_num: int, value: int):
        """
        Drive a GPIO input from testbench.
        
        :param int gpio_num: GPIO number (0-43)
        :param int value: Value to drive (0 or 1)
        """
        if gpio_num >= self.active_gpios_num:
            cocotb.log.error(f"[openframe] GPIO {gpio_num} is out of range (max {self.active_gpios_num-1})")
            return
        common.drive_hdl(self.dut._id(f"gpio{gpio_num}_en", False), (0, 0), 1)
        common.drive_hdl(self.dut._id(f"gpio{gpio_num}", False), (0, 0), value)
        cocotb.log.debug(f"[openframe] drive GPIO[{gpio_num}] = {value}")

    def drive_gpio_range(self, gpio_range: tuple, value: int):
        """
        Drive a range of GPIOs.
        
        :param tuple gpio_range: (high_gpio, low_gpio) tuple
        :param int value: Value to drive
        """
        high, low = gpio_range
        for i in range(low, high + 1):
            bit_value = (value >> (i - low)) & 1
            self.drive_gpio(i, bit_value)

    def release_gpio(self, gpio_num: int):
        """
        Release a GPIO (stop driving from testbench).
        
        :param int gpio_num: GPIO number (0-43)
        """
        if gpio_num >= self.active_gpios_num:
            cocotb.log.error(f"[openframe] GPIO {gpio_num} is out of range")
            return
        common.drive_hdl(self.dut._id(f"gpio{gpio_num}_en", False), (0, 0), 0)
        cocotb.log.debug(f"[openframe] release GPIO[{gpio_num}]")

    def release_gpio_range(self, gpio_range: tuple):
        """
        Release a range of GPIOs.
        
        :param tuple gpio_range: (high_gpio, low_gpio) tuple
        """
        high, low = gpio_range
        for i in range(low, high + 1):
            self.release_gpio(i)

    def monitor_gpio(self, gpio_num: int) -> int:
        """
        Monitor a GPIO output value.
        
        :param int gpio_num: GPIO number (0-43)
        :return: GPIO value
        """
        if gpio_num >= self.active_gpios_num:
            cocotb.log.error(f"[openframe] GPIO {gpio_num} is out of range")
            return 0
        val = self.dut._id(f"gpio{gpio_num}_monitor", False).value
        return int(val) if val.is_resolvable else 0

    def monitor_gpio_range(self, gpio_range: tuple) -> int:
        """
        Monitor a range of GPIO outputs.
        
        :param tuple gpio_range: (high_gpio, low_gpio) tuple
        :return: Combined value of GPIO range
        """
        high, low = gpio_range
        value = 0
        for i in range(low, high + 1):
            bit_value = self.monitor_gpio(i)
            value |= (bit_value << (i - low))
        return value
