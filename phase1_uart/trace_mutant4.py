import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

@cocotb.test()
async def trace(dut):
    cocotb.start_soon(Clock(dut.clk, 1, unit="ns").start())
    dut.rst.value = 1
    dut.tx_start.value = 0
    dut.tx_data.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 1)

    for b in range(2):
        dut.tx_data.value = 0x55
        dut.tx_start.value = 1
        await ClockCycles(dut.clk, 1)
        dut.tx_start.value = 0
        for i in range(48):
            await ClockCycles(dut.clk, 1)
            cocotb.log.info(f"byte{b} cycle{i}: busy={int(dut.tx_busy.value)}")
        await ClockCycles(dut.clk, 2)