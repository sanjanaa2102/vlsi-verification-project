// Formal property P3: BUSY is never held for more than OP_LATENCY
// consecutive cycles.
//
// The bound comes directly from the DUT's own OP_LATENCY parameter --
// this module takes the identical parameter and passes it straight
// through to the apb_regblock instance, so the property's threshold and
// the DUT's actual configured latency can never drift apart (e.g. if
// OP_LATENCY were changed, both the DUT and this bound change together,
// rather than this harness hardcoding a separate "4" that could silently
// stop matching the RTL).
//
// This generalizes the mutant4/mutant5/busy_stuck-style defect classes
// from directed mutation testing (each of which is one specific,
// hand-injected bug) into a single exhaustive claim: no reachable state,
// and no sequence of interfering CTRL writes, can make BUSY stay
// asserted longer than the DUT's own documented latency. Mutation
// testing shows "the specific bugs I thought to inject are caught"; this
// proves "no bug of this entire class exists", a strictly stronger
// guarantee -- which is exactly why it needs formal rather than more
// directed/random simulation.
//
// Observation via busy_o (a real port), not a hierarchical dut.busy_reg
// reference -- confirmed by direct testing that this toolchain's formal
// flow does not reliably model hierarchical cross-module references (see
// apb_regblock_p2_no_restart.sv's header for the specific tautology that
// proved this). Independent of and never shared with apb_env's
// ApbLatencyChecker (which measures the *actual* count via simulation of
// specific traces) or the scoreboard.

module apb_regblock_p3_busy_bounded #(
    parameter integer OP_LATENCY = 4  // matches apb_regblock's own default
)(
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

    apb_regblock #(.OP_LATENCY(OP_LATENCY)) dut (
        .PCLK(PCLK), .PRESETn(PRESETn), .PADDR(PADDR), .PWRITE(PWRITE),
        .PSEL(PSEL), .PENABLE(PENABLE), .PWDATA(PWDATA),
        .PRDATA(PRDATA), .PREADY(PREADY), .PSLVERR(PSLVERR),
        .busy_o(busy_o), .data_o(data_o)
    );

    // Same reasoning as P2: assume the trace begins with a genuine
    // reset, otherwise BMC is free to start from an arbitrary,
    // physically-meaningless register state.
    initial assume (!PRESETn);

    reg formal_past_valid = 1'b0;
    always @(posedge PCLK) formal_past_valid <= 1'b1;

    // Counts consecutive cycles busy_o has been continuously high.
    reg [15:0] busy_run_length = 16'h0000;

    always @(posedge PCLK) begin
        if (!PRESETn) begin
            busy_run_length <= 16'h0000;
        end else begin
            if (busy_o)
                busy_run_length <= busy_run_length + 16'h0001;
            else
                busy_run_length <= 16'h0000;

            if (formal_past_valid)
                assert (busy_run_length <= OP_LATENCY);
        end
    end
endmodule
