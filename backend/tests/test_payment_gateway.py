# 支付网关单元测试

from services.payment import (
    PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult,
    register_gateway, get_gateway, get_gateway_by_provider,
    get_method_options, all_gateways, init_gateways,
)


class TestGatewayRegistry:
    """测试网关注册表"""

    def test_register_and_get(self):
        init_gateways()
        assert get_gateway("mock_qr") is not None
        assert get_gateway("alipay_qr") is not None
        assert get_gateway("epay_qr") is not None
        assert get_gateway("mapay_qr") is not None
        assert get_gateway("nonexistent") is None

    def test_get_gateway_by_provider(self):
        init_gateways()
        assert get_gateway_by_provider("mock") is not None
        assert get_gateway_by_provider("alipay") is not None
        assert get_gateway_by_provider("epay") is not None
        assert get_gateway_by_provider("mapay") is not None
        assert get_gateway_by_provider("unknown") is None

    def test_all_gateways(self):
        init_gateways()
        gateways = all_gateways()
        methods = {g.method_key for g in gateways}
        assert "mock_qr" in methods
        assert "alipay_qr" in methods
        assert "epay_qr" in methods
        assert "mapay_qr" in methods

    def test_get_method_options_none_enabled(self):
        """模拟支付已移除，仅调用 mock_enabled 不应返回任何选项"""
        init_gateways()
        config = {"mock_enabled": True}
        options = get_method_options(config)
        assert options == []

    def test_get_method_options_alipay_epay_enabled(self):
        init_gateways()
        config = {
            "alipay_enabled": True,
            "epay_enabled": True,
        }
        options = get_method_options(config)
        keys = {o["key"] for o in options}
        labels_by_key = {o["key"]: o["label"] for o in options}
        assert "mock_qr" not in keys
        assert "alipay_qr" in keys
        # 易支付默认单通道 alipay → epay_alipay
        assert "epay_alipay" in keys
        assert "epay_qr" not in keys
        assert labels_by_key["epay_alipay"] == "易支付(支付宝)"

    def test_get_method_options_epay_multi_type(self):
        init_gateways()
        config = {
            "epay_enabled": True,
            "epay_type": "alipay,wxpay",
        }
        options = get_method_options(config)
        keys = {o["key"] for o in options}
        labels_by_key = {o["key"]: o["label"] for o in options}
        assert "epay_alipay" in keys
        assert "epay_wxpay" in keys
        assert "epay_qqpay" not in keys
        assert labels_by_key["epay_alipay"] == "易支付(支付宝)"
        assert labels_by_key["epay_wxpay"] == "易支付(微信支付)"

    def test_get_method_options_mapay_multi_type(self):
        init_gateways()
        config = {
            "mapay_enabled": True,
            "mapay_type": "alipay,wxpay,usdt",
        }
        options = get_method_options(config)
        keys = {o["key"] for o in options}
        labels_by_key = {o["key"]: o["label"] for o in options}
        assert "mapay_alipay" in keys
        assert "mapay_wxpay" in keys
        assert "mapay_usdt" in keys
        assert labels_by_key["mapay_alipay"] == "码支付(支付宝)"
        assert labels_by_key["mapay_wxpay"] == "码支付(微信支付)"


class TestMockGateway:
    """测试模拟支付网关"""

    def test_create_checkout(self):
        init_gateways()
        gateway = get_gateway("mock_qr")

        class MockOrder:
            order_no = "TEST123"
            amount = 5900
            currency = "CNY"
            billing_cycle = "monthly"
            payment_method = "mock_qr"
            payment_provider = "mock"
            expired_at = None
            extra_json = {}

        class MockPlan:
            name = "Pro"

        result = gateway.create_checkout(MockOrder(), MockPlan(), {})
        assert result.mode == "mock"
        assert result.can_mock_confirm is True
        assert "TEST123" in result.qr_code_text

    def test_build_checkout_response(self):
        init_gateways()
        gateway = get_gateway("mock_qr")

        class MockOrder:
            order_no = "TEST123"
            amount = 5900
            currency = "CNY"
            billing_cycle = "monthly"
            payment_method = "mock_qr"
            payment_provider = "mock"
            expired_at = None
            extra_json = {}

        class MockPlan:
            name = "Pro"

        checkout = gateway.create_checkout(MockOrder(), MockPlan(), {})
        resp = gateway.build_checkout_response(MockOrder(), MockPlan(), {}, checkout)
        assert resp["method"] == "mock_qr"
        assert resp["provider"] == "mock"
        assert resp["can_mock_confirm"] is True
        assert resp["amount"] == 5900.0
        assert resp["plan_name"] == "Pro"


class TestEpayGateway:
    """测试易支付网关"""

    def test_config_defaults(self):
        init_gateways()
        gateway = get_gateway("epay_qr")
        defaults = gateway.get_config_defaults()
        assert "payment.epay_enabled" in defaults
        assert "payment.epay_gateway" in defaults
        assert "payment.epay_pid" in defaults
        assert "payment.epay_key" in defaults

    def test_epay_sign(self):
        """验证易支付 MD5 签名算法"""
        from services.payment.epay_gateway import _epay_sign
        params = {
            "pid": "1001",
            "type": "alipay",
            "out_trade_no": "TEST202501010001",
            "money": "59.00",
        }
        sign = _epay_sign(params, "test_key_123")
        assert isinstance(sign, str)
        assert len(sign) == 32  # MD5 hex is always 32 chars

    def test_verify_notify_valid(self):
        init_gateways()
        gateway = get_gateway("epay_qr")

        from services.payment.epay_gateway import _epay_sign
        params = {
            "out_trade_no": "TEST123",
            "trade_no": "EPAY202501010001",
            "trade_status": "TRADE_SUCCESS",
            "money": "59.00",
        }
        key = "test_key"
        params["sign"] = _epay_sign(params, key)
        params["sign_type"] = "MD5"

        config = {"epay_key": key}
        result = gateway.verify_notify(params, config)
        assert result.verified is True
        assert result.trade_status == "paid"
        assert result.trade_no == "EPAY202501010001"

    def test_verify_notify_invalid_sign(self):
        init_gateways()
        gateway = get_gateway("epay_qr")

        params = {
            "out_trade_no": "TEST123",
            "trade_no": "EPAY202501010001",
            "trade_status": "TRADE_SUCCESS",
            "sign": "invalid_sign",
            "sign_type": "MD5",
        }
        config = {"epay_key": "test_key"}
        result = gateway.verify_notify(params, config)
        assert result.verified is False

    def test_create_checkout_missing_config(self):
        init_gateways()
        gateway = get_gateway("epay_qr")

        class MockOrder:
            order_no = "TEST123"
            amount = 5900
            billing_cycle = "monthly"
            payment_method = "epay_qr"
            payment_provider = "epay"
            expired_at = None
            extra_json = {}

        class MockPlan:
            name = "Pro"

        import pytest
        with pytest.raises(RuntimeError, match="易支付配置不完整"):
            gateway.create_checkout(MockOrder(), MockPlan(), {})


class TestMaPayGateway:
    """测试码支付网关"""

    def test_config_defaults(self):
        init_gateways()
        gateway = get_gateway("mapay_qr")
        defaults = gateway.get_config_defaults()
        assert defaults["payment.mapay_gateway"] == "https://pay.21lili.cn"
        assert "payment.mapay_enabled" in defaults
        assert "payment.mapay_pid" in defaults
        assert "payment.mapay_key" in defaults

    def test_mapay_sign(self):
        from services.payment.mapay_gateway import _mapay_sign
        params = {
            "pid": "1001",
            "type": "alipay",
            "out_trade_no": "TEST202501010001",
            "money": "59.00",
            "sign_type": "MD5",
            "empty": "  ",
        }
        sign = _mapay_sign(params, "test_key_123")
        assert isinstance(sign, str)
        assert len(sign) == 32

    def test_verify_notify_valid(self):
        init_gateways()
        gateway = get_gateway("mapay_qr")

        from services.payment.mapay_gateway import _mapay_sign
        params = {
            "out_trade_no": "TEST123",
            "trade_no": "MAPAY202501010001",
            "type": "alipay",
            "trade_status": "TRADE_SUCCESS",
            "money": "59.00",
        }
        key = "test_key"
        params["sign"] = _mapay_sign(params, key)
        params["sign_type"] = "MD5"

        result = gateway.verify_notify(params, {"mapay_key": key})
        assert result.verified is True
        assert result.trade_status == "paid"
        assert result.trade_no == "MAPAY202501010001"

    def test_verify_notify_invalid_sign(self):
        init_gateways()
        gateway = get_gateway("mapay_qr")
        params = {
            "out_trade_no": "TEST123",
            "trade_no": "MAPAY202501010001",
            "trade_status": "TRADE_SUCCESS",
            "money": "59.00",
            "sign": "invalid",
        }
        result = gateway.verify_notify(params, {"mapay_key": "test_key"})
        assert result.verified is False

    def test_create_checkout_missing_config(self):
        init_gateways()
        gateway = get_gateway("mapay_qr")

        class MockOrder:
            order_no = "TEST123"
            amount = 5900
            billing_cycle = "monthly"
            payment_method = "mapay_qr"
            payment_provider = "mapay"
            expired_at = None
            extra_json = {}

        class MockPlan:
            name = "Pro"

        import pytest
        with pytest.raises(RuntimeError, match="码支付配置不完整"):
            gateway.create_checkout(MockOrder(), MockPlan(), {})
