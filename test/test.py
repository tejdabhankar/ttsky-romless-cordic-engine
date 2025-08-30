import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from cocotb.triggers import RisingEdge, Timer


# ---------------- SPI bit-bang helpers ----------------

class SpiCfg:
    def __init__(self, cpol=False, cpha=False, msb_first=True, sclk_period_ns=40):
        self.cpol = int(bool(cpol))
        self.cpha = int(bool(cpha))
        self.msb_first = bool(msb_first)
        self.t_half = sclk_period_ns // 2  # ns


async def spi_transfer_byte(dut, cfg: SpiCfg, sclk, mosi, miso, cs_n, tx_byte: int) -> int:
    """
    Transfer one 8-bit word with one CS pulse.
    Returns the received byte.
    CPOL/CPHA modes:
      - Mode 0: cpol=0,cpha=0  (sample on rising)
      - Mode 1: cpol=0,cpha=1  (sample on falling)
      - Mode 2: cpol=1,cpha=0  (sample on falling)
      - Mode 3: cpol=1,cpha=1  (sample on rising)
    """
    # Idle levels
    sclk.value = cfg.cpol
    cs_n.value = 1
    mosi.value = 0
    await Timer(cfg.t_half, units="ns")

    # Assert CS for this byte
    cs_n.value = 0
    await Timer(cfg.t_half, units="ns")

    rx = 0
    bit_indices = range(7, -1, -1) if cfg.msb_first else range(0, 8)

    for i in bit_indices:
        bit = (tx_byte >> i) & 1

        if cfg.cpha == 0:
            # Data valid BEFORE the leading (sample) edge
            mosi.value = bit
            await Timer(cfg.t_half, units="ns")

            # Leading edge (sample edge)
            sclk.value = 1 ^ cfg.cpol
            await Timer(1, units="ns")  # tiny delta before sampling
            rx = (rx << 1) | int(miso.value)
            await Timer(cfg.t_half - 1, units="ns")

            # Trailing edge (shift edge)
            sclk.value = cfg.cpol
            await Timer(cfg.t_half, units="ns")
        else:
            # First edge (shift edge): update MOSI on the leading edge
            await Timer(cfg.t_half, units="ns")
            sclk.value = 1 ^ cfg.cpol
            mosi.value = bit
            await Timer(cfg.t_half, units="ns")

            # Second edge (sample edge)
            sclk.value = cfg.cpol
            await Timer(1, units="ns")
            rx = (rx << 1) | int(miso.value)
            await Timer(cfg.t_half - 1, units="ns")

    # Deassert CS after 8 clocks
    cs_n.value = 1
    await Timer(cfg.t_half, units="ns")
    return rx & 0xFF


async def spi_write_bytes(dut, cfg, sclk, mosi, miso, cs_n, data_bytes):
    for b in data_bytes:
        await spi_transfer_byte(dut, cfg, sclk, mosi, miso, cs_n, b)


async def spi_read_bytes(dut, cfg, sclk, mosi, miso, cs_n, n_bytes):
    rx = []
    for _ in range(n_bytes):
        val = await spi_transfer_byte(dut, cfg, sclk, mosi, miso, cs_n, 0x00)
        rx.append(val)
    return rx


# ---------------- Pack helper (yours) ----------------

def pack_cordic_input(in_x, in_y, in_alpha, i_atan_0):
    """Pack 4x16-bit words into a 64-bit integer."""
    return (i_atan_0 << 48) | (in_alpha << 32) | (in_y << 16) | in_x


# ---------------- The actual test ----------------

@cocotb.test()
async def test_cordic_spi(dut):
    """Test CORDIC FSM over SPI with per-byte CS toggle."""

    # System clock (DUT clock)
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
 # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    dut._log.info("Test project behavior")

    # Map pins (based on your top)
# Map pins (based on your top)
    sclk = dut.ui_in[0]
    mosi = dut.ui_in[1]
    cs_n = dut.ui_in[2]
    miso = dut.uo_out[0]

    # SPI config: start with Mode 0 (cpol=0,cpha=0). Change to cpha=1 if your core is mode 1.
    cfg = SpiCfg(cpol=False, cpha=False, msb_first=True, sclk_period_ns=40)  # 25 MHz

    # Inputs (your example)
    in_x     = 0x09b8
    in_y     = 0x0000
    in_alpha = 0x3244
    i_atan_0 = 0x0c91

    # Pack → 8 little-endian bytes (LSB first) to match your RX assembly
    spi_word = pack_cordic_input(in_x, in_y, in_alpha, i_atan_0)
    tx_bytes = [(spi_word >> (8 * i)) & 0xFF for i in range(8)]
    dut._log.info("TX bytes (LSB first): " + " ".join(f"{b:02x}" for b in tx_bytes))

    # --- Write 8 bytes (CS toggles per byte) ---
    await spi_write_bytes(dut, cfg, sclk, mosi, miso, cs_n, tx_bytes)

    # Wait for data_ready (uo_out[1])
    got_ready = False
    for _ in range(10000):
        await RisingEdge(dut.clk)
        if int(dut.uo_out[1].value) == 1:
            got_ready = True
            break
    assert got_ready, "Timeout: data_ready was never asserted"

    # --- Read 6 bytes back (CS toggles per byte) ---
    rx_bytes = await spi_read_bytes(dut, cfg, sclk, mosi, miso, cs_n, 6)
    dut._log.info("RX bytes: " + " ".join(f"{b:02x}" for b in rx_bytes))

    assert len(rx_bytes) == 6, "Did not receive 6 bytes from DUT"

    # (optional) Repack into 16-bit words if you want to inspect:
    out_sinth = (rx_bytes[1] << 8) | rx_bytes[0]
    out_costh = (rx_bytes[3] << 8) | rx_bytes[2]
    out_alpha = (rx_bytes[5] << 8) | rx_bytes[4]
    dut._log.info(f"Parsed: alpha=0x{out_alpha:04x} cos=0x{out_costh:04x} sin=0x{out_sinth:04x}")
