
import subprocess, re, os

mutants = {
    "mutant1_stop_bit_polarity": "uart_tx_mutant1.v",
    "mutant2_dropped_last_bit": "uart_tx_mutant2.v",
    "mutant3_short_start_bit": "uart_tx_mutant3.v",
    "mutant4_busy_stuck_high": "uart_tx_mutant4.v",
    "mutant5_msb_first_bug": "uart_tx_mutant5.v",
    "mutant6_short_data_bits": "uart_tx_mutant6.v",
}

results = {}
for name, fname in mutants.items():
    abspath = os.path.join(os.getcwd(), fname)
    subprocess.run(["make", "clean"], capture_output=True)
    result = subprocess.run(["make", f"VERILOG_SOURCES={abspath}", "MODULE=test_uart_tx_llm_v2"], capture_output=True, text=True)
    output = result.stdout + result.stderr
    m = re.search(r"FAIL=(\d+)", output)
    fail_count = int(m.group(1)) if m else None
    results[name] = "SURVIVED (LLM missed it)" if fail_count == 0 else "CAUGHT" if fail_count else "UNKNOWN"

print()
print("=== LLM TEST \u2014 MUTATION RESULTS ===")
for name, verdict in results.items():
    print(f"{name}: {verdict}")
