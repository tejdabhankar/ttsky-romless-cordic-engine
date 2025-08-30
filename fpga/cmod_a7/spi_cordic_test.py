import spidev
import math
import numpy as np
import time

# ==== Fixed-point format config ====
FRAC_BITS = 12
SCALE = 1 << FRAC_BITS  # 4096 for S3.12
INT_BITS = 3
TOTAL_BITS = 16

def s3_12_to_float(val):
    """Convert 16-bit signed S3.12 to float."""
    if val & 0x8000:  # negative number in two's complement
        val = val - (1 << 16)
    return val / SCALE

def float_to_s3_12(f):
    """Convert float to 16-bit signed S3.12."""
    val = int(round(f * SCALE))
    # Clamp to signed 16-bit range
    val = max(min(val, (1 << 15) - 1), -(1 << 15))
    return val & 0xFFFF

def pack_cordic_input(in_x, in_y, in_alpha, i_atan_0):
    """Pack 4x16-bit words into 64-bit integer."""
    return (i_atan_0 << 48) | (in_alpha << 32) | (in_y << 16) | in_x

def to_spi_bytes(packed_val, total_bytes):
    """Convert packed integer into list of bytes (LSB first)."""
    return [(packed_val >> (8 * i)) & 0xFF for i in range(total_bytes)]

def generate_test_angles(num_angles=100):
    """Generate evenly spaced angles from 0 to 2π."""
    return np.linspace(0, 2 * math.pi, num_angles, endpoint=False)

def run_cordic_regression_test(num_angles=100, tolerance=1e-3, cos_tolerance=None, sin_tolerance=None):
    """
    Run regression test with specified number of angles.

    Args:
        num_angles: Number of test angles (default 100)
        tolerance: General acceptable error tolerance for pass/fail (default 1e-3)
        cos_tolerance: Specific tolerance for cosine (overrides general tolerance if set)
        sin_tolerance: Specific tolerance for sine (overrides general tolerance if set)

    Returns:
        dict: Test results summary
    """

    # Set specific tolerances if provided, otherwise use general tolerance
    cos_tol = cos_tolerance if cos_tolerance is not None else tolerance
    sin_tol = sin_tolerance if sin_tolerance is not None else tolerance

    # === Fixed CORDIC parameters (as per your specification) ===
    FIXED_IN_X = 0x09b8      # 2.420 in S3.12
    FIXED_IN_Y = 0x0000      # 0.000 in S3.12
    FIXED_I_ATAN_0 = 0x0c91  # 3.142 in S3.12 (≈π)

    # === SPI Setup ===
    spi = spidev.SpiDev()
    spi.open(1, 0)  # Change: (bus, device) - e.g., spi.open(0, 0) for SPI0
    spi.max_speed_hz = 1_000  # Change: SPI clock speed in Hz
    spi.mode = 0b00  # Change: SPI mode (0b00, 0b01, 0b10, or 0b11)

    print(f"\n=== CORDIC Regression Test: {num_angles} Angles ===")
    print(f"Fixed parameters:")
    print(f"  in_x = 0x{FIXED_IN_X:04X} ({s3_12_to_float(FIXED_IN_X):+.6f})")
    print(f"  in_y = 0x{FIXED_IN_Y:04X} ({s3_12_to_float(FIXED_IN_Y):+.6f})")
    print(f"  i_atan_0 = 0x{FIXED_I_ATAN_0:04X} ({s3_12_to_float(FIXED_I_ATAN_0):+.6f})")
    print(f"Tolerance: cos=±{cos_tol:.6f}, sin=±{sin_tol:.6f}")
    print("-" * 80)

    # Generate test angles
    test_angles = generate_test_angles(num_angles)

    # Test results storage
    results = {
        'total_tests': num_angles,
        'passed': 0,
        'failed': 0,
        'max_cos_error': 0.0,
        'max_sin_error': 0.0,
        'cos_errors': [],
        'sin_errors': [],
        'failed_cases': [],
        'execution_time': 0.0
    }

    start_time = time.time()

    # === Run tests for each angle ===
    for idx, angle_rad in enumerate(test_angles, 1):
        # Convert angle to S3.12 format
        in_alpha = float_to_s3_12(angle_rad)

        # Pack input data
        packed_val = pack_cordic_input(FIXED_IN_X, FIXED_IN_Y, in_alpha, FIXED_I_ATAN_0)
        spi_tx_data = to_spi_bytes(packed_val, 8)

        # Send to FPGA and receive response
        rx_bytes = spi.xfer2(spi_tx_data)

        # Get additional output bytes
        rx_bytes_additional = []
        for _ in range(6):
            rx = spi.xfer2([0x00])
            rx_bytes_additional.append(rx[0])

        # Reconstruct 16-bit words
        rx_val = sum(b << (8 * i) for i, b in enumerate(rx_bytes_additional))
        fpga_sin_raw = (rx_val >> 0)  & 0xFFFF
        fpga_cos_raw = (rx_val >> 16) & 0xFFFF

        # Convert to float for comparison
        fpga_cos = s3_12_to_float(fpga_cos_raw)
        fpga_sin = s3_12_to_float(fpga_sin_raw)

        # Calculate expected values
        expected_cos = math.cos(angle_rad)
        expected_sin = math.sin(angle_rad)

        # Calculate errors
        cos_error = abs(fpga_cos - expected_cos)
        sin_error = abs(fpga_sin - expected_sin)

        # Update maximum errors
        results['max_cos_error'] = max(results['max_cos_error'], cos_error)
        results['max_sin_error'] = max(results['max_sin_error'], sin_error)

        # Store all errors for mean calculation
        results['cos_errors'].append(cos_error)
        results['sin_errors'].append(sin_error)

        # Determine pass/fail
        cos_pass = cos_error <= cos_tol
        sin_pass = sin_error <= sin_tol
        test_passed = cos_pass and sin_pass

        if test_passed:
            results['passed'] += 1
            status = "✅ PASS"
        else:
            results['failed'] += 1
            status = "❌ FAIL"
            results['failed_cases'].append({
                'test_num': idx,
                'angle_rad': angle_rad,
                'angle_deg': math.degrees(angle_rad),
                'cos_error': cos_error,
                'sin_error': sin_error,
                'fpga_cos': fpga_cos,
                'fpga_sin': fpga_sin,
                'expected_cos': expected_cos,
                'expected_sin': expected_sin
            })

        # Print progress every 10 tests or for failures
        if idx % 10 == 0 or not test_passed:
            print(f"Test {idx:3d}: θ={angle_rad:6.3f} rad ({math.degrees(angle_rad):6.1f}°) "
                  f"| cos_err={cos_error:.6f}, sin_err={sin_error:.6f} | {status}")

    results['execution_time'] = time.time() - start_time

    # Calculate mean errors
    mean_cos_error = np.mean(results['cos_errors'])
    mean_sin_error = np.mean(results['sin_errors'])
    results['mean_cos_error'] = mean_cos_error
    results['mean_sin_error'] = mean_sin_error

    # === Print detailed summary ===
    print("\n" + "=" * 80)
    print("REGRESSION TEST SUMMARY")
    print("=" * 80)
    print(f"Total tests run:     {results['total_tests']}")
    print(f"Passed:             {results['passed']} ({100*results['passed']/results['total_tests']:.1f}%)")
    print(f"Failed:             {results['failed']} ({100*results['failed']/results['total_tests']:.1f}%)")
    print(f"Execution time:     {results['execution_time']:.2f} seconds")
    print(f"Max cosine error:   {results['max_cos_error']:.8f}")
    print(f"Max sine error:     {results['max_sin_error']:.8f}")
    print(f"Mean cosine error:  {mean_cos_error:.8f}")
    print(f"Mean sine error:    {mean_sin_error:.8f}")

    if results['failed'] > 0:
        print(f"\nFAILED TEST DETAILS:")
        print("-" * 80)
        for case in results['failed_cases']:
            print(f"Test {case['test_num']:3d}: θ={case['angle_deg']:6.1f}° "
                  f"| FPGA: cos={case['fpga_cos']:+.6f}, sin={case['fpga_sin']:+.6f}")
            print(f"         Expected: cos={case['expected_cos']:+.6f}, sin={case['expected_sin']:+.6f}")
            print(f"         Errors:   cos={case['cos_error']:.8f}, sin={case['sin_error']:.8f}")
            print()

    # Overall result
    if results['failed'] == 0:
        print("🎉 ALL TESTS PASSED! CORDIC IP is working correctly.")
    else:
        print("⚠️  Some tests failed. Please review the CORDIC implementation.")

    spi.close()
    return results

# === Additional utility functions ===

def run_quick_test(tolerance=1e-3):
    """Run a quick 10-angle test for debugging."""
    return run_cordic_regression_test(num_angles=10, tolerance=tolerance)

def run_comprehensive_test(tolerance=1e-3):
    """Run full 100-angle regression test."""
    return run_cordic_regression_test(num_angles=100, tolerance=tolerance)

def run_high_precision_test(tolerance=1e-4):
    """Run test with tighter tolerance."""
    return run_cordic_regression_test(num_angles=100, tolerance=tolerance)

def run_custom_tolerance_test(cos_tolerance=1e-3, sin_tolerance=1e-4):
    """Run test with different tolerances for cos and sin."""
    return run_cordic_regression_test(num_angles=100, cos_tolerance=cos_tolerance, sin_tolerance=sin_tolerance)

# === Main execution ===
if __name__ == "__main__":
    # Run the comprehensive test
    test_results = run_comprehensive_test()

    # Optionally save results to file
    import json
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"cordic_test_results_{timestamp}.json"

    with open(filename, 'w') as f:
        # Convert numpy floats to regular floats for JSON serialization
        serializable_results = {
            k: (float(v) if isinstance(v, np.floating) else v)
            for k, v in test_results.items()
        }
        json.dump(serializable_results, f, indent=2)

    print(f"\nTest results saved to: {filename}")
