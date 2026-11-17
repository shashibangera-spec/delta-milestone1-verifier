"""Unit-safe BTCUSD open-interest normalization and candle validation helpers."""

CONTRACT_VALUE_BTC = 0.001


def contracts_to_btc(contracts, contract_value=CONTRACT_VALUE_BTC):
    """Convert BTCUSD contract-count OI into BTC using the product contract value."""
    if contracts is None:
        return None
    return float(contracts) * float(contract_value)


def candle_validation_status(observation_start, observation_end, slot_open, slot_seconds=1800):
    """Return whether the observation fully covers a 30-minute candle slot."""
    slot_close = slot_open + slot_seconds
    if observation_start <= slot_open and observation_end >= slot_close:
        return "COMPLETE_30M_OBSERVATION"
    return "PROVISIONAL_INCOMPLETE"
