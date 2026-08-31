from scanner.symbols import yahoo_symbol


def test_tsx_class_and_unit_symbols():
    assert yahoo_symbol("BAM.A", "TSX") == "BAM-A.TO"
    assert yahoo_symbol("REI.UN", "TSX") == "REI-UN.TO"


def test_venture_and_cse_suffixes():
    assert yahoo_symbol("PNG", "TSXV") == "PNG.V"
    assert yahoo_symbol("YOUR", "CSE") == "YOUR.CN"
    assert yahoo_symbol("AMZN", "NEO") == "AMZN.NE"


def test_existing_yahoo_symbol_is_preserved():
    assert yahoo_symbol("WCP.TO", "TSX") == "WCP.TO"
