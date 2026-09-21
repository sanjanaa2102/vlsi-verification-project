import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

@cocotb.test()
async def test_uart_tx_comprehensive(dut):
    CLKS_PER_BIT = int(dut.CLKS_PER_BIT.value) if hasattr(dut, "CLKS_PER_BIT") else 4
    
    clock = Clock(dut.clk, 1, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst.value = 1
    dut.tx_start.value = 0
    dut.tx_data.value = 0
    await ClockCycles(dut.clk, 5)
    
    assert int(dut.tx_serial.value) == 1, "IDLE state tx_serial must be high"
    assert int(dut.tx_busy.value) == 0, "IDLE state tx_busy must be low"

    dut.rst.value = 0
    await RisingEdge(dut.clk)

    test_bytes = [0x55, 0xAA, 0x00, 0xFF, 0x12]

    for byte_val in test_bytes:
        await RisingEdge(dut.clk)
        dut.tx_data.value = byte_val
        dut.tx_start.value = 1
        await RisingEdge(dut.clk)
        dut.tx_start.value = 0

        await RisingEdge(dut.clk)
        assert int(dut.tx_busy.value) == 1, "tx_busy should assert after tx_start"

        # Helper to verify a single bit period cycle-by-cycle
        async def verify_bit_period(expected_val):
            for _ in range(CLKS_PER_BIT):
                assert int(dut.tx_serial.value) == expected_val, (
                    f"Bit period value mismatch: expected {expected_val}, got {int(dut.tx_serial.value)}"
                )
                await RisingEdge(dut.clk)

        await RisingEdge(dut.clk)
        # 1. Start bit verification (must be 0)
        await verify_bit_period(0)

        # 2. Data bits verification (LSB first, 8 bits)
        for i in range(8):
            expected_bit = (byte_val >> i) & 1
            await verify_bit_period(expected_bit)

        # 3. Stop bit verification (must be 1)
        # Note: The stop bit state drives serial_reg=1 and holds for CLKS_PER_BIT, 
        # then transitions to IDLE on the clock edge ending the count.
        for _ in range(CLKS_PER_BIT - 1):
            assert int(dut.tx_serial.value) == 1, "Stop bit value should be 1"
            assert int(dut.tx_busy.value) == 1, "tx_busy should remain high until stop bit completes"
            await RisingEdge(dut.clk)

        # Final cycle of stop bit where busy drops and state returns to IDLE
        assert int(dut.tx_serial.value) == 1, "Stop bit final cycle value should be 1"
        await RisingEdge(dut.clk)

        assert int(dut.tx_busy.value) == 0, "tx_busy should deassert after stop bit"
        assert int(dut.tx_serial.value) == 1, "tx_serial should return to IDLE high"

        await ClockCycles(dut.clk, 3)

    await ClockCycles(dut.clk, 10)