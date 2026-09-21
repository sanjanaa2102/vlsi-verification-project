from google import genai

with open("uart_tx_golden.v") as f:
    rtl_code = f.read()

prompt = f"""You are a hardware verification engineer. Below is a Verilog module implementing a UART transmitter (8 data bits, no parity, 1 stop bit, "8N1"), using a configurable clock divisor CLKS_PER_BIT to set the baud rate.

```verilog
{rtl_code}
```

Write a complete cocotb (version 2.x) testbench in Python that verifies this module's correctness as thoroughly as you can. Requirements:
- Use `from cocotb.clock import Clock` and `from cocotb.triggers import ClockCycles` (cocotb 2.x style — do NOT use deprecated APIs like `.value.integer`; use `int(signal.value)` instead).
- Drive the clock with `Clock(dut.clk, 1, unit="ns")`.
- Signal names exactly as declared: clk, rst, tx_start, tx_data, tx_serial, tx_busy.
- At least one `@cocotb.test()` function.
- Check whatever you believe are the important correctness properties of a UART transmitter: framing, correct data bits in order, correct bit timing, and correct busy-flag behavior.
- Output ONLY the Python code. No explanation, no markdown fences.
- Explicitly verify precise bit timing: for every bit period (start bit, each of the 8 data bits, and the stop bit), sample the signal on every clock cycle within that period and assert it holds a constant value for exactly CLKS_PER_BIT cycles. Do not assume bit boundaries using fixed time offsets — measure directly, cycle by cycle.
"""

client = genai.Client()
response = client.models.generate_content(model="gemini-3.5-flash-lite", contents=prompt)

code = response.text.strip()
if code.startswith("```"):
    code = code.split("```")[1]
    if code.startswith("python"):
        code = code[len("python"):]
code = code.strip()

with open("test_uart_tx_llm_v2.py", "w") as f:
    f.write(code)

print("Saved to test_uart_tx_llm.py\n---- Preview ----")
print(code[:2000])