import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, Timer

async def reset_dut(dut):
    dut.rst.value = 1
    dut.tx_start.value = 0
    dut.tx_data.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

async def monitor_uart_frame(dut, clks_per_bit):
    frame = []
    
    while int(dut.tx_serial.value) == 1:
        await RisingEdge(dut.clk)
    
    await Timer(clks_per_bit * 0.5, units="ns")
    if int(dut.tx_serial.value) != 0:
        raise AssertionError("Start bit error: tx_serial did not go low")
    await Timer(clks_per_bit, units="ns")

    for i in range(8):
        bit_val = int(dut.tx_serial.value)
        frame.append(str(bit_val))
        await Timer(clks_per_bit, units="ns")

    stop_bit = int(dut.tx_serial.value)
    if stop_bit != 1:
        raise AssertionError(f"Stop bit error: expected 1, got {stop_bit}")
    
    data_str = "".join(reversed(frame))
    return int(data_str, 2)

@cocotb.test()
async def test_uart_tx_basic(dut):
    CLKS_PER_BIT = 4
    
    clock = Clock(dut.clk, 1, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    test_bytes = [0x55, 0xAA, 0x00, 0xFF, 0x12, 0xC0]

    for expected_byte in test_bytes:
        assert int(dut.tx_busy.value) == 0, "tx_busy should be 0 in IDLE"
        assert int(dut.tx_serial.value) == 1, "tx_serial should be 1 (idle) in IDLE"

        dut.tx_data.value = expected_byte
        dut.tx_start.value = 1
        await RisingEdge(dut.clk)
        dut.tx_start.value = 0

        await RisingEdge(dut.clk)
        assert int(dut.tx_busy.value) == 1, "tx_busy should assert after start"

        rx_task = cocotb.start_soon(monitor_uart_frame(dut, CLKS_PER_BIT))
        
        while int(dut.tx_busy.value) == 1:
            await RisingEdge(dut.clk)

        received_byte = await rx_task

        assert received_byte == expected_byte, f"Mismatch: sent 0x{expected_byte:02X}, received 0x{received_byte:02X}"

        await ClockCycles(dut.clk, 2)
        assert int(dut.tx_busy.value) == 0, "tx_busy should deassert after stop bit"
        assert int(dut.tx_serial.value) == 1, "tx_serial should return to idle (1)"

    await ClockCycles(dut.clk, 10)

@cocotb.test()
async def test_uart_tx_back_to_back(dut):
    CLKS_PER_BIT = 4
    
    clock = Clock(dut.clk, 1, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.tx_data.value = 0xA5
    dut.tx_start.value = 1
    await RisingEdge(dut.clk)
    dut.tx_start.value = 0

    await RisingEdge(dut.clk)
    assert int(dut.tx_busy.value) == 1

    dut.tx_data.value = 0x5A
    dut.tx_start.value = 1
    await RisingEdge(dut.clk)
    dut.tx_start.value = 0

    while int(dut.tx_busy.value) == 1:
        await RisingEdge(dut.clk)

    await ClockCycles(dut.clk, 5)