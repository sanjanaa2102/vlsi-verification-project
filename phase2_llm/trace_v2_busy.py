import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

@cocotb.test()
async def trace_busy_v2(dut):
    cocotb.start_soon(Clock(dut.clk, 1, unit="ns").start())
    dut.rst.value = 1
    dut.tx_start.value = 0
    dut.tx_data.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # mirrors test_uart_tx_llm_v2's loop structure exactly
    await RisingEdge(dut.clk)
    dut.tx_data.value = 0x55
    dut.tx_start.value = 1
    await RisingEdge(dut.clk)
    dut.tx_start.value = 0
    cocotb.log.info(f"right after tx_start edge: busy={int(dut.tx_busy.value)} serial={int(dut.tx_serial.value)}")
    for i in range(6):
        await RisingEdge(dut.clk)
        cocotb.log.info(f"+{i+1} cycle: busy={int(dut.tx_busy.value)} serial={int(dut.tx_serial.value)}")