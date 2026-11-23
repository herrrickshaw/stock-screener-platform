"""The repository ports are abstract: they cannot be instantiated and a complete subclass can."""
import pytest

from domain.market_data import repositories as repo


@pytest.mark.parametrize("port", [repo.IStockRepository, repo.IMarketIndexRepository,
                                  repo.ILiveMarketDataService, repo.IFundamentalsRepository])
def test_ports_are_abstract(port):
    with pytest.raises(TypeError):
        port()


def test_a_complete_implementation_can_be_instantiated():
    class Fund(repo.IFundamentalsRepository):
        def get_annual_financials(self, ticker): return {"a": 1}
        def get_quarterly_financials(self, ticker): return {}
        def get_stock_info(self, ticker): return {"t": ticker}
    f = Fund()
    assert f.get_annual_financials("x") == {"a": 1} and f.get_stock_info("y") == {"t": "y"}


def test_each_port_declares_the_expected_abstract_methods():
    assert repo.IStockRepository.__abstractmethods__ == {
        "get_by_ticker", "get_all_tickers", "save", "get_bulk", "exists_in_cache", "get_last_updated"}
    assert repo.IMarketIndexRepository.__abstractmethods__ == {"get_index", "get_current_level"}
    assert repo.ILiveMarketDataService.__abstractmethods__ == {
        "get_vix", "get_bulk_deals", "get_fii_dii_activity", "get_upcoming_events", "get_all_nse_symbols"}
    assert repo.IFundamentalsRepository.__abstractmethods__ == {
        "get_annual_financials", "get_quarterly_financials", "get_stock_info"}
