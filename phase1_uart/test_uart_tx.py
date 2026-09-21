import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

CLKS_PER_BIT = 4

async def reset_dut(dut):
    dut.rst.value = 1
    dut.tx_start.value = 0
    dut.tx_data.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 1)

async def send_byte(dut, byte_val):
    dut.tx_data.value = byte_val
    dut.tx_start.value = 1
    await ClockCycles(dut.clk, 1)
    dut.tx_start.value = 0

    await ClockCycles(dut.clk, CLKS_PER_BIT)
    assert dut.tx_serial.value == 0, "Start bit not seen"
    await ClockCycles(dut.clk, 1)
    assert dut.tx_busy.value == 1, "tx_busy should be high during transmission"

    bits = []
    for _ in range(8):
        await ClockCycles(dut.clk, CLKS_PER_BIT)
        bits.append(int(dut.tx_serial.value))

    await ClockCycles(dut.clk, CLKS_PER_BIT)
    assert dut.tx_serial.value == 1, "Stop bit not seen"
    await ClockCycles(dut.clk, 1)
    assert dut.tx_busy.value == 0, "tx_busy should be low after transmission completes"
    await ClockCycles(dut.clk, 2)
    assert dut.tx_busy.value == 0, "tx_busy should stay low while idle"

    received = sum(b << i for i, b in enumerate(bits))
    assert received == byte_val, f"Expected {byte_val:#x}, got {received:#x}"

@cocotb.test()
async def test_uart_tx_basic(dut):
    cocotb.start_soon(Clock(dut.clk, 1, unit="ns").start())
    await reset_dut(dut)
    for val in [0x00, 0xFF, 0xA5, 0x55, 0x01]:
        await send_byte(dut, val)
        await ClockCycles(dut.clk, 2)
    print("PASSED: all bytes transmitted correctly")

@cocotb.test()
async def test_uart_tx_timing(dut):
    cocotb.start_soon(Clock(dut.clk, 1, unit="ns").start())
    await reset_dut(dut)

    dut.tx_data.value = 0x55  # 01010101 — alternates every bit, so every segment is checkable
    dut.tx_start.value = 1
    await ClockCycles(dut.clk, 1)
    dut.tx_start.value = 0
    await ClockCycles(dut.clk, 1)

    # start bit, bit0..bit7, stop bit
    expected = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]

    for seg_idx, exp_val in enumerate(expected):
        samples = []
        for _ in range(CLKS_PER_BIT):
            await ClockCycles(dut.clk, 1)
            samples.append(int(dut.tx_serial.value))
        assert all(s == exp_val for s in samples), (
            f"Segment {seg_idx}: expected constant {exp_val} for "
            f"{CLKS_PER_BIT} cycles, got {samples}"
        )
    print(f"PASSED: all {len(expected)} segments held for exactly {CLKS_PER_BIT} cycles")