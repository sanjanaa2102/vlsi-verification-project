module uart_tx #(
    parameter CLKS_PER_BIT = 4
)(
    input        clk,
    input        rst,
    input        tx_start,
    input  [7:0] tx_data,
    output       tx_serial,
    output       tx_busy
);
    localparam IDLE=0, START=1, DATA=2, STOP=3;
    reg [1:0] state = IDLE;
    reg [7:0] data_reg = 0;
    reg [2:0] bit_idx = 0;
    reg [15:0] clk_count = 0;
    reg serial_reg = 1'b1;
    reg busy_reg = 1'b0;

    assign tx_serial = serial_reg;
    assign tx_busy   = busy_reg;

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE; serial_reg <= 1'b1; busy_reg <= 1'b0;
            clk_count <= 0; bit_idx <= 0;
        end else begin
            case (state)
                IDLE: begin
                    serial_reg <= 1'b1; busy_reg <= 1'b0;
                    if (tx_start) begin
                        data_reg <= tx_data; busy_reg <= 1'b1;
                        state <= START; clk_count <= 0;
                    end
                end
                START: begin
                    serial_reg <= 1'b0;
                    if (clk_count < CLKS_PER_BIT-1) clk_count <= clk_count + 1;
                    else begin clk_count <= 0; bit_idx <= 0; state <= DATA; end
                end
                DATA: begin
                    serial_reg <= data_reg[bit_idx];
                    if (clk_count < CLKS_PER_BIT-2) clk_count <= clk_count + 1;
                    else begin
                        clk_count <= 0;
                        if (bit_idx < 7) bit_idx <= bit_idx + 1;
                        else state <= STOP;
                    end
                end
                STOP: begin
                    serial_reg <= 1'b1;
                    if (clk_count < CLKS_PER_BIT-1) clk_count <= clk_count + 1;
                    else begin clk_count <= 0; busy_reg <= 0; state <= IDLE; end
                end
            endcase
        end
    end
endmodule