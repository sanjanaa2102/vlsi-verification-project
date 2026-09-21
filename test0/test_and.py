import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_and_basic(dut):
    dut.a.value = 1
    dut.b.value = 1
    await Timer(1, units="ns")
    assert dut.y.value == 1, "AND gate failed on 1,1"
    dut.b.value = 0
    await Timer(1, units="ns")
    assert dut.y.value == 0, "AND gate failed on 1,0"
    print("PASSED: AND gate works")