// Formal property P1: PSLVERR correctness.
//
// PSLVERR must be asserted during ACCESS if and only if the access is
// illegal per the fixed, device-specific address map (write to STATUS,
// or an invalid address; read from INTCLR, or an invalid address).
//
// This property is inherently combinational: PSLVERR in apb_regblock.v
// depends only on PADDR/PWRITE/PSEL/PENABLE (the current-cycle inputs),
// never on any internal register. It does not need $past or any
// multi-cycle reasoning, and its truth at any one step does not depend
// on how that step was reached -- so proving it at every step of a
// bounded run already constitutes a complete proof over the full
// interface input space (all 256 PADDR values x both directions x every
// PSEL/PENABLE combination), not merely a bounded-in-time claim. This is
// noted explicitly rather than assumed -- see VERIFICATION_PLAN.md for
// the reasoning and how it's reported.
//
// PADDR/PWRITE/PSEL/PENABLE/PWDATA are left completely free (no
// `assume`) -- the only constraint is scoping the *check* to when it is
// actually meaningful (during ACCESS), matching the requirement to
// constrain only the interface conditions necessary to make PSLVERR
// meaningful, not to narrow the input space.
//
// Independent of the simulation scoreboard/checkers: this re-derives
// the address-map legality rule directly from the spec (VERIFICATION_PLAN.md's
// register map), not by calling into apb_env's Python reference model.

module apb_regblock_p1_pslverr(
    input        PCLK,
    input        PRESETn,
    input  [7:0] PADDR,
    input        PWRITE,
    input        PSEL,
    input        PENABLE,
    input  [7:0] PWDATA
);
    wire [7:0] PRDATA;
    wire       PREADY, PSLVERR, busy_o;

    apb_regblock dut (
        .PCLK(PCLK), .PRESETn(PRESETn), .PADDR(PADDR), .PWRITE(PWRITE),
        .PSEL(PSEL), .PENABLE(PENABLE), .PWDATA(PWDATA),
        .PRDATA(PRDATA), .PREADY(PREADY), .PSLVERR(PSLVERR), .busy_o(busy_o)
    );

    wire access = PSEL && PENABLE;

    localparam [7:0] ADDR_CTRL   = 8'h00;
    localparam [7:0] ADDR_STATUS = 8'h04;
    localparam [7:0] ADDR_DATA   = 8'h08;
    localparam [7:0] ADDR_INTCLR = 8'h0C;

    wire addr_valid = (PADDR == ADDR_CTRL) || (PADDR == ADDR_STATUS) ||
                       (PADDR == ADDR_DATA) || (PADDR == ADDR_INTCLR);
    wire spec_illegal_write = access && PWRITE  && (!addr_valid || PADDR == ADDR_STATUS);
    wire spec_illegal_read  = access && !PWRITE && (!addr_valid || PADDR == ADDR_INTCLR);

    always @(posedge PCLK) begin
        if (access)
            assert (PSLVERR == (spec_illegal_write || spec_illegal_read));
    end
endmodule
