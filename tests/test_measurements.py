from decimal import Decimal

from services.measurement_service import validate_and_format_measurement, convert_units


def show(title, result):
    print(f"\n=== {title} ===")
    print(result)


def main():
    # The Typo
    res_typo = validate_and_format_measurement("0..005", "0.001", "0.01", "mm")
    show("The Typo", res_typo)

    # The Unit Mismatch
    val_in = Decimal("0.005")
    val_mm = convert_units(val_in, "in", "mm")
    print("\n=== The Unit Mismatch ===")
    print({"input_in": val_in, "converted_mm": val_mm.quantize(Decimal("0.0001"))})

    # The Sanity Ceiling
    res_ceiling = validate_and_format_measurement("55.0", "0.0", "60.0", "mm", label="Main bearing clearance")
    show("The Sanity Ceiling", res_ceiling)

    # The String Cleaner
    res_clean = validate_and_format_measurement("  150 Nm  ", "0", "300", "Nm", label="Torque")
    show("The String Cleaner", res_clean)


if __name__ == "__main__":
    main()
