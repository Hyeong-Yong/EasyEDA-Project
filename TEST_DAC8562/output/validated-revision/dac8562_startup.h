#ifndef DAC8562_STARTUP_H
#define DAC8562_STARTUP_H
#include <stdbool.h>
#include <stdint.h>

/* Integrate callbacks with STM32H747 HAL. Do not run from an IRQ handler.
 * enable_output(false) must deassert J4.4, enable_spi(false) must deassert J4.3.
 * rail_good reads J4.5; wait_ms uses a monotonic delay with interrupts running.
 * send24 must hold SYNC low for exactly 24 SCLKs, MSB first, with DIN stable
 * at each falling SCLK edge. Keep CLR high and use the write-and-update command.
 */
typedef struct {
    void (*enable_output)(bool);
    void (*enable_spi)(bool);
    bool (*rail_good)(void);
    void (*wait_ms)(uint32_t);
    bool (*prepare_bus)(void); /* CLR/SYNC/LDAC HIGH, SCLK/DIN idle, before OE */
    bool (*send24)(uint32_t);
    bool (*verify_zero_outputs)(void);
} dac8562_io;

static inline bool dac8562_startup(const dac8562_io *io) {
    io->enable_output(false);
    io->enable_spi(false);
    for (uint32_t elapsed=0; elapsed<500; ++elapsed) {
        if (io->rail_good()) break;
        io->wait_ms(1);
        if (elapsed==499) return false;
    }
    /* Qualify power-good, do not accept a single noisy edge. */
    io->wait_ms(10);
    if (!io->rail_good()) return false;
    if (!io->prepare_bus()) return false;
    io->enable_spi(true);
    io->wait_ms(1);
    if (!io->send24(UINT32_C(0x280001)) ||
        !io->send24(UINT32_C(0x1F8000)) ||
        !io->send24(UINT32_C(0x380001)) ||
        !io->send24(UINT32_C(0x020000))) goto failed;
    /* Loaded-reference settling is not guaranteed by this delay. Confirm
     * reference/output settling on the prototype and adjust this guard. */
    io->wait_ms(20);
    if (!io->rail_good() || !io->verify_zero_outputs()) goto failed;
    io->enable_output(true);
    return true;
failed:
    io->enable_output(false);
    io->enable_spi(false);
    return false;
}
static inline void dac8562_shutdown(const dac8562_io *io) {
    io->enable_output(false);
    io->wait_ms(10); /* Increase after measuring release with flyback diode. */
    io->enable_spi(false);
    /* Only after this function may the caller remove the analog supplies. */
}
#endif
