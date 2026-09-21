module apb_regblock #(
    parameter integer OP_LATENCY = 4   // cycles CTRL.START takes to complete
)(
    input             PCLK,
    input             PRESETn,   // active-low, standard AMBA convention
    input      [7:0]  PADDR,
    input             PWRITE,
    input             PSEL,
    input             PENABLE,
    input      [7:0]  PWDATA,
    output     [7:0]  PRDATA,
    output            PREADY,
    output            PSLVERR,
    output            busy_o     // verification-only observability port --
                                  // NOT part of the APB interface, mirrors
                                  // the internal busy_reg so the testbench
                                  // can independently verify OP_LATENCY
                                  // cycle-accurately without relying on
                                  // software polling. See VERIFICATION_PLAN.md.
);
    localparam ADDR_CTRL   = 8'h00;
    localparam ADDR_STATUS = 8'h04;
    localparam ADDR_DATA   = 8'h08;
    localparam ADDR_INTCLR = 8'h0C;

    reg       enable_reg = 1'b0;
    reg [7:0] data_reg   = 8'h00;
    reg       busy_reg   = 1'b0;
    reg       done_reg   = 1'b0;
    reg [7:0] op_count   = 8'h00;

    wire access    = PSEL && PENABLE;
    wire is_write  = access && PWRITE;
    wire is_read   = access && !PWRITE;

    wire addr_valid = (PADDR == ADDR_CTRL) || (PADDR == ADDR_STATUS) ||
                       (PADDR == ADDR_DATA) || (PADDR == ADDR_INTCLR);

    // Register-map legality: device-specific, not an APB protocol rule --
    // see VERIFICATION_PLAN.md for why this is scoreboard/reference-model
    // territory, not the protocol checker's.
    wire illegal_write = is_write && (!addr_valid || PADDR == ADDR_STATUS);
    wire illegal_read  = is_read  && (!addr_valid || PADDR == ADDR_INTCLR);

    assign PREADY  = !PWRITE;            // zero-wait-state slave
    assign PSLVERR = illegal_write || illegal_read;
    assign busy_o  = busy_reg;

    reg [7:0] prdata_reg;
    assign PRDATA = prdata_reg;

    always_comb begin
        case (PADDR)
            ADDR_CTRL:   prdata_reg = {6'b0, 1'b0, enable_reg}; // START always reads 0
            ADDR_STATUS: prdata_reg = {6'b0, done_reg, busy_reg};
            ADDR_DATA:   prdata_reg = data_reg;
            default:     prdata_reg = 8'h00; // INTCLR and any unmapped address
        endcase
    end

    always @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) begin
            enable_reg <= 1'b0;
            data_reg   <= 8'h00;
            busy_reg   <= 1'b0;
            done_reg   <= 1'b0;
            op_count   <= 8'h00;
        end else begin
            // Operation latency countdown. START's own condition below
            // checks the *registered* enable_reg (not the incoming write
            // data), so writing ENABLE and START together in one CTRL
            // write does NOT start an operation on that same write --
            // enable must already be committed from a prior cycle. This
            // is deliberate, realistic, and directly tested.
            if (busy_reg) begin
                if (op_count < OP_LATENCY - 1) begin
                    op_count <= op_count + 1'b1;
                end else begin
                    busy_reg <= 1'b0;
                    done_reg <= 1'b1;
                    data_reg <= data_reg + 1'b1;
                    op_count <= 8'h00;
                end
            end

            if (is_write) begin
                case (PADDR)
                    ADDR_CTRL: begin
                        enable_reg <= PWDATA[0];
                        if (PWDATA[1] && enable_reg && !busy_reg) begin
                            busy_reg <= 1'b1;
                            op_count <= 8'h00;
                        end
                    end
                    ADDR_DATA: begin
                        data_reg <= PWDATA;
                    end
                    ADDR_INTCLR: begin
                        if (PWDATA[1]) done_reg <= 1'b0;
                    end
                    default: ; // STATUS write: ignored at the storage level, flagged via PSLVERR
                endcase
            end
        end
    end
endmodule
