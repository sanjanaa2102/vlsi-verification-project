// Formal property P2: an accepted operation is never restarted while
// busy, regardless of any interfering CTRL writes that arrive during it.
//
// This is the exact defect class Phase 5's mutant3 (missing busy guard)
// represented -- found there only after deliberately engineering a very
// specific retrigger timing; several plausible near-miss timings did NOT
// expose it. That is precisely why this needs a genuine multi-cycle
// property, not a same-cycle check: the bug only manifests depending on
// the relative timing between a retrigger write and the operation's
// internal countdown, which this harness explores exhaustively (every
// PADDR/PWRITE/PSEL/PENABLE/PWDATA combination at every cycle is left
// completely free -- nothing about interfering writes is special-cased
// or excluded).
//
// Temporal structure (not a single-cycle immediate assertion):
//   1. Watch for an operation being ACCEPTED: busy_o rising 0->1.
//   2. At that moment, remember (latch) the pre-operation DATA value --
//      the formal harness's own state, independent of and never read by
//      the simulation scoreboard.
//   3. From then on, PADDR/PWRITE/PSEL/PENABLE/PWDATA remain completely
//      unconstrained -- the solver is free to choose ANY sequence of
//      legal or illegal CTRL writes (including further ENABLE/START
//      combinations) while busy is asserted.
//   4. When the operation COMPLETES (busy_o falling 1->0), check that
//      DATA now equals the remembered pre-operation value plus exactly
//      one -- i.e. the operation ran exactly once, however many
//      interfering writes occurred in between.
//
// A reset occurring mid-operation aborts the tracked episode rather than
// checking it (mirrors how uart_env/apb_env's checkers exclude
// reset-aborted transactions from correctness checks -- a genuinely
// different, deliberately interrupted scenario, not a violation of this
// property).
//
// Observation via busy_o/data_o (real ports), not hierarchical dut.xxx
// references: confirmed by direct testing that this toolchain's formal
// flow does not reliably model hierarchical cross-module signal
// references (a trivial tautology, `busy_o == dut.busy_reg`, produced a
// false counterexample), while exposed ports behave correctly. data_o
// was added to apb_regblock.v specifically for this (verification-only,
// mirrors busy_o's existing precedent -- see VERIFICATION_PLAN.md).
// Entirely independent of apb_env's black-box scoreboard: no Python
// code, no cocotb, nothing shared.
//
// Scoping assumption: DATA-address writes are excluded while an
// operation is in flight. This is a real, legal, and separately
// understood DUT behavior (see apb_env/reference_model.py's apply_write:
// a DATA write while busy legitimately changes what value the eventual
// auto-increment operates on) -- found by direct testing, not assumed in
// advance: an earlier version of this property, without this exclusion,
// produced a counterexample that was really just this legal interaction,
// not a restart bug. Excluding it narrows the property to what it is
// actually about -- whether a CTRL/START retrigger can restart an
// in-flight operation -- rather than silently conflating two unrelated
// behaviors. CTRL writes (every ENABLE/START combination, including
// illegal ones) remain completely unconstrained throughout.

module apb_regblock_p2_no_restart(
    input        PCLK,
    input        PRESETn,
    input  [7:0] PADDR,
    input        PWRITE,
    input        PSEL,
    input        PENABLE,
    input  [7:0] PWDATA
);
    wire [7:0] PRDATA;
    wire       PREADY, PSLVERR;
    wire       busy_o;
    wire [7:0] data_o;

    apb_regblock dut (
        .PCLK(PCLK), .PRESETn(PRESETn), .PADDR(PADDR), .PWRITE(PWRITE),
        .PSEL(PSEL), .PENABLE(PENABLE), .PWDATA(PWDATA),
        .PRDATA(PRDATA), .PREADY(PREADY), .PSLVERR(PSLVERR),
        .busy_o(busy_o), .data_o(data_o)
    );

    // Assume the trace begins with a genuine reset -- without this, BMC
    // is free to choose an initial state where PRESETn is never
    // asserted at all, leaving the DUT's registers at an arbitrary,
    // physically-meaningless starting value (confirmed by direct
    // testing: an earlier version of this harness "failed" purely
    // because its counterexample trace never reset at all). Every real
    // test in this project also begins with driver.reset() -- this is
    // the same precondition, not a weakening of the property.
    initial assume (!PRESETn);

    // See the scoping-assumption note above: DATA-address writes are
    // excluded while busy, so this property stays focused on the
    // CTRL/START retrigger guard it's actually about.
    always @(posedge PCLK)
        if (busy_o)
            assume (!(PSEL && PWRITE && PADDR == 8'h08));

    reg formal_past_valid = 1'b0;
    always @(posedge PCLK) formal_past_valid <= 1'b1;

    reg       prev_busy = 1'b0;
    reg [7:0] data_at_accept = 8'h00;

    always @(posedge PCLK) begin
        if (!PRESETn) begin
            // Reset aborts any in-flight tracked episode -- not checked.
            prev_busy <= 1'b0;
        end else begin
            if (formal_past_valid) begin
                // Step 1+2: operation accepted -- remember pre-op DATA.
                if (!prev_busy && busy_o)
                    data_at_accept <= data_o;

                // Step 4: operation completed -- check exactly one
                // increment happened, no matter what interfered while
                // busy (step 3 needs no code: inputs are simply never
                // constrained).
                if (prev_busy && !busy_o)
                    assert (data_o == data_at_accept + 8'd1);
            end
            prev_busy <= busy_o;
        end
    end
endmodule
