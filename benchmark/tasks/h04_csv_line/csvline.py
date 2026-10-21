def parse_csv_line(line):
    return [field.strip('"') for field in line.split(",")]
